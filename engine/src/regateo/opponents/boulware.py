"""The idea-1 strategy engine as a code-only agent: free, fast, deterministic.

Ported from legacy/idea-1/negotiation/{strategy,estimator}.py. It reads only the opponent's
numbers, never their words, so it's a benchmark for "how far does pure number-play get".
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, fields
from statistics import mean

from agent_sdk import ActionKind, AgentContext, Move, Observation, PrivateView, Role, sign

from regateo.agents.base import AgentSpec, register
from regateo.opponents.common import fmt_price, opponent_offers


@dataclass
class StrategyParams:
    boulware: float = 4.0         # concession curve: 1 = straight line, >1 = hold firm, concede late
    keep_share: float = 0.7       # final offer tries to keep this share of the ESTIMATED surplus
    open_overshoot: float = 0.05  # open this far past the favourable end of the market (share of range)
    close_by: float = 0.85        # after this share of the budget, switch to closing mode
    min_margin: float = 0.02      # never settle closer than this to our reservation (share of range)
    reciprocity: float = 1.5      # before closing, concede at most this many times their last concession
    min_step: float = 0.01        # ...but always move at least this much (share of range)
    assumed_rounds: int = 4       # our guess of the deadline when it is hidden
    overtime_decay: float = 0.7   # past that guess, shrink our planned endpoint by this factor per round
    time_safety_s: float = 8.0    # act as if the clock is this many seconds shorter
    price_step: float = 1.0       # offers are rounded to this, in our favour


class OpponentModel:
    """Guesses the opponent's limit from their offers. All values in u-space (bigger = better for us)."""

    def __init__(self, view: PrivateView):
        self.s = sign(view.role)
        self.u_reservation = self.s * view.reservation
        self.offers: list[float] = []
        market = sorted(self.s * p for p in (view.market_low, view.market_high))
        self.market_best = market[1]
        if view.opponent_range:
            self.prior_lo, self.prior_hi = sorted(self.s * p for p in view.opponent_range)
        else:
            self.prior_lo, self.prior_hi = self.u_reservation, self.market_best

    def set_offers(self, prices: list[float]) -> None:
        self.offers = [self.s * p for p in prices]

    @property
    def last(self) -> float | None:
        return self.offers[-1] if self.offers else None

    @property
    def last_step(self) -> float | None:
        return self.offers[-1] - self.offers[-2] if len(self.offers) >= 2 else None

    def estimate_limit(self, remaining_turns: int) -> float:
        if self.prior_lo == self.prior_hi:
            return self.prior_hi
        floor = max(self.prior_lo, max(self.offers)) if self.offers else self.prior_lo
        prior_mid = (floor + self.prior_hi) / 2
        if not self.offers:
            return prior_mid
        steps = [b - a for a, b in zip(self.offers, self.offers[1:], strict=False)][-3:]
        trend = max(0.0, mean(steps)) if steps else 0.0
        projected = self.offers[-1] + trend * max(remaining_turns, 0) * 0.5
        w = min(1.0, len(self.offers) / 4)
        est = w * projected + (1 - w) * prior_mid
        return min(max(est, floor), self.prior_hi)


