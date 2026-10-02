"""Checks for the hard invariants every agent keeps (docs/06-agent-contract.md §3.4), for agents that
want code to veto a move before it is sent. They never choose a move: they only say what is wrong with one.
"""
from __future__ import annotations

import re

from agent_sdk.messages import ActionKind
from agent_sdk.prices import find_prices, fmt_price
from agent_sdk.roles import sign
from agent_sdk.view import PrivateView

TOLERANCE = 0.005

# Any agreement vocabulary, negated or not: "I can't accept", "the moment we agree", "a solid deal".
_AGREEMENT = re.compile(r"\b(?:accept\w*|agree\w*|deal\w*|sold|works for me|sounds good|let's do it)\b", re.IGNORECASE)


def past_limit(view: PrivateView, price: float) -> bool:
    """True when `price` is worse for us than our walk-away price."""
    s = sign(view.role)
    return s * price < s * view.reservation - TOLERANCE


def limit_problems(view: PrivateView, action: ActionKind | str, price: float | None, message: str,
                   standing_offer: float | None, *, mentions: bool = True) -> list[str]:
    """What breaks the walk-away price in a move, as feedback a model can act on. Empty: none.

    - An offer past the limit, or an acceptance when the price accepted is past it. An acceptance is
      checked at both the price it names and `standing_offer`, the other side's latest offer as we read
      it, since a platform may close at either.
    - With `mentions`: any amount in the message past the limit, even one being rejected, since a
      platform reading free text may take "$199 is too much" for an offer of $199.
    """
    action = ActionKind(action)
    problems: list[str] = []
    if action is ActionKind.OFFER:
        if price is None:
            problems.append("an offer needs a price.")
        elif past_limit(view, price):
            problems.append(f"{fmt_price(price, view.currency)} is past your walk-away price.")
    elif action is ActionKind.ACCEPT:
        prices = [p for p in (price, standing_offer) if p is not None]
        if not prices:
            problems.append("there is no offer from the other side to accept.")
        elif any(past_limit(view, p) for p in prices):
            problems.append("accepting their offer would go past your walk-away price.")
    if mentions:
        found = find_prices(message)
        if any(p.currency for p in found):
            found = [p for p in found if p.currency]            # "2 days", "50 chairs" aren't prices
        bad = sorted({p.value for p in found if past_limit(view, p.value)})
        if bad:
            problems.append(f"the message mentions {', '.join(fmt_price(p, view.currency) for p in bad)}, past your "
                            "walk-away price. Don't write prices you would never agree to, not even to reject them.")
    return problems


def standing_problems(view: PrivateView, action: ActionKind | str, price: float | None,
                      their_offer: float | None) -> list[str]:
    """An offer worse for us than the other side's standing offer, as feedback a model can act on. Empty: none.

    Accepting their offer would get more, so the model is asked to accept it or offer something better for us
    than it; which, stays with the model. Pass `their_offer` read defensively (the amount of their own worst for
    us in their latest message that names one), so a planted or quoted amount can't make the check fire. An
    opt-in check for agents that want it (docs/06 §3.4): the user approved it behind a switch, 2026-10-02.
    """
    if ActionKind(action) is not ActionKind.OFFER or price is None or their_offer is None:
        return []
    s = sign(view.role)
    if s * price >= s * their_offer - TOLERANCE:
        return []
    theirs, ours = fmt_price(their_offer, view.currency), fmt_price(price, view.currency)
    return [f"their latest offer, {theirs}, is already better for you than your offer of {ours}. Accept their "
            f"offer, or offer a price better for you than {theirs}."]


def reads_as_agreement(message: str) -> bool:
    """True when the message uses any agreement vocabulary, negated or not. A message that doesn't accept
    should not, since the reader that decides whether a deal closed is unknown."""
    return bool(_AGREEMENT.search(message))
