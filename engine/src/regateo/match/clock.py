"""Match clocks. Real time for LLM matches; simulated time so scripted runs test clocks instantly."""
from __future__ import annotations

import random
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds since the match started."""
        ...

    def after_response(self) -> None:
        """Called once an agent has produced a message."""
        ...


class RealClock:
    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self._t0

    def after_response(self) -> None:
        pass


class SimClock:
    """Each response takes a random simulated latency; nothing actually waits."""

    def __init__(self, latency_s: tuple[float, float] = (1.5, 4.0), seed: int = 0):
        self.t = 0.0
        self.latency_s = latency_s
        self._rng = random.Random(seed)

    def now(self) -> float:
        return self.t

    def after_response(self) -> None:
        self.t += self._rng.uniform(*self.latency_s)
