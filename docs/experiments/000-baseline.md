# 000: The baseline, measured

**Agent:** `baseline` (strategy prompt v2, `checks: limit+mentions`, `accept_words: reader`). **Reference for this
measurement:** `o1-qwen` (plain O1). **Configs:** `backend/configs/gym/baseline.yaml`, `baseline-holdout.yaml`.
Why the baseline is built this way: [05-learnings.md](../05-learnings.md).

## Dev bench (run_01a0f26323015d857a3b, standard-v1, 240 pairs)

| | Share | Deals | Deals past own limit |
|---|---|---|---|
| **baseline** | **0.341** [0.298, 0.384] | 67.9% | **0** |
| o1-qwen | 0.224 [0.187, 0.261] | 75.0% | 14 |

Baseline − O1: **+0.117** [+0.068, +0.165], p < 0.0001. Ahead against every opponent, most against the scripted
hardliner (+0.244) and liar (+0.165). Deals within own limit: 68% vs 69%. All automatic promotion checks pass.

## Holdout (run_01a0f277daf26258ecff, holdout-v1, 120 pairs)

| | Share | Deals | Deals past own limit |
|---|---|---|---|
| **baseline** | 0.503 [0.420, 0.586] | 73.3% | 0 |
| o1-qwen | 0.470 [0.378, 0.562] | 85.0% | 4 |

Baseline − O1: **+0.033** [−0.059, +0.125], p = 0.49: the same direction, but most of the dev gain doesn't carry
over. Deals within own limit 73% vs 82%: **fails the deal check** by 9 points. By opponent: well ahead of boulware
(+0.196) and O1 with the strategy prompt (+0.166), level with the naive persona and the plain exploiter, and
**behind the exploiter with thinking** (−0.219, p = 0.17, 24 pairs). By cell: +0.121 with 10 rounds, −0.056 with 5.

## What it says

- On the dev bench the baseline is clearly better than plain O1 and never goes past its limit.
- Against opponents it has never seen, the gain shrinks to within noise, and it closes fewer deals. The weak spots are
  the ones the holdout was built to probe: an opponent that waits it out (the thinking exploiter), and a short
  deadline. Both fit the concern that a slow, patterned concession schedule can be exploited. Per the holdout rule,
  this is a direction for dev experiments, not something to mine holdout transcripts for.

## League (run_01a0f2916296a3fe24a2, 200 matches, 20 per pairing)

| # | Agent | Rating | Mean share | Deal rate |
|---|---|---|---|---|
| 1 | boulware | 1610 | 0.417 | 59% |
| 2 | tough-qwen | 1606 | 0.475 | 73% |
| 3 | **baseline** | 1546 | 0.426 | 80% |
| 4 | o2-qwen | 1416 | 0.285 | 76% |
| 5 | o1-qwen | 1322 | 0.259 | 85% |

The baseline is clearly above plain O1 and O2, and level with boulware and the tough persona within noise (±0.07 on
each mean). Boulware is still first by rating, as before the clean start.
