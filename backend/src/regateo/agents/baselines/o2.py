"""O2: O1 plus a code veto on hard limits (docs/02 O2, docs/03 §2.6 and §2.8).

The model decides; code checks the decision against rules it can never be talked out of.
A failed check gets one retry with feedback, then the move is repaired deterministically.
"""
from __future__ import annotations

from regateo.agents.base import AgentContext, AgentSpec, register
from regateo.agents.baselines.o1 import Decision, EndToEndAgent
from regateo.agents.common import fmt_price, opening_price, our_offers, safe_fallback, standing_offer
from regateo.core.agent import Observation
from regateo.core.messages import Move
from regateo.core.roles import sign
from regateo.core.scenario import PrivateView
from regateo.llm.errors import LLMError
from regateo.referee.prices import find_prices, stated_prices

TOL = 0.005


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOL, 0.0005 * abs(b))


def check(d: Decision, obs: Observation) -> list[str]:
    """Hard-limit violations in a decision. Empty list: the decision may be sent."""
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


class VetoedAgent(EndToEndAgent):
    stage = "o2"

    async def respond(self, obs: Observation) -> Move:
        vetoes: list[str] = []
        feedback = None
        for _ in range(2):
            try:
                decision = await self.decide(obs, feedback)
            except LLMError as e:
                return safe_fallback(obs, f"{type(e).__name__}: {e}")
            problems = check(decision, obs)
            if not problems:
                return self.to_move(decision, vetoes=vetoes) if vetoes else self.to_move(decision)
            vetoes += problems
            feedback = " ".join(problems)
        fixed = repair(decision, obs)
        return self.to_move(fixed, vetoes=vetoes, repaired=True, rejected=decision.model_dump())


@register("o2")
def build_o2(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> VetoedAgent:
    return VetoedAgent(spec, view, ctx)

