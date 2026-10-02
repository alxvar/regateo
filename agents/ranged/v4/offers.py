"""Our own offers so far, read so that free text works too. On a free-text platform our own messages come
back with no action or price: the platform drops them and keeps what we meant in `meta["intent"]` (and our
logged `meta["decision"]`). lib's `our_offers` reads only the action and price, so in free text it found no
offers at all (found after round 1)."""
from __future__ import annotations

from agent_sdk import ActionKind, Observation, sign

from ..lib.common import _readings


def our_offers(obs: Observation) -> list[float]:
    """Our offers so far, oldest first: the move's own action and price when the platform kept them, else what
    we meant (`intent`), else the decision we logged."""
    me = obs.view.role
    out: list[float] = []
    for m in obs.history:
        if m.sender is not me:
            continue
        mv = m.move
        intent = mv.meta.get("intent") or {}
        decision = mv.meta.get("decision") or {}
        if mv.action is ActionKind.OFFER and mv.price is not None:
            out.append(mv.price)
        elif intent.get("action") == ActionKind.OFFER and intent.get("price") is not None:
            out.append(float(intent["price"]))
        elif mv.action is None and decision.get("action") == "offer" and decision.get("price") is not None:
            out.append(float(decision["price"]))
    return out


def their_floor(obs: Observation) -> float | None:
    """Their standing offer for the `standing` veto, read defensively: of the amounts of their own in their latest
    message that names one, the worst for us ("another seller is at $120, but I can do $135": a buyer's floor is
    $135). Amounts that only quote ours don't count, so "$150? Too much." doesn't make our $150 their offer."""
    s = sign(obs.view.role)
    for own, _ in reversed(_readings(obs)):
        if own:
            return min(own, key=lambda p: s * p)
    return None
