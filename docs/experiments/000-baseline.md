# 000: The baseline, measured

**Agent:** `baseline` (strategy prompt v2, `checks: limit+mentions`, `accept_words: reader`). **Reference for this
measurement:** `o1-qwen` (plain O1). **Configs:** `engine/configs/gym/baseline.yaml`, `baseline-holdout.yaml`.
Why the baseline is built this way: [05-learnings.md](../05-learnings.md#the-current-reference-and-why).

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

## Re-run as an agent package (2026-10-01)

When agents became packages, the baseline became `single_call/v1/baseline` and plain O1 `single_call/v1/o1-qwen`.
Their identity changed (it now hashes their code), but every model request they make is byte for byte the same, so
all three measurements were run again under the new names.

| Run | Before | After |
|---|---|---|
| Dev (run_01a0f788e0c49683e4d1) | baseline 0.341, O1 0.224, Δ +0.117 (p < 0.0001) | baseline 0.343, O1 0.227, Δ +0.115 (p < 0.0001) |
| Holdout (run_01a0f795b19a94d08332) | baseline 0.503, O1 0.470, Δ +0.033 (p = 0.49) | baseline 0.518, O1 0.469, Δ +0.049 (p = 0.30) |
| League (run_01a0f79f52a116144391) | 3rd of 5: boulware 1610, tough-qwen 1606, baseline 1546 | 3rd of 5: boulware 1614, tough-qwen 1599, baseline 1568 |

On dev, 475 of 480 matches ended exactly as before, and on the holdout 236 of 240. The rest diverge where the
original run had a model error (output truncated at max_tokens, which isn't cached, so the re-run asked again), or
where the referee's model reader read a message differently: its requests carry a random tag, so they are never
replayed from the cache. The league is not paired, so its matches were played afresh. Nothing changes in what this
experiment says. On dev the deal check now just fails (68% against 70% within own limit, before 68% against 69%),
which comes from those few matches, not from the agent.

## Learnings

Recorded on 2026-10-01, when the learnings record was introduced.

- L1 strengthened: the dev gain over O1 is significant, but most of it doesn't carry over to the holdout.
- L4 strengthened: boulware is first in the league again.
- L6: the thinking exploiter and the 5-round cell are evidence pointing toward exploitable patterns (not significant).
- L7 strengthened: 0 deals past the limit on dev and holdout, against 14 and 4 for plain O1.
