# 001: Which no-new-components levers make O1 stronger?

**Bench:** standard-v1, tier screen, then full for the survivors. **Reference:** o1-qwen. **Config:** `backend/configs/gym/exp-001-o1-levers.yaml`.

## Why

On the o2-vs-o1 benchmark (run_01a0e4663e0fdb8238ab), O1 captured 0.197 of the zone of possible agreement:
- It opened a median 24% of the market width inside its favourable end (quartiles 15–42%).
- Its deals captured a median 0.20 of the zone.
- 57 of its matches ended at the round limit with no deal.
- It lost track of the numbers, e.g. proposing to "split the difference" at the other side's own price.

## Variants

| Challenger | Change | Hypothesis |
|---|---|---|
| o1/analysis | private `analysis` field, generated before the price | deciding a price with no reasoning is the main weakness |
| o1/think | Qwen thinking mode (model-card sampling) | same, with the model's native reasoning |
| o1/digest | private per-turn summary of offers, moves, gap, messages left | it can't track the numbers from free text |
| o1/pp0 | presence_penalty 1.5 → 0 | the penalty pushes it off its own last price, i.e. towards conceding |
| o1/informed | analysis + digest | the two together |
| o1/informed-v2 | + strategy prompt negotiator_system.v2 | it has a goal but no playbook |

## Results

### Screen, re-scored (run_01a0eebf4e5b9471f849, 96 pairs per challenger)

The first screen (run_01a0eea0326376769483) is superseded. Its referee read "$130 per unit, $6,500 total" as a
price of $6,500 and a refusal ("I don't think we've agreed on $97") as an acceptance. Both are fixed
(`referee/prices.py`, `referee/reader.py`); the re-run replayed from the cache up to the first changed reading.
The totals bug had hit o1-think hardest, since it writes totals habitually, but it is still last.

| Variant | Share | vs ref | p | Deal rate | Median share in deals | Median opening | Deals past own limit |
|---|---|---|---|---|---|---|---|
| o1-v2 | 0.341 | +0.067 | 0.099 | 81% | **0.409** | **-0.04** | 3 |
| o1-informed-v2 | 0.289 | +0.015 | 0.653 | 92% | 0.259 | -0.07 | 2 |
| o1-qwen (ref) | 0.274 | | | 78% | 0.318 | -0.24 | 3 |
| o1-pp0 | 0.247 | -0.027 | 0.435 | 78% | 0.225 | -0.19 | 4 |
| o1-digest | 0.180 | -0.094 | 0.007 | 88% | 0.108 | -0.26 | 6 |
| o1-informed | 0.169 | -0.105 | 0.005 | 96% | 0.075 | -0.24 | 9 |
| o1-analysis | 0.148 | -0.126 | 0.001 | 90% | 0.065 | -0.24 | 8 |
| o1-think | 0.121 | -0.153 | <0.001 | 88% | 0.051 | -0.31 | 1 |

Opening: the first offer's distance inside the favourable end of the market, as a share of the market width (0 = at the end).

### What it says

- **Reasoning and information alone make O1 worse.** Analysis, thinking and the digest each raise the deal rate
  (78% to 88-96%) but cut the median share per deal from 0.32 to 0.05-0.11. Given room to think or a clear view of
  the gap, the model reasons its way to agreement, not to value. None of them fixes the weak opening.
- **The strategy prompt is the lever.** o1-v2 opens at the market end (-0.04 vs -0.24) and keeps 0.41 of the zone
  per deal, at the reference's deal rate.
- **Adding analysis + digest to the strategy prompt costs value** (informed-v2 +0.015 vs v2 +0.067): more deals, but
  a lower share per deal, the same pattern as without the strategy prompt.
- **Presence penalty: no effect.** Hypothesis rejected.
- The digest line "their latest offer is $X better than your walk-away price" may invite settling for anything
  above the limit. Suspect, untested.

### Full bench (run_01a0eec5c2bc5764a1f1, 240 pairs, code at 6324778)

| Variant | Share | vs ref | 95% CI | p | Deal rate | Median share in deals | Deals past own limit |
|---|---|---|---|---|---|---|---|
| **o1-v2** | **0.336** | **+0.105** | | **0.0001** | 78% | 0.415 | 11 |
| o1-informed-v2 | 0.258 | +0.026 | [-0.022, +0.075] | 0.28 | 91% | 0.185 | 10 |
| o1-qwen (ref) | 0.232 | | | | 78% | 0.291 | 16 |

o1-v2 vs the reference, by slice:

| Slice | v2 | ref | diff | p |
|---|---|---|---|---|
| persona:tough | 0.389 | 0.192 | +0.197 | <0.001 |
| persona:injector | 0.630 | 0.471 | +0.159 | 0.024 |
| scripted:hardliner | 0.233 | 0.089 | +0.143 | 0.029 |
| scripted:liar | 0.188 | 0.075 | +0.114 | 0.045 |
| scripted:injector | 0.168 | 0.153 | +0.016 | 0.82 |
| persona:manipulator | 0.411 | 0.411 | -0.001 | 0.99 |
| seller | 0.434 | 0.312 | +0.122 | 0.003 |
| buyer | 0.239 | 0.152 | +0.087 | 0.008 |
| deadline known | 0.368 | 0.243 | +0.125 | <0.001 |
| deadline hidden | 0.305 | 0.220 | +0.084 | 0.039 |

### Conclusion

The strategy prompt (negotiator_system.v2) is worth +0.105 share on standard-v1, broadly across opponents, roles
and deadline settings, at the same deal rate. Private analysis, Qwen thinking and the per-turn digest each make the
agent more agreeable and cost value, with or without the strategy prompt. Presence penalty has no effect.

### Open

- Promote o1-v2 to reference (pending the promotion rule in docs/04-hill-climbing.md).
- o1-v2 still closes 11 deals past its own limit: the O2 code veto on top of v2 should remove those.
- The buyer side still trails the seller side (0.24 vs 0.43).
