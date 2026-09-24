"""Opponent model: guesses the other side's walk-away price from how they move.

Everything here uses "our utility" units: u = +price for a seller, -price for a buyer.
That way a bigger u is always better for us, and every concession the opponent makes
pushes their offers UP in u. It lets one piece of code serve both roles.
"""
from __future__ import annotations

from statistics import mean
from typing import Optional

from .scenario import PrivateView, sign


class OpponentModel:
    def __init__(self, view: PrivateView):
        self.s = sign(view.role)
        self.u_reservation = self.s * view.reservation
        self.offers: list[float] = []          # their offers, in u
        market = sorted(self.s * p for p in (view.market_low, view.market_high))
        self.market_best = market[1]           # the end of the public range that favours us

        # Prior belief about where their limit sits (in u): [prior_lo, prior_hi].
        if view.opponent_range:
            self.prior_lo, self.prior_hi = sorted(self.s * p for p in view.opponent_range)
        else:
            self.prior_lo, self.prior_hi = self.u_reservation, self.market_best

    def observe(self, price: float) -> None:
        self.offers.append(self.s * price)

    @property
    def last(self) -> Optional[float]:
        return self.offers[-1] if self.offers else None

    @property
    def best(self) -> Optional[float]:
        return max(self.offers) if self.offers else None

    @property
    def last_step(self) -> Optional[float]:
        """How much they conceded with their latest offer (in u)."""
        return self.offers[-1] - self.offers[-2] if len(self.offers) >= 2 else None

    def estimate_limit(self, remaining_turns: int) -> float:
        """Best guess (in u) of the furthest they will go.

        Early on we lean on the prior; as offers come in we lean on their trend:
        'if they keep conceding at this pace, discounted, where do they end up?'
        """
        if self.prior_lo == self.prior_hi:          # full information
            return self.prior_hi
        floor = max(self.prior_lo, self.best) if self.offers else self.prior_lo
        prior_mid = (floor + self.prior_hi) / 2
        if not self.offers:
            return prior_mid

        steps = [b - a for a, b in zip(self.offers, self.offers[1:])][-3:]
        trend = max(0.0, mean(steps)) if steps else 0.0
        projected = self.last + trend * max(remaining_turns, 0) * 0.5
        w = min(1.0, len(self.offers) / 4)          # trust data more as it accumulates
        est = w * projected + (1 - w) * prior_mid
        return min(max(est, floor), self.prior_hi)
