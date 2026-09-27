"""How well does the referee read messages? Compare readings with what each agent meant.

Agents record their intent: LLM agents their decision (`meta.decision`), and on free-text
platforms the protocol keeps every agent's dropped action and price (`meta.intent`). That gives a
labelled example for nearly every message a run produces, at no extra cost.

Two readers are compared on the same messages: the rules alone (recomputed here), and the rules
with the model for ambiguous messages (the stored reading, or its shadow when the model ran in
shadow mode). Intent is a label, not the truth: when an agent's text says something other than
what it meant, the reading can be right and the intent wrong, so read the mismatches.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from regateo.core.messages import Message, Reading, ReadKind
from regateo.referee.reader import same_price, with_readings

_INTENT_KIND = {"offer": ReadKind.OFFER, "accept": ReadKind.ACCEPT, "reject": ReadKind.REJECT,
                "walk_away": ReadKind.REJECT, "message": ReadKind.NONE}


class Intent(BaseModel):
    kind: ReadKind
    price: float | None = None


def intent_of(m: Message) -> Intent | None:
    """What the sender meant, if it was recorded."""
    meta = m.move.meta
    for key in ("intent", "decision"):
        d = meta.get(key)
        if isinstance(d, dict) and d.get("action") in _INTENT_KIND:
            kind = _INTENT_KIND[d["action"]]
            price = d.get("price") if kind is not ReadKind.NONE else None
            return Intent(kind=kind, price=float(price) if price is not None else None)
    if m.move.action is not None and m.move.action.value in _INTENT_KIND:   # structured platforms
        return Intent(kind=_INTENT_KIND[m.move.action.value], price=m.move.price)
    return None


def agrees(r: Reading, intent: Intent) -> bool:
    if intent.kind is ReadKind.REJECT:
        # LLM agents "reject" both silently and with a counter-price; either reading is right.
        if r.kind in (ReadKind.REJECT, ReadKind.NONE):
            return True
        return (r.kind is ReadKind.OFFER and intent.price is not None and r.price is not None
                and same_price(r.price, intent.price))
    if r.kind is not intent.kind:
        return False
    if intent.price is None:
        return True
    return r.price is not None and same_price(r.price, intent.price)


class Score(BaseModel):
    n: int = 0
    correct: int = 0

    @property
    def rate(self) -> float | None:
        return self.correct / self.n if self.n else None

    def add(self, ok: bool) -> None:
        self.n += 1
        self.correct += ok


class Group(BaseModel):
    """Accuracy of each reader on one group of messages."""
    rules: Score = Field(default_factory=Score)
    with_model: Score = Field(default_factory=Score)
    model_calls: int = 0


class Mismatch(BaseModel):
    match_id: str
    idx: int
    sender: str
    agent: str
    text: str
    intent: Intent
    rules: Reading
    with_model: Reading


class ReadingAudit(BaseModel):
    run_id: str
    messages: int = 0
    labelled: int = 0
    unstated: int = 0                                    # intended an offer but wrote no amount: not scored
    clear: Group = Field(default_factory=Group)          # the rules decided alone
    ambiguous: Group = Field(default_factory=Group)      # the rules flagged it; the model may have run
    mismatches: list[Mismatch] = Field(default_factory=list)
    mismatches_total: int = 0


class MatchMessages(BaseModel):
    match_id: str
    seller: str                       # agent labels
    buyer: str
    messages: list[Message]


def audit_readings(run_id: str, matches: Iterable[MatchMessages], max_examples: int = 50) -> ReadingAudit:
    out = ReadingAudit(run_id=run_id)
    for mm in matches:
        rules = with_readings([m.model_copy(update={"reading": None}) for m in mm.messages])
        final = with_readings(mm.messages)
        for m, r_rules, r_final in zip(mm.messages, rules, final, strict=True):
            out.messages += 1
            intent = intent_of(m)
            if intent is None or r_rules.reading is None or r_final.reading is None:
                continue
            if intent.kind is ReadKind.OFFER and intent.price is not None and not r_rules.reading.candidates:
                out.unstated += 1                          # meant a price but didn't write one (stallers)
                continue
            model = _with_model(r_final.reading)
            out.labelled += 1
            group = out.ambiguous if r_rules.reading.ambiguous else out.clear
            ok_rules, ok_model = agrees(r_rules.reading, intent), agrees(model, intent)
            group.rules.add(ok_rules)
            group.with_model.add(ok_model)
            group.model_calls += model.source == "llm"
            if not (ok_rules and ok_model):
                out.mismatches_total += 1
                if len(out.mismatches) < max_examples:
                    out.mismatches.append(Mismatch(
                        match_id=mm.match_id, idx=m.idx, sender=m.sender.value,
                        agent=mm.seller if m.sender.value == "seller" else mm.buyer, text=m.text,
                        intent=intent, rules=_bare(r_rules.reading), with_model=_bare(model)))
    return out


def _with_model(r: Reading) -> Reading:
    """The reading the rules+model reader gives: the stored one, or its shadow when the model
    reader ran in shadow mode (stored only where it differs)."""
    return r.shadow or r


def _bare(r: Reading) -> Reading:
    return r.model_copy(update={"shadow": None})

