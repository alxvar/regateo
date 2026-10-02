# 002: Climb round 2 over ranged and tools, with red-team findings for the builders

**Status:** done, promoted `ranged/v4/clock-standing`. **Runs:** redteam-01 run_01a0fb89727a10729c73, round-02
run_01a0fc0e5d2cb2a609fb, holdout-01 run_01a0fc50ff316d57faad, redteam-02 run_01a0fc97151ff081a314, league
run_01a0fccbd18fff09faf1. **Configs:** `engine/configs/gym/{redteam-01,round-02,holdout-01,redteam-02}.yaml`,
`engine/configs/arena/league.yaml`.

## Why

Round 1 (run_01a0f9180ca60d701354, five architectures, about 11 hours) left two lines with a clear gain on
`standard-v2`: `ranged/v2/hold` (+0.098, p = 0.0006) and `tools/v1/call` (+0.086, p = 0.003). Round 2 climbs only
those two, to fit in about three hours, and runs the red team first so that its findings reach the builders.

## Plan

1. **Red team on the current agents** (`adversarial-v1`): the reference, `ranged/v2/hold`, `ranged/v3/hold-standing`
   (v2/hold with the veto on offers worse than their standing offer, added after the red team's analysis) and
   `tools/v1/call`.
2. **Builder sessions**, one per line (`regateo round export --redteam RUN`): round-01's dev results plus a summary of
   the red-team run (share by opponent, each attack against its plain twin, exploit signals, the end of the worst
   match against each attack), not its transcripts.
3. **Dev round** on `standard-v2` with successive halving within each line and early stopping; the reference and the
   parents replay from the cache.
4. **Holdout** (`holdout-v2`) for each line's finalist, **red team** again, then the **league** for a promoted agent.

## Red team before the round

| Attack, cost (share against it minus against its plain twin) | baseline | ranged/v2/hold | ranged/v3/hold-standing | tools/v1/call |
|---|---|---|---|---|
| `redteam:llm` (Qwen with thinking and a brief of our weaknesses) | −0.27 | −0.18 | −0.20 | (misread, see below) |
| quote-accept (gets us to restate its price, then "accepts" it) | +0.02 | −0.16 | −0.14 | −0.19 |
| echo | −0.00 | +0.05 | +0.01 | −0.03 |
| misquote | +0.03 | −0.02 | −0.04 | +0.02 |

Overall against the reference: v3/hold-standing +0.037 (p = 0.03), v2/hold +0.022. tools concedes on 143 of its 155
moves against stonewall, which never moves.

**A referee misread:** in one tools match (fifty office chairs, $135 per chair agreed) the reader took the $6,750 lot
total as the price and scored a deal far past our limit, share −133. It is the only deal past a limit in the run. The
builder's summary said so; the reader is fixed with its bench, so it is not corrected here.

## Builders

Claude Code in the builder sandbox, same inputs, run twice: Sonnet 5.5 (default effort) and Opus 5.5 (effort high).
There was time to measure only one set; Sonnet's is on branch `round-02-sonnet`, not measured.

- **Sonnet:** ranged `v4/endgame` and `v4/endgame-standing` (the strategist told whether their offer is within our
  limit and that a reply to our last message can't be accepted, with a prompt weighing a sure deal against holding);
  tools `v3/closing`, `v3/closecheck` (facts or a prompt rule on their standing offer near the end), `v1/linear`
  (a linear concession schedule).
- **Opus:** found two bugs Sonnet didn't. ranged's ledger, since v2, stated the other side's movement backwards ("not
  toward you" exactly when they had moved toward us), under a prompt whose rule is to concede only when they move.
  tools' acceptance check also tested the price read as their latest offer, so a competitor's or planted amount past
  our limit in their message blocked a good acceptance (17 times against the LLM opponents by its count).

Measured: Opus's set. Left out by hand: `tools/v3/horizon` (it told the model "negotiations here allow 5 to 10
messages per side", which no known tournament rule says) and `ranged/v3/hold-standing` (`v4/hold-standing` is the
same agent with the ledger fix).

| Agent | Change |
|---|---|
| ranged/v4/hold-standing | v3/hold-standing with the ledger fix |
| ranged/v4/clock-standing | plus `clock`: messages sent by each side, when the negotiation can end (or that the limit is unknown), the gap between the latest offers; a strategist prompt on closing a small gap before the messages run out |
| ranged/v4/clock-standing-plain | plus: don't call an offer final unless it is the last message |
| tools/v3/call | v2's code (our own offers read correctly, one retry), with the acceptance checked at the price our message names |
| tools/v3/standing | plus the veto on offers worse than their standing offer, which the model may override on its second draft |

Code states facts only in all of them; prices and when to accept stay with the model.

## Result on dev

About 1.5 hours, 1,776 matches, none failed.

| Agent | vs baseline | p | n (scored pairs) | |
|---|---|---|---|---|
| ranged/v4/clock-standing | +0.141 | <0.0001 | 240 | finalist |
| ranged/v2/hold (parent) | +0.139 | 0.025 | 48 | cut after 96 pairs |
| ranged/v4/hold-standing | +0.194 | 0.046 | 24 | cut after 48 |
| ranged/v4/clock-standing-plain | +0.136 | 0.11 | 24 | cut after 48 |
| tools/v1/call (parent) | +0.089 | 0.002 | 240 | finalist |
| tools/v3/standing | +0.091 | 0.19 | 48 | cut after 96 |
| tools/v3/call | +0.188 | 0.089 | 24 | cut after 48 |

- **clock-standing against v2/hold itself**, on the same 240 scored pairs (the reference replayed identically):
  +0.043 [−0.009, +0.095], p = 0.11; on the gates +0.089, p = 0.0002. Against the reference it gains against every
  scored opponent (tough +0.105, manipulator +0.169, injector +0.148) and both cells; deals within its own limit 87%
  against 73%. Offers worse than their standing offer fell from 13% of its matches to 4%, and no-deals from 104 to
  70 (`regateo signals`).
- **The first cuts were within noise.** After 24 scored pairs, `v4/hold-standing` was 0.004 behind `v2/hold`, and
  `tools/v3/call` 0.011 behind `v1/call` and 0.001 behind `v3/standing`. What each bug fix is worth on its own is
  still unmeasured.

## Holdout

| Agent | vs baseline | p | Deals within own limit | Gates |
|---|---|---|---|---|
| ranged/v4/clock-standing | +0.188 | <0.0001 | 94% vs 81% | +0.05 to +0.07 |
| tools/v1/call | −0.037 | 0.44 | 77% vs 81% (fails) | within 0.10 |

clock-standing gains against every unseen opponent (O1 with the strategy prompt +0.21, the two exploiters +0.18
each, naive +0.30, boulware +0.07), in both roles and with 5 and 10 messages. 11 deals scored a share above 1 (the
opponent past its own limit); they split evenly between it and the reference, so they don't move the difference.
Nobody read the holdout's transcripts.

## Red team after the round

clock-standing +0.074 against the reference (p < 0.0001), the best so far; no deal past its limit.

| Attack, cost | baseline | ranged/v4/clock-standing |
|---|---|---|
| `redteam:llm` | −0.28 | −0.29 |
| quote-accept | +0.02 | −0.19 |
| misquote | +0.03 | +0.09 |
| echo | −0.00 | −0.01 |

Against stonewall it is 0.05 behind the reference (not significant); against anchor 0.13 ahead.

## League

Six agents, every pair 10 games in each role (300 matches, standard-v1's scenario ranges, seed 5).
clock-standing is first (rating 1631, mean share 0.580, deals 92%) and is ahead of every other agent head to head,
with no deal past its limit:

| Opponent | clock-standing | them | deals |
|---|---|---|---|
| single_call/v1/baseline | 0.539 | 0.461 | 20/20 |
| tough-qwen | 0.406 | 0.344 | 15/20 |
| boulware | 0.593 | 0.357 | 19/20 |
| single_call/v1/o2-qwen | 0.634 | 0.266 | 18/20 |
| single_call/v1/o1-qwen | 0.730 | 0.270 | 20/20 |

The rest of the table: tough-qwen 1601, baseline 1588, boulware 1525, o2-qwen 1349, o1-qwen 1307. 20 games per pair
is small: the margins over the baseline (+0.08) and tough-qwen (+0.06) are not significant on their own.

## What it says

- **Promoted:** `ranged/v4/clock-standing` passes dev, the holdout and the red team, and its holdout gain (+0.188) is
  larger than its dev gain (+0.141).
- **tools/v1/call's dev gain doesn't reach unseen opponents.** It stays tools' parent but is no candidate.
- **The builder's model mattered in what it found**, though only one set was measured: Opus at high effort found two
  bugs in the agents' facts and guards that Sonnet didn't, and its variants came with controls. Sonnet's variants
  are not measured, so this is not a measured difference in gain.
- **Still open:** the adaptive LLM attacker costs every agent about 0.28, and quote-accept costs ranged and tools
  about 0.19 while the baseline doesn't fall for it. The builders had the summary and didn't target quote-accept.
- **Halving's first rung is too small to cut on** when members are close: 24 scored pairs separate +0.19 from +0.20
  by chance.
