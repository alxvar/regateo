"""Score a message reader on the labeled corpus (configs/referee/reading-corpus.yaml).

Each case is read the way a match reads it: every message in turn, each against the readings of
the ones before. A reading counts as right when it has the same consequence as the label:
"reject" and "none" both leave prices where they were (only a structured walk-away ends a match),
and accepting a price P is the same as offering P when P is the other side's current offer.
What matters most is false acceptances, since an "accept" reading closes a deal.
"""
from __future__ import annotations

from pydantic import BaseModel

from regateo.core.config import configs_dir, load_yaml_dict
from regateo.core.messages import Message, Move, ReadKind
from regateo.core.roles import Role, other
from regateo.referee.reader import OfferReader, same_price, standing_offer


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
    misses: list[Miss]


def load_corpus() -> list[Case]:
    return [Case.model_validate(c) for c in load_yaml_dict(configs_dir() / "referee" / "reading-corpus.yaml")["cases"]]


async def evaluate(reader: OfferReader, name: str, cases: list[Case] | None = None) -> ReaderScore:
    cases = cases if cases is not None else load_corpus()
    misses = []
    false_acc = missed_acc = 0
    for c in cases:
        history: list[Message] = []
        for i, text in enumerate(c.messages):
            sender = Role.BUYER if i % 2 == 0 else Role.SELLER
            m = Message(idx=i, sender=sender, text=text, move=Move(text=text))
            history.append(m.model_copy(update={"reading": await reader.read([*history, m])}))
        r = history[-1].reading
        assert r is not None
        standing = standing_offer(history[:-1], other(history[-1].sender))
        if not _same_consequence(c.kind, c.price, r.kind, r.price, standing):
            misses.append(Miss(case=c, got_kind=r.kind, got_price=r.price, note=r.note))
            false_acc += r.kind is ReadKind.ACCEPT
            missed_acc += c.kind is ReadKind.ACCEPT and r.kind is not ReadKind.ACCEPT
    return ReaderScore(reader=name, cases=len(cases), correct=len(cases) - len(misses), false_accepts=false_acc,
                       missed_accepts=missed_acc, misses=misses)


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