class BoulwareAgent:
    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: AgentContext):
        known = {f.name for f in fields(StrategyParams)}
        self.name = spec.label
        self.v = view
        self.p = StrategyParams(**{k: v for k, v in spec.params.items() if k in known})
        self.rng = random.Random(ctx.rng.random())
        self.s = sign(view.role)
        self.u_res = self.s * view.reservation
        self.width = abs(view.market_high - view.market_low) or 1.0
        self.model = OpponentModel(view)
        self.last_u: float | None = None
        self.turn = 0
        self.moves_first: bool | None = None

    def _time_fraction(self, elapsed: float) -> float:
        if not self.v.time_limit_s:
            return 0.0
        return elapsed / max(self.v.time_limit_s - self.p.time_safety_s, 1e-6)

    def _progress(self, elapsed: float) -> float:
        n, turn = self.v.max_rounds, self.turn
        if n:
            t = turn / max(n - 1, 1)
        elif self.v.time_limit_s:
            t = 0.0
        else:   # hidden deadline: pretend it's assumed_rounds, then creep towards 1
            h = max(self.p.assumed_rounds, 2)
            t = 0.9 * turn / (h - 1) if turn <= h - 1 else 0.9 + 0.1 * (1 - 0.7 ** (turn - h + 1))
        return min(max(t, self._time_fraction(elapsed)), 1.0)

    async def respond(self, obs: Observation) -> Move:
        if self.moves_first is None:
            self.moves_first = obs.message_idx == 0
        self.model.set_offers(opponent_offers(obs))
        p, t = self.p, self._progress(obs.elapsed_s)
        remaining = max((self.v.max_rounds or p.assumed_rounds) - self.turn, 1)

        u_floor = self.u_res + p.min_margin * self.width
        u_est = self.model.estimate_limit(remaining)
        u_end = max(u_floor, self.u_res + p.keep_share * (u_est - self.u_res))
        overtime = 0 if (self.v.max_rounds or self.v.time_limit_s) else max(0, self.turn - (p.assumed_rounds - 1))
        if overtime:
            u_end = u_floor + (u_end - u_floor) * p.overtime_decay ** overtime
        u_open = max(self.model.market_best, self.model.prior_hi) + p.open_overshoot * self.width
        if self.v.opponent_range:
            u_open = self.model.prior_hi + p.open_overshoot * self.width

        target = u_open - (u_open - u_end) * t ** p.boulware
        closing = t >= p.close_by
        if self.last_u is not None:
            if not closing and self.model.last_step is not None:
                cap = max(p.reciprocity * max(self.model.last_step, 0.0), p.min_step * self.width)
                target = max(target, self.last_u - cap)
            target = min(target, self.last_u)
        target = max(target, u_floor)
        target = math.ceil(target / p.price_step) * p.price_step

        n = self.v.max_rounds
        final = (n is not None and self.turn >= n - 1) or self._time_fraction(obs.elapsed_s) >= 1.0
        last_word = final and not self.moves_first
        opp_u = self.model.last
        self.turn += 1
        if opp_u is not None and (opp_u >= target or (closing and opp_u >= u_end)
                                  or (final and opp_u >= u_floor) or (last_word and opp_u > self.u_res)):
            price = self.s * opp_u
            return Move(text=self._text("accept", price, "closing"), action=ActionKind.ACCEPT, price=price,
                        meta={"phase": "last_word" if final else "closing"})

        self.last_u = target
        phase = "anchor" if self.turn == 1 else ("last_word" if final else ("closing" if closing else "bargain"))
        price = self.s * target
        return Move(text=self._text("offer", price, phase), action=ActionKind.OFFER, price=price,
                    meta={"phase": phase, "target_u": target, "estimate_u": u_est})

    def _text(self, action: str, price: float, phase: str) -> str:
        p = fmt_price(price, self.v.currency)
        if action == "accept":
            options = [f"Great, I accept {p}. Thanks, a pleasure doing business.", f"Accepted at {p}. Thank you!"]
        elif phase == "anchor":
            options = [f"Thanks for your interest in {self.v.item}. Given its condition and what comparable ones "
                       f"go for, I'm asking {p}." if self.v.role is Role.SELLER else
                       f"I'm interested in {self.v.item}. Based on what similar ones go for, I can offer {p}."]
        elif phase in ("closing", "last_word"):
            options = [f"I've moved as far as I reasonably can. {p} is where I need to be.",
                       f"I appreciate the back and forth. I can do {p}, and that's close to my final position."]
        else:
            options = [f"I hear you, and I want to make this work. I can come to {p}.",
                       f"Thanks, that helps. Meeting you partway: {p}.", f"I appreciate that. My counter is {p}."]
        return self.rng.choice(options)


@register("boulware")
def build_boulware(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> BoulwareAgent:
    return BoulwareAgent(spec, view, ctx)
