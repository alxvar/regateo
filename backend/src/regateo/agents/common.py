"""Helpers shared by agents: price formatting, reading the opponent's offers, safe fallbacks."""
from __future__ import annotations

from regateo.core.agent import Observation
from regateo.core.messages import ActionKind, Message, Move, ReadKind
from regateo.core.roles import Role, sign
from regateo.core.scenario import PrivateView
from regateo.referee.prices import stated_prices
from regateo.referee.reader import with_readings

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


def state_digest(obs: Observation, *, structured: bool, moves_only: bool = False) -> str:
    """A private summary of where the negotiation stands, added to the model's turn so it doesn't
    have to rebuild the numbers from free text. Their offers are read with the referee's rules
    (which skip prices they merely quote); under free text we only use their words, as a real
    opponent's structured intent wouldn't reach us. `moves_only` leaves out how their offer compares
    with our walk-away price, which may invite settling for anything above it."""
    v, me = obs.view, obs.view.role
    s = sign(me)
    f = lambda p: fmt_price(p, v.currency)  # noqa: E731
    history = [m if m.sender is me or structured else m.model_copy(update={"move": Move(text=m.text)})
               for m in obs.history]
    read = with_readings([m.model_copy(update={"reading": None}) for m in history])
    theirs = [m.reading.price for m in read if m.sender is not me and m.reading
              and m.reading.kind is ReadKind.OFFER and m.reading.price is not None]
    ours = our_offers(obs)
    lines = ["[Private notes from your own system, not from the other side]",
             f"- Your offers so far: {' -> '.join(map(f, ours)) if ours else 'none yet'}",
             f"- Their offers so far: {' -> '.join(map(f, theirs)) if theirs else 'none yet'}"]
    moves = []
    if len(theirs) >= 2:
        step = s * (theirs[-1] - theirs[-2])
        moves.append(f"they moved {f(abs(step))} toward you" if step > 0 else
                     f"they moved {f(-step)} away from you" if step < 0 else "they didn't move")
    if len(ours) >= 2:
        moves.append(f"you moved {f(abs(ours[-1] - ours[-2]))} toward them")
    if moves:
        lines.append(f"- Last moves: {'; '.join(moves)}")
    if theirs and not moves_only:
        margin = s * (theirs[-1] - v.reservation)
        where = "better than" if margin > 0 else "worse than" if margin < 0 else "exactly"
        lines.append(f"- Their latest offer {f(theirs[-1])} is {f(abs(margin)) + ' ' if margin else ''}{where} "
                     f"your walk-away price")
    if theirs and ours:
        lines.append(f"- Gap between your latest offer and theirs: {f(abs(ours[-1] - theirs[-1]))}")
    last = read[-1] if read and read[-1].sender is not me else None
    if last and last.reading and last.reading.kind is ReadKind.ACCEPT:
        price = f(last.reading.price) if last.reading.price is not None else "a price"
        lines.append(f"- Their last message reads as accepting {price}")
    if v.max_rounds is not None:
        sent = sum(m.sender is me for m in obs.history)
        lines.append(f"- Your messages left, including this one: {max(v.max_rounds - sent, 0)} of {v.max_rounds}")
    else:
        lines.append("- Messages left: unknown")
    return "\n".join(lines)
