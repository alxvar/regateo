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

### Open

- Full bench (exp-001-o1-levers-full): o1-v2 and o1-informed-v2 against the reference, 240 pairs.
