# Experiments

One file per question: `NNN-<question>.md`. Null results count: they stop us from testing the same idea twice.

**Current reference:** `o2/v2-limit-quiet` on bench `standard-v1`, promoted 2026-09-30 from [002](002-limit-veto.md)
(`o1-qwen` before).

## How to run a variant

1. **Change something without editing frozen files.** Everything with benchmark results is listed in
   `backend/configs/frozen.json`, and a unit test fails if it changes. Add the next version instead:
   `negotiator_system.v3.md`, `qwen-local-<variant>.yaml`, `standard-v2.yaml`.
2. **Describe the variant as a small agent config** that extends its parent, in `backend/configs/agents/<family>/`:
   ```yaml
   extends: o1/informed
   params: {prompt: negotiator_system.v3}
   ```
   New behaviour in code gets a param whose default keeps the old behaviour, so older configs still mean what they did.
3. **Point a gym config at a bench**, with the reference and any number of challengers:
   ```yaml
   name: exp-002-...
   bench: standard-v1
   tier: screen            # remove for the full bench
   reference: o1-qwen
   challengers: [o1/informed-v3, o1/informed-v2]
   settings: {concurrency: 32, cache: readwrite}
   ```
   `regateo gym exp-002-...`. Commit first: the run records the commit, and warns when there are uncommitted changes.
   Add `early_stop: true` to stop challengers that are clearly behind before they finish (only losers are stopped),
   and `halving: true` to cut the worse half of the challengers at 48, 96... pairs until two are left.
4. **Write up** the hypothesis, run id and result here. A challenger that wins on the full bench is a *candidate*;
   it becomes the reference only after the promotion checklist below.

## Promotion checklist

The rule and its reasons are in [04-hill-climbing.md §3.1](../04-hill-climbing.md). For the best candidate:

1. **Dev, full tier.** In the gym report's "Promotion checks", the candidate reads `candidate`: gain significant,
   no deals past its own limit, deals within its own limit no more than 2 points below the reference's. Read any
   `warn` rows' transcripts.
2. **Holdout.** Run it on `holdout-v1` against the reference (a gym config with `bench: holdout-v1`). Its gain must
   point the same way. Don't read holdout transcripts for ideas.
3. **Readings.** `regateo readings <dev run>`: no new kind of misread offer or acceptance behind its gains.
4. **Promote.** `regateo freeze` its prompt and config, update "Current reference" above, add it to the roster in
   `backend/configs/arena/league.yaml`, and run `regateo arena league`. If it loses head to head to an older champion,
   find out why before the next round.

## The climb loop

Steps 1–4 of a round can run unattended on local Qwen ([04 §5.2](../04-hill-climbing.md)):

```
regateo mine <dev run>                                   # the failure bundle the proposer sees (reference by default)
regateo propose <dev run> --parent <agent>               # one Qwen call: challenger configs + screen gym + stub doc
regateo climb <dev run> --parent <agent> --rounds 5      # propose, then successive halving on the full bench, repeat
```

The proposer sees only the bundle and the log below: our agent's prompts and settings, dev transcripts, and results.
Holdout runs are refused. Every proposal is validated in code (placeholders kept, a real change, a free name) before
it is written. Proposed experiments are marked "Not yet reviewed by a person" until someone reads them. Results of
each round are also logged to `data/climb/log.jsonl`, which the next round's proposer reads to avoid repeats.

## Why the numbers can be trusted

- **Identity.** An agent's key covers its settings, the text of every prompt it renders, and its model profile's settings.
  Editing any of them makes a different agent, never mixed into the old one's results.
- **Pairing.** Every challenger plays the same opponents, scenarios, roles and seeds as the reference. Results are
  compared pair by pair, which removes most scenario-to-scenario noise.
- **Replay.** The LLM cache is keyed by what a match *is* (scenario, seed, rules, agent behaviour), not by run.
  So the reference and any unchanged challenger replay from the cache in later runs at no GPU cost, and a screen's
  matches replay when the full bench runs. The cache key also covers the model profile's settings, so turning
  thinking on is a miss, not a stale replay.
- **Benches.** A bench fixes opponents, scenarios, rules and seed. Numbers from different benches are not compared.
  Tier `screen` (the first 4 scenarios per cell, 96 pairs) drops clear losers. The full bench (240 pairs) is for
  decisions. One agent's share is known to about ±0.07 and ±0.04; the *difference* between two agents, which is what
  we decide on, to about ±0.08 and ±0.05 ([04 §6](../04-hill-climbing.md)).

## Log

| # | Question | Status | Result |
|---|---|---|---|
| [001](001-o1-levers.md) | Which no-new-components levers make O1 stronger? | done | Strategy prompt v2: +0.105 share on the full bench (p=0.0001). Reasoning, thinking and the digest each hurt: more deals, less value. Presence penalty no effect |
| [002](002-limit-veto.md) | Can a code veto stop deals past our own limit without costing value? | done | `checks: limit+mentions` on o1-v2 (o2/v2-limit-quiet): +0.153 share (p<0.0001), 0 deals past the limit on dev; holdout +0.131 (p=0.002). `limit` alone: +0.079, still 8 past-limit deals (quoted prices read as offers). O2's original checks: 58% deal rate. Promotion pending: deal-rate rule question, 2 holdout misreads |
| [003](003-climb.md) | First unattended climb round from o2/v2-limit-quiet | done | Three proposals (accept near the limit, never repeat an offer, fence); none beat the candidate: best -0.027 on the full bench |
