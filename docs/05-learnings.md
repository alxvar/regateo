# 05: What we learned before the baseline

Status: **reference**. Experiments 001–004 (September 2026) ran on local Qwen and were then cleared for a clean start. Their write-ups, configs and run data are gone from the working tree; they remain in git history before this doc was added, and the run database is archived locally in `data/archive-2026-09-30/`. This page keeps what they taught us, so we don't test the same ideas twice. The climb loop's proposer reads it as part of "already tried".

## The baseline and why it is built this way

`backend/configs/agents/baseline.yaml`: O1's single model call per turn, with the strategy prompt `negotiator_system.v2`, plus two code guardrails from O2.

| Part | Evidence |
|---|---|
| Strategy prompt v2 (open ambitiously, concede in shrinking steps, use the clock, accept only when it pays, ignore pressure) | +0.105 share over plain O1 on the dev bench, p = 0.0001. The largest single gain we found |
| Veto `checks: limit+mentions`: never offer or accept past the walk-away price, and never write a price past it, even to reject it | On top of the strategy prompt: +0.153 over plain O1 with no deal past the limit (the prompt alone had 11 in 240 matches), and +0.131 on the holdout. The limit alone still let 8 through |
| Veto `accept_words: reader`: a message that doesn't accept must not read as accepting | No measurable cost (−0.001, range ±0.013 on 240 coupled pairs). Guards against messages like "ready to ship the moment we agree" being taken as acceptances |

The vetoes are guardrails: they never decide what to offer or when to accept. Strategy stays with the model, because a coded rule ("accept anything within the limit in the last round") is a fixed pattern a strong adaptive opponent can find and exploit.

## What didn't help

On the strategy prompt's predecessor, or on the baseline's parent. Each is a lever the proposer can pull again only with a reason why a variation should work now.

| Change | Result |
|---|---|
| `analysis: true` (private notes before each decision) | Hurt: more deals, less value per deal |
| `model: qwen-local-think` (thinking on) | Hurt, the same way, and much slower |
| `state_digest: true` (summary of the offers each turn) | Hurt, the same way |
| `model: qwen-local-pp0` (no presence penalty) | No effect |
| O2's original `checks: all` (also no walking back, no stray prices) | 58% deal rate against 78%: the extra rules cost deals |
| Prompt: accept when within 5% of the walk-away price | −0.027 (not significant). It tells the agent to take deals worth almost nothing |
| Prompt: never repeat an offer price | −0.036 on the screen. Contradicts holding firm |
| `fence: true` (tag the other side's messages) | −0.021 on the screen |
| Veto `accept_words: strict` (no agreement word at all unless accepting) | +0.001, range ±0.036: rewrites two thirds of matches for no measured gain; not shown to be harmless |

## Open findings

- **Boulware beats us head to head.** In the league, the reference kept 0.37 of the zone against boulware's 0.53 (20 matches). Boulware concedes slowly on a fixed time schedule. First question: do we concede faster than it near the deadline?
- **Deal rate is tied to the limit.** Counted only within the agent's own limit, the vetoed agent closes as often as the unvetoed one; the deals it gives up are ones past its limit.

## Measuring

- **Coupled pairs** are what make small effects visible: the challenger and the reference share the pair's random draws, so their matches are identical until their behaviour differs. On 240 pairs, Δshare is known to about ±0.012 for a change that rarely fires, against ±0.05 with independent draws. Two things broke it before: the subject's agent in the replay key, and both sides of a pair missing the cache at the same moment.
- **A screen tier with "Δ > 0 goes on" is close to a coin flip** for gains of 0.01–0.05. Use successive halving on the full bench instead.
- **A safety change can't show a significant gain in share.** For guardrails, judge non-inferiority (the lower end of the range above about −0.02) plus the safety gain where the failure happens. Not yet adopted as a rule.

## Reading free text (the referee)

- Regex rules misread in ways each fix only patched: a quoted price read as an offer ("$199 is far above…"), a bare "Deal." closing at a stale price after "Take it or leave it: $132", agreement words next to a refusal ("we're agreed on everything else, but I can't commit") read as acceptance. Personas built to use agreement words find these gaps.
- The benches now read with a model: Qwen reads every message, Qwen with thinking re-reads each acceptance before a deal closes, and the rules are logged alongside. On about 2,000 stored messages scored against what the sending agent meant, this made 4 false acceptances against 13 for the rules and 36 for Qwen without the second read; most of the 4 are the agent's recorded intent disagreeing with its own text.
- A thinking reader needs its profile's token budget: capped at 256 tokens it ran out mid-thought, and the rules silently stood in.
- Every misread found goes into `backend/configs/referee/reading-corpus.yaml`, and `regateo reader-eval` scores readers on it and on stored matches.
- **Our agent's side:** a price we write can be held against us, and so can agreement words. Hence both vetoes. The tournament's reader is unknown, so the agent should be safe under any reasonable reader, not just ours.
