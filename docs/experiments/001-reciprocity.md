# 001: Does the baseline concede more than its opponent?

**Status:** done, null. **Run:** run_01a0f2c40f6dd9711968. **Config:** `engine/configs/gym/exp-001-reciprocity.yaml` (standard-v1, successive halving).

## Why

In the league the baseline kept 0.275 of the zone against boulware and 0.284 against tough-qwen. The transcripts
show it jumping toward a firm opponent (as buyer: $105 → $140 → $157 while boulware went $202 → $201 → $197).
Counting offers read by the referee on the dev run (run_01a0f26323015d857a3b), the baseline's concession is larger
than the other side's last one in 46–77% of its moves, and over a match it gives up 1.6–1.8 times as much as the tough
persona and the scripted hardliner. The strategy prompt already says "never concede more than they just did"; the
model doesn't follow it.

| Opponent (dev) | Our moves | Bigger than theirs | Our total ÷ theirs (median) | Share |
|---|---|---|---|---|
| scripted:hardliner | 123 | 77% | 1.77 | 0.280 |
| persona:tough | 123 | 68% | 1.63 | 0.332 |
| persona:manipulator | 119 | 66% | 1.58 | 0.454 |
| persona:injector | 106 | 57% | 1.13 | 0.533 |
| scripted:liar | 106 | 46% | 0.95 | 0.280 |
| scripted:injector | 58 | 55% | 0.33 | 0.164 |

## Challengers

| Agent | Change | Hypothesis |
|---|---|---|
| b1/reciprocity | prompt v3: the reciprocity rule as a step before every offer ("work out how far they moved; move at most that far; if they didn't move, don't") | the rule is there but buried in one sentence |
| b1/moves | `state_digest: moves`: a private per-turn summary of both sides' offers and last moves, without the walk-away comparison | the model can't follow the rule because it can't track the numbers in free text |
| b1/reciprocity-moves | both | the rule needs the numbers |

The full digest hurt in 001 before the reset (more deals, less value), possibly through its line "their offer is $X
better than your walk-away price"; `moves` leaves that line out. Strategy stays with the model: no challenger
changes a price in code.

Risk: holding still against a hardliner costs deals. The deal check (within own limit, −2 points) watches that.

## Result

Successive halving cut b1/reciprocity after 48 pairs (−0.003); the other two played all 240 pairs.

| Agent | Share | Deals | vs baseline | p | Deals within own limit |
|---|---|---|---|---|---|
| baseline | 0.341 | 68% | | | 68% |
| b1/reciprocity-moves | 0.385 | 70% | +0.044 | 0.089 | 70% |
| b1/moves | 0.373 | 78% | +0.033 | 0.18 | 78% |
| b1/reciprocity | (cut at 48) | | −0.003 | 0.96 | |

Neither finalist passes the gain check. No deals past the limit; the deal check passes for both.

Paired Δshare by opponent (240 pairs, 40 per opponent):

| Opponent | b1/moves | b1/reciprocity-moves |
|---|---|---|
| scripted:hardliner | +0.072 | +0.119 |
| scripted:injector | +0.111 | +0.182 |
| scripted:liar | −0.026 | +0.092 |
| persona:tough | +0.023 | −0.035 |
| persona:manipulator | −0.022 | −0.047 |
| persona:injector | +0.037 | −0.048 |

Did the behaviour change? Share of our concessions bigger than the other side's last one:

| Opponent | baseline | b1/moves | b1/reciprocity-moves |
|---|---|---|---|
| scripted:hardliner | 77% | 74% | 65% |
| persona:tough | 68% | 61% | 57% |
| persona:manipulator | 66% | 66% | 59% |
| scripted:liar | 46% | 40% | 32% |

## What it says

- **The hypothesis is not supported.** With the rule spelled out and the moves computed for it, the model still
  outpaces the other side in more than half of its concessions. Qwen doesn't follow the rule, even when it has the
  numbers.
- **The gains come from the scripted opponents, not the firm LLM personas** this was aimed at. Against the tough and
  manipulator personas both variants are level or slightly behind. The scripted opponents have fixed schedules, so
  gains there may not carry over to adaptive opponents.
- **The moves digest raises the deal rate** (78% vs 68%) without deals past the limit, unlike the full digest before
  the reset. Leaving out the walk-away comparison seems to be what removed the harm, but the gain is not significant.
- Not promoted. Both finalists are worth keeping as a direction (information about moves), not as a rule.

## Learnings

Recorded on 2026-10-01, when the learnings record was introduced.

- L3 new: Qwen doesn't follow a numeric concession rule, even with the numbers.
- L2 extended: the moves-only digest is the first per-turn summary that didn't hurt.
- L4 strengthened: we give up 1.6–1.8 times as much as firm opponents over a match.
- L5 new: gains against scripted opponents, none against the LLM personas.
