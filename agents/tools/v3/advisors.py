"""The tools the model may call (docs/02 O3): deterministic code that works out facts and gives advice.

Each tool reads only the observation, so its answer is the same every time it is asked. Two of them
suggest prices (`estimate_opponent_limit`, `concession_schedule`): advice the model is free to ignore,
never a decision. The agent logs how far its moves land from that advice (`advice` in the move's meta).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent_sdk import Observation, better_or_equal, sign
from agent_sdk.guards import limit_problems

from ..lib.common import money, opening_price, own_messages_sent, standing_offer, their_offers
from .common import our_offers

TOOLS = {
    "offer_history": "both sides' offers so far, the last moves and the gap between you",
    "estimate_opponent_limit": "a rough estimate of the other side's walk-away price from how their offers moved",
    "concession_schedule": "a suggested price for your next offer: slow concessions early, larger near the end",
    "deadline_belief": "how many messages are probably left, from the rules and what the other side said",
    "check_offer": "whether a price you are considering is safe and sensible to offer (give `price`)",
    "market_facts": "the public market range, and where both sides' offers sit in it",
}
FACT_TOOLS = [t for t in TOOLS if t != "check_offer"]   # the ones that need no argument


@dataclass(frozen=True)
class Settings:
    assumed_rounds: int = 8          # messages per side the schedule assumes when the limit is unknown
    beta: float = 0.4                # schedule shape: below 1 concedes little early and more near the end


def _round(price: float) -> float:
    return float(round(price)) if abs(price) >= 100 else round(price, 2)


def estimate(obs: Observation) -> float | None:
    """Their walk-away price, extrapolated from their concessions: if each step shrinks by a ratio r, the
    steps still to come add up to last_step * r / (1 - r). None before they make an offer."""
    v, s = obs.view, sign(obs.view.role)
    theirs = their_offers(obs)
    if not theirs:
        return None
    if len(theirs) == 1:
        # One offer: assume they'll move about halfway from it to the market end that favours us.
        best = opening_price(v)
        return _round((theirs[0] + best) / 2) if s * best > s * theirs[0] else theirs[0]
    steps = [s * (b - a) for a, b in zip(theirs, theirs[1:], strict=False)]
    last = steps[-1]
    if last <= 0:
        return theirs[-1]                                  # they stopped moving (or moved back)
    r = min(max(last / steps[-2], 0.2), 0.8) if len(steps) >= 2 and steps[-2] > 0 else 0.5
    return _round(theirs[-1] + s * last * r / (1 - r))


def schedule(obs: Observation, settings: Settings) -> float:
    """A suggested next offer: from our opening toward the better for us of our walk-away price and their
    estimated limit, along start + (goal - start) * t^(1/beta), t being how far through the messages we are."""
    v, s = obs.view, sign(obs.view.role)
    ours = our_offers(obs)
    start = ours[0] if ours else opening_price(v)
    est = estimate(obs)
    goal = v.reservation if est is None else s * min(max(s * est, s * v.reservation), s * start)
    total = v.max_rounds or settings.assumed_rounds
    t = min((own_messages_sent(obs) + 1) / total, 1.0)
    price = start + (goal - start) * t ** (1 / settings.beta)
    if ours and s * price > s * ours[-1]:
        price = ours[-1]                                   # never suggest walking an offer back
    return _round(s * max(s * price, s * v.reservation))


_CLAIM = re.compile(r"[^.!?\n]*\b(?:final|last offer|deadline|today|tonight|tomorrow|hours?|minutes?|"
                    r"another (?:buyer|seller|offer)|other (?:buyers|sellers|offers)|walk away|leaving|elsewhere)\b"
                    r"[^.!?\n]*[.!?]?", re.IGNORECASE)


def run(name: str, obs: Observation, settings: Settings, price: float | None = None) -> str:
    v, me = obs.view, obs.view.role
    s = sign(me)
    f = lambda p: money(v, p)  # noqa: E731
    ours, theirs = our_offers(obs), their_offers(obs)
    standing = standing_offer(obs)
    if name == "offer_history":
        lines = [f"Your offers: {' -> '.join(map(f, ours)) if ours else 'none yet'}",
                 f"Their offers: {' -> '.join(map(f, theirs)) if theirs else 'none yet'}"]
        if len(theirs) >= 2:
            step = s * (theirs[-1] - theirs[-2])
            lines.append(f"Their last move: {f(abs(step))} {'toward' if step > 0 else 'away from'} you"
                         if step else "Their last move: none")
        if len(ours) >= 2:
            lines.append(f"Your last move: {f(abs(ours[-1] - ours[-2]))} toward them")
        if len(theirs) >= 2 and len(ours) >= 2:
            lines.append(f"Total moved so far: you {f(abs(ours[-1] - ours[0]))}, they {f(abs(theirs[-1] - theirs[0]))}")
        if ours and theirs:
            lines.append(f"Gap between your latest offer and theirs: {f(abs(ours[-1] - theirs[-1]))}")
        return "\n".join(lines)
    if name == "estimate_opponent_limit":
        est = estimate(obs)
        if est is None:
            return (f"No offers from them yet. Without evidence, their walk-away price most likely lies inside the "
                    f"market range, {f(v.market_low)} to {f(v.market_high)}.")
        return (f"Estimate: about {f(est)} (low confidence: extrapolated from {len(theirs)} offer(s), and they may "
                f"be bluffing). They will at least take their own latest offer, {f(theirs[-1])}.")
    if name == "concession_schedule":
        p = schedule(obs, settings)
        total = v.max_rounds or settings.assumed_rounds
        known = "" if v.max_rounds else f", assuming about {total} (the real limit is unknown)"
        out = f"Suggested next offer: {f(p)} (message {own_messages_sent(obs) + 1} of {total}{known})."
        if standing is not None and better_or_equal(me, standing, p):
            out += f" Their latest offer, {f(standing)}, is already at least as good for you."
        return out
    if name == "deadline_belief":
        sent = own_messages_sent(obs)
        out = (f"The rules allow {v.max_rounds} messages per side. You have sent {sent}, so you have "
               f"{max(v.max_rounds - sent, 0)} left including this one." if v.max_rounds is not None else
               f"The message limit is unknown. You have sent {sent}. It could end within the next few messages.")
        if v.time_limit_s:
            out += f" The whole negotiation must finish within {v.time_limit_s:.0f} seconds."
        claims = [c.group(0).strip()[:160] for m in obs.history if m.sender is not me for c in _CLAIM.finditer(m.text)]
        if claims:
            out += "\nWhat they said about time or alternatives (unverified, may be bluffs):\n" + \
                   "\n".join(f'- "{c}"' for c in claims[-4:])
        return out
    if name == "check_offer":
        if price is None:
            return "check_offer needs a price."
        found = limit_problems(v, "offer", price, "", standing, mentions=False)
        if found:
            return f"{f(price)}: not safe, {' '.join(found)}"
        notes = [f"{f(price)}: safe to offer."]
        if standing is not None and better_or_equal(me, standing, price):
            notes.append(f"But their latest offer, {f(standing)}, is already at least as good for you: accepting it "
                         "would beat offering this.")
        if ours:
            step = s * (ours[-1] - price)
            notes.append(f"That is {f(abs(step))} {'toward them from' if step > 0 else 'away from them, back from'} "
                         f"your last offer, {f(ours[-1])}." if step else "That repeats your last offer.")
        return " ".join(notes)
    if name == "market_facts":
        span = abs(v.market_high - v.market_low) or 1.0
        best = opening_price(v)
        where = lambda p: f"{100 * abs(best - p) / span:.0f}% of the range away from the end that favours you"  # noqa: E731
        lines = [f"Comparable items go for {f(v.market_low)} to {f(v.market_high)}."]
        if ours:
            lines.append(f"Your latest offer {f(ours[-1])} is {where(ours[-1])}.")
        if theirs:
            lines.append(f"Their latest offer {f(theirs[-1])} is {where(theirs[-1])}.")
        return "\n".join(lines)
    return f"unknown tool {name!r}"
