"""Code vetoes on hard limits (docs/02 O2, docs/03 §2.6 and §2.8).

The model decides; code checks the decision against rules it can never be talked out of.
"""
from __future__ import annotations

import re

from agent_sdk import Observation, sign
from regateo.referee.prices import find_prices, stated_prices
from regateo.referee.reader import is_acceptance

from ..lib.common import fmt_price, opening_price, our_offers, standing_offer
from .decision import Decision

TOL = 0.005


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOL, 0.0005 * abs(b))


CHECKS = ("all", "limit", "limit+mentions")
ACCEPT_WORDS = ("reader", "strict")

# Any agreement vocabulary, negated or not: "I can't accept", "the moment we agree", "a solid deal".
_AGREEMENT = re.compile(r"\b(?:accept\w*|agree\w*|deal\w*|sold|works for me|sounds good|let's do it)\b", re.IGNORECASE)


def accept_word_check(d: Decision, mode: str) -> list[str]:
    """A message that doesn't accept must not read as accepting: a platform reading free text may hold us
    to "ready to ship the moment we agree" (experiment 002's holdout). "reader": what our referee's rules
    reader takes as an acceptance; "strict": any agreement vocabulary, since other readers may differ."""
    if d.action == "accept":
        return []
    hit = is_acceptance(d.message) if mode == "reader" else bool(_AGREEMENT.search(d.message))
    if not hit:
        return []
    return ["the message could be read as accepting their offer, but you are not accepting. Don't use words like "
            "'deal', 'agree', 'accept', 'sounds good' or 'works for me' unless you accept."]


def check(d: Decision, obs: Observation, checks: str = "all") -> list[str]:
    """Hard-limit violations in a decision. Empty list: the decision may be sent.

    `checks`: "all" (the original O2 rules), "limit" (only never offer or accept past the walk-away
    price), or "limit+mentions" (also never write a price past it, even to reject it: a platform
    reading free text may take "$199 is too much" for an offer of $199)."""
    if checks != "all":
        return _limit_checks(d, obs, mentions=checks == "limit+mentions")
    v = obs.view
    s = sign(v.role)
    res = v.reservation
    ours = our_offers(obs)
    theirs = standing_offer(obs)
    problems: list[str] = []

    if d.action == "offer":
        if d.price is None:
            problems.append("an offer needs a price.")
        else:
            if s * d.price < s * res:
                problems.append(f"{fmt_price(d.price, v.currency)} is past your walk-away price.")
            if ours and s * d.price > s * ours[-1] + TOL:
                problems.append(f"you already offered {fmt_price(ours[-1], v.currency)}; never walk an offer back.")
    elif d.action == "accept":
        if theirs is None:
            problems.append("there is no offer from the other side to accept.")
        else:
            if d.price is not None and not _near(d.price, theirs):
                problems.append(f"the other side's latest offer is {fmt_price(theirs, v.currency)}; "
                                "you can only accept that exact price.")
            if s * theirs < s * res:
                problems.append("accepting their offer would go past your walk-away price.")

    stated = stated_prices(d.message)
    found = find_prices(d.message)                          # includes negated ones: "not below $100" leaks too
    if any(p.currency for p in found):
        found = [p for p in found if p.currency]            # "2 days", "50 chairs" aren't prices
    mentioned = [p.value for p in found]
    allowed = [p for p in [d.price, theirs, *ours] if p is not None]
    if d.action == "offer" and d.price is not None and not any(_near(p, d.price) for p in stated):
        problems.append(f"the message must state your offer of {fmt_price(d.price, v.currency)}.")
    if any(_near(p, res) for p in mentioned) and not (d.price is not None and _near(d.price, res)):
        problems.append("the message reveals your walk-away price.")
    stray = [p for p in mentioned if not any(_near(p, a) for a in allowed)]
    if stray:
        problems.append(f"the message mentions prices other than your offer and theirs: {stray}.")
    return problems


def _limit_checks(d: Decision, obs: Observation, *, mentions: bool) -> list[str]:
    v = obs.view
    s = sign(v.role)
    theirs = standing_offer(obs)
    past = lambda p: s * p < s * v.reservation - TOL  # noqa: E731
    problems: list[str] = []
    if d.action == "offer":
        if d.price is None:
            problems.append("an offer needs a price.")
        elif past(d.price):
            problems.append(f"{fmt_price(d.price, v.currency)} is past your walk-away price.")
    elif d.action == "accept":
        # An acceptance closes at their standing offer as read, whatever price the decision names: check both.
        prices = [p for p in (d.price, theirs) if p is not None]
        if not prices:
            problems.append("there is no offer from the other side to accept.")
        elif any(past(p) for p in prices):
            problems.append("accepting their offer would go past your walk-away price.")
    if mentions:
        found = find_prices(d.message)
        if any(p.currency for p in found):
            found = [p for p in found if p.currency]        # "2 days", "50 chairs" aren't prices
        bad = sorted({p.value for p in found if past(p.value)})
        if bad:
            problems.append(f"the message mentions {', '.join(fmt_price(p, v.currency) for p in bad)}, past your "
                            "walk-away price. Don't write prices you would never agree to, not even to reject them.")
    return problems


def repair(d: Decision, obs: Observation) -> Decision:
    """Deterministic safe version of a decision that failed its checks twice."""
    v = obs.view
    s = sign(v.role)
    ours = our_offers(obs)
    theirs = standing_offer(obs)
    if d.action == "accept" and theirs is not None and s * theirs >= s * v.reservation:
        return Decision(action="accept", price=theirs, message=f"Agreed, {fmt_price(theirs, v.currency)}. Deal.")
    price = d.price if d.action == "offer" and d.price is not None else (ours[-1] if ours else opening_price(v))
    u = max(s * price, s * v.reservation)                   # never past our reservation
    if ours:
        u = min(u, s * ours[-1])                            # never walk back
    price = round(s * u, 2)
    return Decision(action="offer", price=price, message=f"I can do {fmt_price(price, v.currency)}.")
