"""Negotiation scenarios: the hidden ground truth, and what each side is allowed to see.

Every rule we don't know yet (see docs/01 §4) is a knob on `Rules` or `ScenarioSpec`,
so the same code runs under any combination until the organisers answer.
"""
from __future__ import annotations

import itertools
import random
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from regateo.core.roles import Role


class InfoMode(StrEnum):
    PRIVATE = "private"          # each side knows only its own reservation
    RANGE_HINT = "range_hint"    # each side gets a noisy range around the other's reservation
    FULL = "full"                # each side knows the other's reservation


class FirstMover(StrEnum):
    SELLER = "seller"
    BUYER = "buyer"
    RANDOM = "random"


class Rules(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_rounds: int = 8                        # message pairs; a round = one message from each side
    deadline_known: bool = True                # whether agents are told max_rounds
    time_limit_s: float | None = None          # wall-clock budget for the whole match
    per_message_timeout_s: float | None = None
    first_mover: FirstMover = FirstMover.RANDOM
    max_message_chars: int = 2000

    @property
    def max_messages(self) -> int:
        return 2 * self.max_rounds


class PrivateView(BaseModel):
    """Everything one agent is told at the start. Nothing else counts as known."""
    model_config = ConfigDict(frozen=True)

    role: Role
    item: str
    currency: str
    reservation: float                         # our walk-away price
    market_low: float
    market_high: float
    max_rounds: int | None                     # None: deadline hidden
    time_limit_s: float | None
    opponent_range: tuple[float, float] | None = None
    context: str = ""                          # free-text brief, if the platform gives one


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    item: str
    currency: str = "USD"
    seller_reservation: float
    buyer_reservation: float
    market_low: float
    market_high: float
    rules: Rules = Field(default_factory=Rules)
    info_mode: InfoMode = InfoMode.PRIVATE
    seller_hint: tuple[float, float] | None = None   # what the seller is told about the buyer
    buyer_hint: tuple[float, float] | None = None    # what the buyer is told about the seller
    context: str = ""

    @property
    def zopa(self) -> float:
        """Size of the zone of possible agreement. <= 0 means no deal is possible."""
        return self.buyer_reservation - self.seller_reservation

    def reservation(self, role: Role) -> float:
        return self.seller_reservation if role is Role.SELLER else self.buyer_reservation

    def surplus_share(self, role: Role, price: float | None) -> float:
        """Share of the ZOPA that `role` captured. 0 without a deal; negative past our reservation."""
        if price is None or self.zopa <= 0:
            return 0.0
        if role is Role.SELLER:
            return (price - self.seller_reservation) / self.zopa
        return (self.buyer_reservation - price) / self.zopa

    def view_for(self, role: Role) -> PrivateView:
        return PrivateView(
            role=role,
            item=self.item,
            currency=self.currency,
            reservation=self.reservation(role),
            market_low=self.market_low,
            market_high=self.market_high,
            max_rounds=self.rules.max_rounds if self.rules.deadline_known else None,
            time_limit_s=self.rules.time_limit_s,
            opponent_range=self.seller_hint if role is Role.SELLER else self.buyer_hint,
            context=self.context,
        )


DEFAULT_ITEMS = [
    "a used road bike",
    "a vintage film camera",
    "a batch of fifty office chairs",
    "a one-year software licence",
]


class ScenarioSpec(BaseModel):
    """A grid of rule settings plus sampling ranges. Each grid cell yields `per_cell` scenarios."""

    items: list[str] = Field(default_factory=lambda: list(DEFAULT_ITEMS))
    currency: str = "USD"
    seller_reservation: tuple[float, float] = (80, 130)
    zopa: tuple[float, float] = (8, 60)
    market_margin: tuple[float, float] = (15, 40)
    hint_width: float = 0.3                     # range hint width as a share of the market range
    info_modes: list[InfoMode] = Field(default_factory=lambda: [InfoMode.PRIVATE])
    max_rounds: list[int] = Field(default_factory=lambda: [8])
    deadline_known: list[bool] = Field(default_factory=lambda: [True])
    time_limit_s: list[float | None] = Field(default_factory=lambda: [None])
    first_mover: FirstMover = FirstMover.RANDOM
    per_cell: int = 10


def _hint(rng: random.Random, true_value: float, width: float) -> tuple[float, float]:
    lo = true_value - rng.uniform(0, width)
    return (round(lo, 2), round(lo + width, 2))


def sample_scenario(rng: random.Random, spec: ScenarioSpec, rules: Rules, info_mode: InfoMode,
                    scenario_id: str) -> Scenario:
    s = rng.uniform(*spec.seller_reservation)
    b = s + rng.uniform(*spec.zopa)
    lo = s - rng.uniform(*spec.market_margin)
    hi = b + rng.uniform(*spec.market_margin)

    seller_hint = buyer_hint = None
    if info_mode is InfoMode.FULL:
        seller_hint, buyer_hint = (round(b, 2),) * 2, (round(s, 2),) * 2
    elif info_mode is InfoMode.RANGE_HINT:
        w = (hi - lo) * spec.hint_width
        seller_hint, buyer_hint = _hint(rng, b, w), _hint(rng, s, w)

    return Scenario(
        id=scenario_id,
        item=rng.choice(spec.items),
        currency=spec.currency,
        seller_reservation=round(s, 2),
        buyer_reservation=round(b, 2),
        market_low=round(lo),
        market_high=round(hi),
        rules=rules,
        info_mode=info_mode,
        seller_hint=seller_hint,
        buyer_hint=buyer_hint,
    )


def sample_scenarios(spec: ScenarioSpec, seed: int) -> list[Scenario]:
    """Deterministic scenario set for a spec: same spec and seed, same scenarios."""
    rng = random.Random(seed)
    out: list[Scenario] = []
    cells = itertools.product(spec.info_modes, spec.max_rounds, spec.deadline_known, spec.time_limit_s)
    for info_mode, max_rounds, deadline_known, time_limit_s in cells:
        rules = Rules(max_rounds=max_rounds, deadline_known=deadline_known,
                      time_limit_s=time_limit_s, first_mover=spec.first_mover)
        cell = f"{info_mode}-r{max_rounds}-{'known' if deadline_known else 'hidden'}-t{time_limit_s or 0:g}"
        for i in range(spec.per_cell):
            out.append(sample_scenario(rng, spec, rules, info_mode, f"{seed}:{cell}:{i}"))
    return out
