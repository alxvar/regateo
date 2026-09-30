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

(pending)
