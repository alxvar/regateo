import random

from regateo.stats import bradley_terry, match_score, mean_ci, paired_test, wilson


def test_mean_ci_covers_true_mean_most_of_the_time():
    rng = random.Random(0)
    covered = 0
    for trial in range(100):
        xs = [rng.gauss(0.5, 0.2) for _ in range(60)]
        e = mean_ci(xs, seed=trial)
        covered += e.lo <= 0.5 <= e.hi
    assert 88 <= covered <= 99


def test_empty_is_none_not_nan():
    assert mean_ci([]).mean is None and wilson(0, 0).lo is None and paired_test([]).p_value is None


def test_wilson_bounds():
    e = wilson(0, 20)
    assert e.mean == 0 and e.lo == 0 and 0.1 < e.hi < 0.2
    assert wilson(20, 20).hi == 1


def test_paired_exact_and_sampled():
    assert paired_test([0.1, 0.2, 0.3, 0.4]).p_value == 2 / 16          # only all-plus and all-minus as extreme
    assert paired_test([0.1, -0.1] * 50).p_value > 0.9
    r = paired_test([0.05 + 0.01 * (i % 5) for i in range(100)])
    assert r.p_value < 0.001 and r.a_better == 1 and r.lo > 0


def test_bradley_terry_recovers_order():
    rng = random.Random(1)
    strength = {"a": 4.0, "b": 2.0, "c": 1.0}
    results = []
    for _ in range(300):
        x, y = rng.sample(sorted(strength), 2)
        results.append((x, y, 1.0 if rng.random() < strength[x] / (strength[x] + strength[y]) else 0.0))
    r = bradley_terry(results)
    assert r["a"] > r["b"] > r["c"]
    assert 150 < r["a"] - r["c"] < 330          # true gap: 400*log10(4) ≈ 241


def test_match_score():
    assert match_score(0.7, 0.3, True) == 1 and match_score(0, 0, False) == 0.5
