# 001: Does the baseline concede more than its opponent?

**Status:** running. **Config:** `backend/configs/gym/exp-001-reciprocity.yaml` (standard-v1, successive halving).

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

(pending)
