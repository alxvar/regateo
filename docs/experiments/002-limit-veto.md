# 002: Can a code veto stop deals past our own limit without costing value?

**Bench:** standard-v1, full, with early stopping. **Reference:** o1-qwen. **Config:** `backend/configs/gym/exp-002-limit-veto.yaml`.

## Why

001's winner, o1-v2 (+0.105 share on the full bench), still closed 11 deals past its own walk-away price in 240 matches, so it fails the promotion rule's hard gate ([04 §3.1](../04-hill-climbing.md)). Reading those 11 transcripts shows two causes:

- **It really accepts past its limit.** "Alright, I accept your offer of $140" with a limit of $138.34; "$134 works for me" with $132.21.
- **A price it only quoted is read as an offer.** "I understand your position, but $199 is significantly above the market rate…" was read as an offer of $199, and the hardliner accepted it. On O2's benchmark run, its one remaining past-limit deal was the same pattern: "$125.00 is simply too low" was read as accepting $125. We don't know how the tournament platform reads free text, so a price we write is a price someone may hold us to.

O2's original veto brought past-limit deals from 19 to 1 on the o2-vs-o1 benchmark, but its deal rate fell from 76% to 64%. It also enforces rules unrelated to the limit (no walking back an offer, no stray or leaked prices), which may be what cost the deals.

## Variants

All four use the strategy prompt negotiator_system.v2. The veto (`checks` param on O2, `agents/baselines/o2.py`) gets one retry with feedback, then repairs the move in code.

| Challenger | Veto | Hypothesis |
|---|---|---|
| o1/v2 | none | 001's winner; replays from the cache |
| o2/v2-limit | never offer or accept past the limit | removes the real past-limit deals at almost no cost |
| o2/v2-limit-quiet | + never write a price past the limit, even to reject it | also removes the misread ones |
| o2/v2 | O2's original checks | the extra rules are what cost O2 its deals |

## Results

### Full bench (run_01a0f16d1940f5f62934, 240 pairs, code at acd4aae)

No challenger was stopped early. o1-qwen and o1-v2 replayed from the cache: their numbers equal 001's.

| Variant | Share | vs ref | p | Deal rate | Deals within own limit | Deals past own limit |
|---|---|---|---|---|---|---|
| **o2-v2-limit-quiet** | **0.385** | **+0.153** | <0.0001 | 73.8% | **73.8%** | **0** |
| o1-v2 | 0.336 | +0.105 | 0.0001 | 78.3% | 73.8% | 11 |
| o2-v2-limit | 0.311 | +0.079 | 0.015 | 75.8% | 72.5% | 8 |
| o2-v2 | 0.268 | +0.036 | 0.20 | 58.3% | 57.5% | 2 |
| o1-qwen (ref) | 0.232 | | | 77.5% | 70.8% | 16 |

limit-quiet against o1-v2 directly (paired): +0.048 [-0.006, +0.103], p=0.084.

### What it says

- **Not writing prices past the limit is what matters.** The limit-only veto still let 8 deals past the limit
  through: the agent quoted the other side's price to reject it ("$199 is far above…"), and the referee read that as
  an offer. Forbidding those mentions removes every past-limit deal *and* raises the share (+0.153 vs +0.105 for v2).
  Plausibly because quoting their number anchors the conversation on it.
- **O2's original checks cost deals**, as suspected: 58% deal rate. The rules beyond the limit (no walking back, no
  stray prices) are what hurt.
- **The deal rate drop is the past-limit deals.** limit-quiet closes 73.8% against v2's 78.3%, but v2's 78.3% includes
  11 deals past its own limit (4.6 points). Counting only deals within the agent's own limit, the two are equal, and
  both beat the reference (70.8%).
- **Readings.** `regateo readings` shows limit-quiet with the fewest messages whose reading differs from the agent's
  intent (517, against 693-801 for the others), so its gain doesn't come from referee misreads.

### Promotion checks for o2-v2-limit-quiet

- Gain: pass (+0.153, p<0.0001). Limit: pass (0). Opponents: pass.
- **Deals: fails as the rule is written** (73.8% vs 77.5%, more than 2 points down). It passes if the rule counts only
  deals within the agent's own limit (73.8% vs 70.8%). Decision needed: see "Open".
- Holdout (run_01a0f1815bcc0b7f1097, holdout-v1, 144 pairs): **+0.131** [+0.052, +0.210], p=0.0017. Same direction,
  and significant on its own; ahead against all six unseen opponents (most against the anchoring persona, +0.385, and
  boulware, +0.182). Deal rate 75% vs 80%. **2 deals past its own limit**, both against the scripted staller, and both
  referee misreads, not veto failures: the agent wrote "Take your time… ready to ship the moment we agree" and "…I'm
  confident it's a solid deal for the right person", meaning to chat, and the rules reader took each as a clear
  acceptance of the staller's lowball. Only these two matches were read, to classify the failure.

### Open

- Should the deal-rate check count only deals within the agent's own limit? A past-limit deal scores negative and is a
  hard fail anyway, so counting it as a "deal" in the deal-rate check rewards the thing the limit check forbids.
- The reader takes "deal" and "agree" in a non-accepting message as an acceptance. A tournament platform reading free
  text may do the same, so this is a requirement M2 risk ("never close a deal by accident"). Two fixes, possibly both:
  make the reader stricter (a referee change, so a new bench version), and have the veto reject acceptance words in a
  message that doesn't accept (an agent change, testable now as the next experiment).
