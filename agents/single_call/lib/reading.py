"""Reading the other side's messages with rules: what each one does (offer, accept, reject, nothing) and at
what price. single_call's own reader, for the private state digest and the accept-word veto.

It started as a copy of the engine referee's first rule reader (rules-v1) and is this architecture's
own now: the referee may change or read with a model, and this code stays as it is.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from agent_sdk import ActionKind, Message, Role, other
from agent_sdk.prices import find_prices, without_totals

PRICE_TOLERANCE = 0.005   # absolute, after rounding to cents


class ReadKind(StrEnum):
    OFFER = "offer"              # puts a price forward
    ACCEPT = "accept"            # accepts the other side's price
    REJECT = "reject"            # refuses or walks away
    NONE = "none"                # no price move (talk, questions, restating a price)


@dataclass(frozen=True)
class Reading:
    kind: ReadKind
    price: float | None = None   # None when the message names no price, or the offer among several is unclear
    candidates: list[float] = field(default_factory=list)   # amounts the message names


ACCEPT = re.compile(
    r"\b(?:deal|i accept|we accept|happy to accept|accepted|agreed|i agree|we agree|you've got a deal|"
    r"it's a deal|sold|let's do it|works for me|sounds good|we have a deal|deal's done|deal done|"
    r"acceptable to me|is acceptable|you have a deal|you've got yourself a deal|it is(?=\s*[.!]))",
    re.IGNORECASE,
)
# "deal" as a noun ("a fair deal for both", "close the deal today") is not an acceptance.
_NEUTRAL_DEAL = re.compile(r"\b(?:the|a|this|that|fair|good|great|reasonable|close|closing|seal|make|making)\s+deal\b",
                           re.IGNORECASE)
NOT_ACCEPT = re.compile(
    r"\b(?:no deal|not a deal|deal\?|deal is off|if you|would you|could you|how about|what about|counter|"
    r"if (?:that|this|it) works|misunderstanding|pass on|walk away|walking away|"
    r"end(?:ing)? (?:this|the) negotiation|disregard)\b"
    # a negation shortly before an agreement verb: "have not accepted", "can't close this deal at",
    # "never agreed to", "not quite where I can close", "isn't acceptable"
    r"|\b(?:not|never|cannot|unable to|\w+n't)\s+(?:[\w'’]+\s+){0,4}?"
    r"(?:accept|agree|close|sell|proceed|finali[sz]e|acceptable)\w*",
    re.IGNORECASE,
)
_RANGE = re.compile(r"[$€£]\s?\d[\d,.]*k?\s*(?:-|–|—|to)\s*[$€£]?\s?\d|\d[\d,.]*k?\s*(?:-|–|—|to)\s*[$€£]\s?\d"
                    r"|\bbetween\s+[$€£]?\s?\d[\d,.]*k?\s+and\s+[$€£]?\s?\d", re.IGNORECASE)
_QUOTE_WINDOW = 2   # the other side's messages whose amounts count as quotes when restated
_OFFER_CUE = re.compile(
    r"\b(?:i can do|i could do|i can go|how about|what about|would you take|would .{0,20}work|my price|"
    r"my offer|i'll (?:do|take|go|pay|sell)|i will (?:do|take|go|pay|sell)|i'd (?:do|take|go|pay|sell)|"
    r"let's say|meet (?:you )?at|final offer|offering|i'm at|i am at|go up to|go down to|come down to|"
    r"come up to|stretch to|move to|maximum is|minimum is|best i can do)\b",
    re.IGNORECASE,
)
# Refusing a price rather than offering it: "I'm not ready to meet at that level", "$175 is above
# what I can justify", "too high for me".
_REFUSAL = re.compile(
    r"\b(?:not|never|cannot|unable to|\w+n't)\s+(?:[\w'’]+\s+){0,4}?(?:meet|go|do|pay|afford|justify|sell|take)\b"
    r"|\b(?:above|below|beyond|over|under) (?:what i can|my budget|my limit|my minimum|my maximum)"
    r"|\btoo (?:high|low|steep|much)\b",
    re.IGNORECASE,
)

Read = tuple[Message, Reading]


def is_acceptance(text: str) -> bool:
    return bool(ACCEPT.search(_NEUTRAL_DEAL.sub(" ", text))) and not NOT_ACCEPT.search(text)


def same_price(a: float, b: float) -> bool:
    return abs(round(a, 2) - round(b, 2)) <= PRICE_TOLERANCE


def _has(values: Sequence[float], p: float) -> bool:
    return any(same_price(p, v) for v in values)


def _latest_offer(earlier: Sequence[Read], role: Role) -> Reading | None:
    for m, r in reversed(earlier):
        if m.sender is role and r.kind is ReadKind.OFFER:
            return r
    return None


def _standing_offer(earlier: Sequence[Read], role: Role) -> float | None:
    latest = _latest_offer(earlier, role)
    return latest.price if latest else None


def _offer_options(earlier: Sequence[Read], role: Role) -> list[float]:
    latest = _latest_offer(earlier, role)
    if latest is None:
        return []
    return [latest.price] if latest.price is not None else list(latest.candidates)


def read(messages: Sequence[Message]) -> list[Reading]:
    """A reading of every message, in order; each is read in the light of the ones before it."""
    out: list[Read] = []
    for m in messages:
        out.append((m, _read(m, out)))
    return [r for _, r in out]


def _read(m: Message, earlier: Sequence[Read]) -> Reading:
    them = other(m.sender)
    standing = _standing_offer(earlier, them)
    if m.move.action is not None:
        return _structured(m, standing)

    mentions = without_totals([p for p in find_prices(m.text) if not p.negated])
    named: list[float] = []
    for v in [p.value for p in mentions if p.currency] or [p.value for p in mentions]:
        if not _has(named, v):
            named.append(v)
    ranges = [r.span() for r in _RANGE.finditer(m.text)]
    in_range = [p.value for p in mentions if any(a <= p.start < b for a, b in ranges)]
    recent = [e for e, _ in earlier if e.sender is them][-_QUOTE_WINDOW:]
    theirs = [p.value for e in recent for p in find_prices(e.text)]
    mine = [p.value for e, _ in earlier if e.sender is m.sender for p in find_prices(e.text)]
    own = [p for p in named if not _has(theirs, p)]        # not quoting the other side
    fresh = [p for p in own if not _has(mine, p)]         # not repeating ourselves either
    their_offers = [r.price for e, r in earlier if e.sender is them and r.kind is ReadKind.OFFER
                    and r.price is not None]
    options = _offer_options(earlier, them)

    def reading(kind: ReadKind, price: float | None = None) -> Reading:
        return Reading(kind=kind, price=price, candidates=named)

    if is_acceptance(m.text):
        if not named:
            return reading(ReadKind.ACCEPT, standing)
        if fresh:
            # Acceptance words next to a new amount of our own: a counter ("that's a good deal
            # for you: $140"), not an acceptance.
            return reading(ReadKind.OFFER, fresh[-1] if len(fresh) == 1 else None)
        if standing is not None and _has(named, standing):
            return reading(ReadKind.ACCEPT, standing)
        if standing is None and len(named) == 1 and _has(options, named[0]):
            return reading(ReadKind.ACCEPT, named[0])
        if len(named) == 1 and _has(their_offers, named[0]):
            return reading(ReadKind.ACCEPT, named[0])
        if own:
            # "Great, we agree at $90!" when they never offered $90: a claim, i.e. an offer at $90.
            return reading(ReadKind.OFFER, own[-1] if len(own) == 1 else None)
        return reading(ReadKind.NONE)
    if not named:
        return reading(ReadKind.NONE)
    if ranges:
        outside = [p for p in fresh if not _has(in_range, p)]
        if len(outside) == 1:
            return reading(ReadKind.OFFER, outside[0])
        return reading(ReadKind.OFFER)
    if len(fresh) == 1:
        return reading(ReadKind.OFFER, fresh[0])
    if not fresh and len(own) == 1:
        return reading(ReadKind.OFFER, own[0])                # restating our own offer
    if not own:
        # A refusal of their one price is not an offer of it; with two amounts, it refuses one and offers the other.
        if _OFFER_CUE.search(m.text) and (len(named) > 1 or not _REFUSAL.search(m.text)):
            return reading(ReadKind.OFFER, named[-1])
        return reading(ReadKind.NONE)
    return reading(ReadKind.OFFER)


def _structured(m: Message, standing: float | None) -> Reading:
    a, price = m.move.action, m.move.price
    if a is ActionKind.OFFER:
        return Reading(kind=ReadKind.OFFER, price=price)
    if a is ActionKind.ACCEPT:
        return Reading(kind=ReadKind.ACCEPT, price=price if price is not None else standing)
    if a in (ActionKind.REJECT, ActionKind.WALK_AWAY):
        return Reading(kind=ReadKind.REJECT)
    return Reading(kind=ReadKind.NONE)
