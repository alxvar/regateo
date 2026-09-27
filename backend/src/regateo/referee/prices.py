"""Find money amounts in free text.

Returns every candidate with its position and flags instead of guessing one "the price",
so callers can be strict (idea-1 took the last amount and read "$150, definitely not $100"
as 100; see docs/learnings/idea-1.md §3.4).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from regateo.core.messages import Message
from regateo.core.roles import Role, other

_CUR_PREFIX = r"(?P<pre>[$€£]|(?:USD|EUR|GBP|US\$)\s?)"
_NUMBER = r"(?P<num>\d{1,3}(?:[,\u202f]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_SCALE = r"(?P<scale>\s?(?:k|K|m|M|thousand|million)\b)"
_CUR_SUFFIX = r"(?P<post>\s?(?:[$€£]|USD|EUR|GBP|dollars?|euros?|bucks|pounds?)\b)"

_MONEY = re.compile(
    rf"(?<![\w.]){_CUR_PREFIX}?{_NUMBER}{_SCALE}?{_CUR_SUFFIX}?(?![\w%]|\.\d)",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:not|never|nor|won't|can't|cannot|wouldn't|couldn't)\b[^.!?;\d]{0,20}$",
                       re.IGNORECASE)
_SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}


@dataclass(frozen=True)
class PriceMention:
    value: float
    start: int
    end: int
    currency: bool      # had a currency symbol/word, or a k/m scale
    negated: bool       # preceded closely by a negation ("definitely not $100")

    @property
    def strong(self) -> bool:
        return self.currency and not self.negated


def find_prices(text: str) -> list[PriceMention]:
    out = []
    for m in _MONEY.finditer(text):
        num = float(re.sub(r"[,\u202f]", "", m.group("num")))
        scale = (m.group("scale") or "").strip().lower()
        if scale:
            num *= _SCALES[scale]
        out.append(PriceMention(
            value=round(num, 2),
            start=m.start(),
            end=m.end(),
            currency=bool(m.group("pre") or m.group("post") or scale),
            negated=bool(_NEGATION.search(text[max(0, m.start() - 40): m.start()])),
        ))
    return out


def stated_prices(text: str, *, require_currency: bool = False) -> list[float]:
    """Distinct, non-negated amounts in order of appearance.

    If any amount is currency-marked, only marked ones count ("50 chairs for $900" -> [900]).
    """
    mentions = [p for p in find_prices(text) if not p.negated]
    if require_currency or any(p.currency for p in mentions):
        mentions = [p for p in mentions if p.currency]
    seen: list[float] = []
    for p in mentions:
        if p.value not in seen:
            seen.append(p.value)
    return seen


def offered_price(text: str, quoted: Iterable[float] = ()) -> float | None:
    """The one price a message puts forward, for display and analysis.

    Negotiators restate the other side's number before countering ("$120 is too low, I can do
    $155"), so amounts equal to a price in `quoted` (what the other side said earlier) are
    skipped, and the last remaining one is the offer. If every amount is a quote, the message is
    repeating or accepting that price, and the last one is returned.
    """
    mentions = [p for p in find_prices(text) if not p.negated]
    prices = [p.value for p in mentions if p.currency] or [p.value for p in mentions]
    if not prices:
        return None
    theirs = set(quoted)
    own = [p for p in prices if p not in theirs]
    return (own or prices)[-1]


def offer_path(messages: Sequence[Message]) -> list[float | None]:
    """`offered_price` for each message of a transcript: the structured price where the platform
    carried one, otherwise read from the text with the other side's earlier amounts as quotes."""
    said: dict[Role, list[float]] = {Role.SELLER: [], Role.BUYER: []}
    out: list[float | None] = []
    for m in messages:
        if m.move.price is not None:
            p = m.move.price
        else:
            p = offered_price(m.text, said[other(m.sender)])
        said[m.sender] += [x.value for x in find_prices(m.text)]
        out.append(p)
    return out
