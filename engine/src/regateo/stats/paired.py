"""Paired comparison: is A better than B on the same scenarios?"""
from __future__ import annotations

import itertools
import math
import random
from statistics import NormalDist, fmean

from pydantic import BaseModel

from regateo.stats.summary import mean_ci

EXACT_MAX_N = 16      # 2^16 sign patterns: exact test is cheap below this
NORMAL_MIN_N = 60     # from here, the sign-flip null is normal (CLT) and sampling it is wasted time


class PairedResult(BaseModel):
    """All None when there are no pairs (JSON has no NaN)."""
    n: int
    mean_diff: float | None
    lo: float | None          # bootstrap CI of the mean difference
    hi: float | None
    p_value: float | None     # two-sided sign-flip permutation test of "mean difference is 0"
    a_better: float | None    # share of pairs with d > 0
    ties: float | None
    b_better: float | None


def paired_test(diffs: list[float], *, n_perm: int = 10_000, n_boot: int = 2000, seed: int = 0) -> PairedResult:
    """Paired differences d_i = score_A - score_B. The sign-flip test makes no normality
    assumption, which matters here: shares pile up at 0 (no deal) and near 0.5."""
    n = len(diffs)
    if n == 0:
        return PairedResult(n=0, mean_diff=None, lo=None, hi=None, p_value=None,
                            a_better=None, ties=None, b_better=None)
    ci = mean_ci(diffs, n_boot=n_boot, seed=seed)
    observed = abs(fmean(diffs))
    eps = 1e-12
    if n <= EXACT_MAX_N:
        hits = total = 0
        for signs in itertools.product((1, -1), repeat=n):
            total += 1
            hits += abs(sum(s * d for s, d in zip(signs, diffs, strict=True)) / n) >= observed - eps
        p = hits / total
    elif n >= NORMAL_MIN_N:
        # Under H0 the sign-flipped sum has mean 0 and variance sum(d^2), and is close to normal.
        scale = math.sqrt(sum(d * d for d in diffs))
        p = 1.0 if scale == 0 else 2 * (1 - NormalDist().cdf(observed * n / scale))
    else:
        rng = random.Random(seed)
        hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in diffs) / n) >= observed - eps
                   for _ in range(n_perm))
        p = (hits + 1) / (n_perm + 1)
    pos = sum(d > 1e-9 for d in diffs) / n
    neg = sum(d < -1e-9 for d in diffs) / n
    return PairedResult(n=n, mean_diff=ci.mean, lo=ci.lo, hi=ci.hi, p_value=min(p, 1.0),
                        a_better=pos, ties=1 - pos - neg, b_better=neg)
