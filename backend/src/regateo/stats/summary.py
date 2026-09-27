"""Point estimates with confidence intervals."""
from __future__ import annotations

import math
import random
from statistics import NormalDist, fmean

from pydantic import BaseModel


class Estimate(BaseModel):
    """None when there is no data (JSON has no NaN)."""
    mean: float | None
    lo: float | None
    hi: float | None
    n: int


def mean_ci(xs: list[float], *, level: float = 0.95, n_boot: int = 2000, seed: int = 0) -> Estimate:
    """Mean with a bootstrap percentile interval. Deterministic for a given seed."""
    n = len(xs)
    if n == 0:
        return Estimate(mean=None, lo=None, hi=None, n=0)
    m = fmean(xs)
    if n == 1:
        return Estimate(mean=m, lo=m, hi=m, n=1)
    rng = random.Random(seed)
    boots = sorted(fmean(rng.choices(xs, k=n)) for _ in range(n_boot))
    alpha = (1 - level) / 2
    return Estimate(mean=m, lo=boots[int(alpha * n_boot)], hi=boots[min(int((1 - alpha) * n_boot), n_boot - 1)], n=n)


def wilson(k: int, n: int, *, level: float = 0.95) -> Estimate:
    """Rate k/n with a Wilson score interval (well-behaved near 0 and 1)."""
    if n == 0:
        return Estimate(mean=None, lo=None, hi=None, n=0)
    z = NormalDist().inv_cdf(1 - (1 - level) / 2)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return Estimate(mean=p, lo=lo, hi=hi, n=n)
