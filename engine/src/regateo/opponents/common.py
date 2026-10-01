"""Helpers shared by the opponents: price formatting, reading the other side's offers, safe fallbacks."""
from __future__ import annotations

from agent_sdk import ActionKind, Message, Move, Observation, PrivateView, Role, sign

from regateo.referee.prices import stated_prices

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def fmt_price(price: float, currency: str = "USD") -> str:
    num = f"{price:,.0f}" if float(price).is_integer() else f"{price:,.2f}"
    sym = _SYMBOLS.get(currency)
    return f"{sym}{num}" if sym else f"{num} {currency}"


def message_offer(m: Message, reader: Role) -> float | None:
    """The price a message offers, read defensively by `reader`.

    Uses the structured field when the platform delivers one. From text, when several prices
    appear, takes the one worst for the reader, so a planted number can't talk us up.
    """
    if m.move.action is ActionKind.OFFER and m.move.price is not None:
        return m.move.price
    prices = stated_prices(m.text)
    if not prices:
        return None
    return min(prices, key=lambda p: sign(reader) * p)


def opponent_offers(obs: Observation) -> list[float]:
    """Every price the opponent has offered so far, oldest first."""
    me = obs.view.role
    out = []
    for m in obs.history:
        if m.sender is not me and (p := message_offer(m, me)) is not None:
            out.append(p)
    return out


def standing_offer(obs: Observation) -> float | None:
    """The opponent's most recent offer, from any of their messages."""
    offers = opponent_offers(obs)
    return offers[-1] if offers else None


def our_offers(obs: Observation) -> list[float]:
    me = obs.view.role
    return [m.move.price for m in obs.history
            if m.sender is me and m.move.action is ActionKind.OFFER and m.move.price is not None]


def opening_price(view: PrivateView) -> float:
    """Favourable end of the public market range, never past our reservation."""
    s = sign(view.role)
    best = max(s * view.market_low, s * view.market_high)
    return s * max(best, s * view.reservation)


def safe_fallback(obs: Observation, reason: str) -> Move:
    """Deterministic move when the model fails: repeat our last offer, or open at the market end."""
    ours = our_offers(obs)
    price = ours[-1] if ours else opening_price(obs.view)
    return Move(
        text=f"My offer stands at {fmt_price(price, obs.view.currency)}.",
        action=ActionKind.OFFER,
        price=price,
        meta={"fallback": reason},
    )
