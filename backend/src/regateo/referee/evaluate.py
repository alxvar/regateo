"""Score a message reader on the labeled corpus (configs/referee/reading-corpus.yaml).

Each case is read the way a match reads it: every message in turn, each against the readings of
the ones before. A reading counts as right when it has the same consequence as the label:
"reject" and "none" both leave prices where they were (only a structured walk-away ends a match),
and accepting a price P is the same as offering P when P is the other side's current offer.
What matters most is false acceptances, since an "accept" reading closes a deal.
"""
from __future__ import annotations

import asyncio
import random

from pydantic import BaseModel

from regateo.core.config import configs_dir, load_yaml_dict
from regateo.core.messages import Message, Move, ReadKind
from regateo.core.roles import Role, other
from regateo.referee.audit import agrees, intent_of
from regateo.referee.reader import OfferReader, same_price, standing_offer
from regateo.storage.store import Store


class Case(BaseModel):
    messages: list[str]
    kind: ReadKind
    price: float | None = None
    source: str = ""


class Miss(BaseModel):
    case: Case
    got_kind: ReadKind
    got_price: float | None
    note: str = ""


class ReaderScore(BaseModel):
    reader: str
    cases: int
    correct: int
    false_accepts: int               # a wrong reading that closes a deal: nobody made it, or not at that price
    missed_accepts: int              # a real acceptance read as something else
    fallbacks: int = 0               # messages the model failed to read, so the rules did
    misses: list[Miss]


def load_corpus() -> list[Case]:
    return [Case.model_validate(c) for c in load_yaml_dict(configs_dir() / "referee" / "reading-corpus.yaml")["cases"]]


async def evaluate(reader: OfferReader, name: str, cases: list[Case] | None = None) -> ReaderScore:
    cases = cases if cases is not None else load_corpus()
    misses = []
    false_acc = missed_acc = fallbacks = 0
    for c in cases:
        history: list[Message] = []
        for i, text in enumerate(c.messages):
            sender = Role.BUYER if i % 2 == 0 else Role.SELLER
            m = Message(idx=i, sender=sender, text=text, move=Move(text=text))
            reading = await reader.read([*history, m])
            fallbacks += "reader model" in reading.note
            history.append(m.model_copy(update={"reading": reading}))
        r = history[-1].reading
        assert r is not None
        standing = standing_offer(history[:-1], other(history[-1].sender))
        if not _same_consequence(c.kind, c.price, r.kind, r.price, standing):
            misses.append(Miss(case=c, got_kind=r.kind, got_price=r.price, note=r.note))
            false_acc += r.kind is ReadKind.ACCEPT
            missed_acc += c.kind is ReadKind.ACCEPT and r.kind is not ReadKind.ACCEPT
    return ReaderScore(reader=name, cases=len(cases), correct=len(cases) - len(misses), false_accepts=false_acc,
                       missed_accepts=missed_acc, fallbacks=fallbacks, misses=misses)


def _same_consequence(kind: ReadKind, price: float | None, got: ReadKind, got_price: float | None,
                      standing: float | None) -> bool:
    quiet = {ReadKind.NONE, ReadKind.REJECT}
    if kind in quiet or got in quiet:
        return kind in quiet and got in quiet
    same = (price is None and got_price is None) or (
        price is not None and got_price is not None and same_price(price, got_price))
    if kind is got:
        return same
    # accept P == offer P, when P is what the other side currently offers: either way the deal is at P
    return same and got_price is not None and standing is not None and same_price(got_price, standing)


class IntentScore(BaseModel):
    """A reader against what LLM agents meant (their recorded decisions), on stored dev matches."""
    reader: str
    matches: int
    messages: int                    # with a recorded intent
    correct: int
    false_accepts: int               # read as an acceptance the sender didn't mean (or at another price)
    missed_accepts: int              # the sender accepted; the reading didn't
    fallbacks: int = 0
    examples: list[dict] = []        # false acceptances first, then other misses: for reading and labeling


async def evaluate_on_runs(store: Store, runs: list[str], readers: dict[str, OfferReader], *, sample: int = 150,
                           seed: int = 0, concurrency: int = 16, examples: int = 30) -> list[IntentScore]:
    """Re-read `sample` stored matches from `runs` with each reader, each on its own earlier readings,
    and score every message whose sender recorded an intent. Refuses holdout runs."""
    rows = []
    for run_id in runs:
        run = await store.get_run(run_id)
        if run is None or run.config.get("purpose") == "holdout":
            raise ValueError(f"{run_id}: not a stored dev run")
        rows += [r for r in await store.list_matches(run_id) if r.status == "done"]
    picked = random.Random(seed).sample(rows, min(sample, len(rows)))
    transcripts = {r.id: [m.model_copy(update={"reading": None}) for m in await store.match_messages(r.id)]
                   for r in picked}
    sem = asyncio.Semaphore(concurrency)
    out = []
    for name, reader in readers.items():
        async def one(mid: str, msgs: list[Message], reader: OfferReader = reader) -> list[tuple]:
            async with sem:
                history: list[Message] = []
                res = []
                for m in msgs:
                    r = await reader.read([*history, m])
                    standing = standing_offer(history, other(m.sender))
                    history.append(m.model_copy(update={"reading": r}))
                    if (it := intent_of(m)) is not None:
                        res.append((mid, m, r, it, standing))
                return res
        results = [x for xs in await asyncio.gather(*(one(k, v) for k, v in transcripts.items())) for x in xs]
        score = IntentScore(reader=name, matches=len(transcripts), messages=len(results), correct=0,
                            false_accepts=0, missed_accepts=0)
        bad: list[tuple[int, dict]] = []
        for mid, m, r, it, standing in results:
            score.fallbacks += "reader model" in r.note
            ok = agrees(r, it) or _same_consequence(it.kind, it.price, r.kind, r.price, standing)
            if ok:
                score.correct += 1
                continue
            false_acc = r.kind is ReadKind.ACCEPT
            score.false_accepts += false_acc
            score.missed_accepts += it.kind is ReadKind.ACCEPT and r.kind is not ReadKind.ACCEPT
            context = [f"{h.sender.value}: {h.text}" for h in transcripts[mid][max(0, m.idx - 4):m.idx + 1]]
            bad.append((0 if false_acc else 1, {
                "match": mid, "idx": m.idx, "context": context, "meant": f"{it.kind.value} {it.price}",
                "read": f"{r.kind.value} {r.price}", "note": r.note}))
        score.examples = [e for _, e in sorted(bad, key=lambda b: b[0])[:examples]]
        out.append(score)
    return out
