"""Referee for one negotiation.

Agents exchange free text. The referee tracks each side's standing offer from the
structured Turn objects; a deal happens when one side accepts the other's standing offer
inside the round and time budget. Anything after the budget scores zero.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from negotiation.scenario import PrivateView, Scenario


class SimClock:
    """Fake wall clock, so time budgets can be tested without waiting."""
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class MatchResult:
    deal: bool
    price: Optional[float]
    messages: int
    transcript: list[tuple[str, str]] = field(default_factory=list)


AgentFactory = Callable[[PrivateView, SimClock], object]


def run_match(scenario: Scenario, make_seller: AgentFactory, make_buyer: AgentFactory,
              rng: random.Random, latency: tuple[float, float] = (1.5, 4.0)) -> MatchResult:
    clock = SimClock()
    agents = {"seller": make_seller(scenario.view_for("seller"), clock),
              "buyer": make_buyer(scenario.view_for("buyer"), clock)}
    order = ["seller", "buyer"] if scenario.seller_first else ["buyer", "seller"]
    standing: dict[str, Optional[float]] = {"seller": None, "buyer": None}
    transcript: list[tuple[str, str]] = []
    incoming: Optional[str] = None

    for i in range(2 * scenario.max_rounds):
        role, other = order[i % 2], order[(i + 1) % 2]
        turn = agents[role].respond(incoming)
        clock.now += rng.uniform(*latency)             # time spent producing the message
        if scenario.time_limit_s and clock.now > scenario.time_limit_s:
            break                                      # arrived too late: doesn't count
        transcript.append((role, turn.text))
        if turn.action in ("accept", "confirm"):
            if standing[other] is not None:
                return MatchResult(True, standing[other], i + 1, transcript)
            continue
        standing[role] = turn.price
        incoming = turn.text
    return MatchResult(False, None, len(transcript), transcript)
