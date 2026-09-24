"""Negotiation scenarios: the hidden ground truth, and what each side is allowed to see.

Because we don't know the real format yet, every unknown is a knob here:
  - info_mode:      how much each side knows about the other's walk-away price
  - max_rounds:     how many message pairs are allowed
  - deadline_known: whether agents are told max_rounds
  - time_limit_s:   an optional wall-clock budget
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal, Optional

Role = Literal["buyer", "seller"]
InfoMode = Literal["private", "range_hint", "full"]

ITEMS = [
    "a used road bike",
    "a vintage film camera",
    "a batch of fifty office chairs",
    "a one-year software licence",
]


def sign(role: Role) -> int:
    """+1 for a seller (higher price is better), -1 for a buyer (lower price is better)."""
    return 1 if role == "seller" else -1


@dataclass
class PrivateView:
    """Everything one agent is told at the start. Nothing else counts as 'known'."""
    role: Role
    item: str
    reservation: float                    # our walk-away price
    market_low: float                     # public, rough price range both sides see
    market_high: float
    max_rounds: Optional[int]             # None = deadline hidden from us
    time_limit_s: Optional[float]         # None = no clock
    opponent_range: Optional[tuple[float, float]] = None  # a hint about THEIR walk-away price
    moves_first: bool = True


@dataclass
class Scenario:
    item: str
    seller_reservation: float
    buyer_reservation: float
    market_low: float
    market_high: float
    max_rounds: int
    deadline_known: bool
    time_limit_s: Optional[float]
    info_mode: InfoMode
    seller_hint: Optional[tuple[float, float]]   # what the seller is told about the buyer
    buyer_hint: Optional[tuple[float, float]]    # what the buyer is told about the seller
    seller_first: bool

    @property
    def zopa(self) -> float:
        """Size of the zone of possible agreement (can be <= 0: no deal possible)."""
        return self.buyer_reservation - self.seller_reservation

    def view_for(self, role: Role) -> PrivateView:
        return PrivateView(
            role=role,
            item=self.item,
            reservation=self.seller_reservation if role == "seller" else self.buyer_reservation,
            market_low=self.market_low,
            market_high=self.market_high,
            max_rounds=self.max_rounds if self.deadline_known else None,
            time_limit_s=self.time_limit_s,
            opponent_range=self.seller_hint if role == "seller" else self.buyer_hint,
            moves_first=self.seller_first == (role == "seller"),
        )

    def surplus_share(self, role: Role, price: Optional[float]) -> float:
        """Share of the ZOPA that `role` captured. 0 when there is no deal."""
        if price is None or self.zopa <= 0:
            return 0.0
        if role == "seller":
            return (price - self.seller_reservation) / self.zopa
        return (self.buyer_reservation - price) / self.zopa


def _hint(rng: random.Random, true_value: float, width: float) -> tuple[float, float]:
    lo = true_value - rng.uniform(0, width)
    return (round(lo, 2), round(lo + width, 2))


def sample_scenario(
    rng: random.Random,
    *,
    max_rounds: int = 8,
    deadline_known: bool = True,
    time_limit_s: Optional[float] = None,
    info_mode: InfoMode = "private",
) -> Scenario:
    s = rng.uniform(80, 130)
    zopa = rng.uniform(8, 60)
    b = s + zopa
    lo = s - rng.uniform(15, 40)
    hi = b + rng.uniform(15, 40)

    seller_hint = buyer_hint = None
    if info_mode == "full":
        seller_hint, buyer_hint = (b, b), (s, s)
    elif info_mode == "range_hint":
        w = (hi - lo) * 0.3
        seller_hint, buyer_hint = _hint(rng, b, w), _hint(rng, s, w)

    return Scenario(
        item=rng.choice(ITEMS),
        seller_reservation=round(s, 2),
        buyer_reservation=round(b, 2),
        market_low=round(lo),
        market_high=round(hi),
        max_rounds=max_rounds,
        deadline_known=deadline_known,
        time_limit_s=time_limit_s,
        info_mode=info_mode,
        seller_hint=seller_hint,
        buyer_hint=buyer_hint,
        seller_first=rng.random() < 0.5,
    )
