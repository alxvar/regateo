"""Early stopping for benchmark gyms: stop playing a challenger once it is clearly behind the reference.

Only ever used to drop losers (docs/04-hill-climbing.md §6). Looking at the results again and again
and stopping at the first good-looking moment would produce false winners, so a challenger is never
promoted early: it either stops as a loser or plays its full share of the bench.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import fmean, stdev

from pydantic import BaseModel

from regateo.core.outcome import Outcome
from regateo.core.roles import Role
from regateo.runner.runner import MatchJob


class EarlyStop(BaseModel):
    min_pairs: int = 48        # first look; smaller samples come from too few scenarios to judge
    every: int = 24            # then look again after this many more pairs
    z: float = 2.58            # stop when mean + z * standard error < 0 (strict, because we look several times)


class Halving(BaseModel):
    """Successive halving (docs/04-hill-climbing.md §6): every challenger plays the first `first` pairs; then
    the better half by mean gain over the reference goes on to twice as many pairs, and so on, until
    `finalists` are left, who play the rest of the bench. More candidates for the same matches, and the
    matches go where the candidates are close. A cut only decides who plays on; promotion still needs the
    full bench."""
    first: int = 48            # pairs before the first cut: 2 scenarios per cell on standard-v1
    keep: float = 0.5          # fraction kept at each cut, rounded up
    finalists: int = 2         # stop cutting at this many


class EarlyStopper:
    """Fed every finished match; tells the runner which jobs to skip. `stopped` maps a subject to
    the number of pairs it had played when it was stopped."""

    def __init__(self, cfg: EarlyStop, challengers: list[str], stopped: dict[str, int] | None = None):
        self.cfg = cfg
        self.challengers = challengers
        self.stopped: dict[str, int] = dict(stopped or {})
        self._pending: dict[str, dict[str, float]] = defaultdict(dict)    # pair -> subject -> share
        self._diffs: dict[str, list[float]] = defaultdict(list)

    def skip(self, job: MatchJob) -> bool:
        subject = job.meta.get("subject")
        if subject == "b":
            return all(c in self.stopped for c in self.challengers)
        return subject in self.stopped

    def record(self, job: MatchJob, outcome: Outcome) -> None:
        self.add(job.meta["pair"], job.meta["subject"], outcome.share(Role(job.meta["role"])))

    def add(self, pair: str, subject: str, share: float) -> None:
        seen = self._pending[pair]
        seen[subject] = share
        if "b" not in seen:
            return                                     # paired once the reference's result arrives
        for s in [s for s in seen if s != "b"] if subject == "b" else [subject]:
            self._diffs[s].append(seen[s] - seen["b"])
            self._check(s)

    def _check(self, subject: str) -> None:
        d = self._diffs[subject]
        n = len(d)
        if subject in self.stopped or n < self.cfg.min_pairs or (n - self.cfg.min_pairs) % self.cfg.every:
            return
        if fmean(d) + self.cfg.z * stdev(d) / math.sqrt(n) < 0:
            self.stopped[subject] = n
