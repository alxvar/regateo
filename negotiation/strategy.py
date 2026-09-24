"""Strategy engine: decides the numbers.

Plain, deterministic code. It never reads the opponent's words, only their offers,
so persuasion, fake deadlines and prompt injection cannot move it.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from .estimator import OpponentModel
from .scenario import PrivateView, sign


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
    time_safety_s: float = 8.0    # act as if the clock is this many seconds shorter (LLM latency)
    price_step: float = 1.0       # offers are rounded to this, in our favour


@dataclass
class Decision:
    action: Literal["offer", "accept"]
    price: float
    phase: Literal["anchor", "bargain", "closing", "last_word"]


class StrategyEngine:
    def __init__(self, view: PrivateView, params: Optional[StrategyParams] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.v = view
        self.p = params or StrategyParams()
        self.s = sign(view.role)
        self.u_res = self.s * view.reservation
        self.width = abs(view.market_high - view.market_low) or 1.0
        self.clock = clock
        self.t0 = clock()
        self.last_u: Optional[float] = None     # our last offer, in u

    # ---- how far through the budget are we? (0 = start, 1 = end) -------------
    def _time_fraction(self) -> float:
        if not self.v.time_limit_s:
            return 0.0
        budget = max(self.v.time_limit_s - self.p.time_safety_s, 1e-6)
        return (self.clock() - self.t0) / budget

    def progress(self, turn: int) -> float:
        n = self.v.max_rounds
        if n:
            t = turn / max(n - 1, 1)
        elif self.v.time_limit_s:
            t = 0.0                    # rounds unknown but a clock exists: let the clock drive
        else:
            # Hidden deadline: pretend it is `assumed_rounds`, then creep towards 1
            # without ever quite reaching it (every extra round might be the last).
            h = max(self.p.assumed_rounds, 2)
            if turn <= h - 1:
                t = 0.9 * turn / (h - 1)
            else:
                t = 0.9 + 0.1 * (1 - 0.7 ** (turn - h + 1))
        return min(max(t, self._time_fraction()), 1.0)

    def _overtime(self, turn: int) -> int:
        if self.v.max_rounds or self.v.time_limit_s:
            return 0
        return max(0, turn - (self.p.assumed_rounds - 1))

    def _is_final_turn(self, turn: int) -> bool:
        n = self.v.max_rounds
        return (n is not None and turn >= n - 1) or self._time_fraction() >= 1.0

    # ---- the decision -------------------------------------------------------------
    def decide(self, opp_u: Optional[float], turn: int, model: OpponentModel) -> Decision:
        p, t = self.p, self.progress(turn)
        remaining = max((self.v.max_rounds or p.assumed_rounds) - turn, 1)

        u_floor = self.u_res + p.min_margin * self.width
        u_est = model.estimate_limit(remaining)
        u_end = max(u_floor, self.u_res + p.keep_share * (u_est - self.u_res))
        overtime = self._overtime(turn)
        if overtime:
            # Hidden deadline and we're past our guess: every extra round might be the last,
            # so lower our planned endpoint a bit each round (this also breaks deadlocks
            # against opponents who are just as stubborn as we are).
            u_end = u_floor + (u_end - u_floor) * p.overtime_decay ** overtime
        u_open = max(model.market_best, model.prior_hi) + p.open_overshoot * self.width
        if self.v.opponent_range:          # a hint tells us where they stop: don't open absurdly past it
            u_open = model.prior_hi + p.open_overshoot * self.width

        # Boulware curve: hold near the anchor, bend towards u_end late.
        target = u_open - (u_open - u_end) * t ** p.boulware
        closing = t >= p.close_by
        if self.last_u is not None:
            if not closing and model.last_step is not None:
                # Reciprocity: before closing time, don't out-concede them.
                cap = max(p.reciprocity * max(model.last_step, 0.0), p.min_step * self.width)
                target = max(target, self.last_u - cap)
            target = min(target, self.last_u)           # never walk an offer back
        target = max(target, u_floor)
        target = math.ceil(target / p.price_step) * p.price_step   # round in our favour

        final = self._is_final_turn(turn)
        last_word = final and not self.v.moves_first   # nobody can answer our next message
        if opp_u is not None:
            if (opp_u >= target
                    or (closing and opp_u >= u_end)
                    or (final and opp_u >= u_floor)
                    or (last_word and opp_u > self.u_res)):
                return Decision("accept", self.s * opp_u, "last_word" if final else "closing")

        self.last_u = target
        phase = "anchor" if turn == 0 else ("last_word" if final else ("closing" if closing else "bargain"))
        return Decision("offer", self.s * target, phase)
