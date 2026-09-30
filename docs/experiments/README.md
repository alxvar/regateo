# Experiments

One file per question: `NNN-<question>.md`. Null results count: they stop us from testing the same idea twice.

**Current reference:** `baseline` on bench `standard-v1`, set up 2026-09-30 from the experiments before it
([05-learnings.md](../05-learnings.md)).

## How to run a variant

1. **Change something without editing frozen files.** Everything with benchmark results is listed in
   `backend/configs/frozen.json`, and a unit test fails if it changes. Add the next version instead:
   `negotiator_system.v3.md`, `qwen-local-<variant>.yaml`, `standard-v2.yaml`.
2. **Describe the variant as a small agent config** that extends its parent, in `backend/configs/agents/<family>/`:
   ```yaml
   extends: baseline
   params: {prompt: negotiator_system.v3}
   ```
   New behaviour in code gets a param whose default keeps the old behaviour, so older configs still mean what they did.
3. **Point a gym config at a bench**, with the reference and any number of challengers:
   ```yaml
   name: exp-001-...
   bench: standard-v1
   reference: baseline
   challengers: [o2/firmer-close, o2/think-first]
   halving: true           # cut the worse half at 48, 96... pairs until two are left
   early_stop: true        # stop challengers that are clearly behind
   settings: {concurrency: 32, cache: readwrite}
   ```
   `regateo gym exp-001-...`. Commit first: the run records the commit, and warns when there are uncommitted changes.
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
regateo propose <dev run> --parent <agent>               # one Qwen call: challenger configs + gym + stub doc
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
- **Coupling.** Within a pair, the challenger and the reference share random draws: an identical model request
  gets the same answer, and each call is seeded from the pair. Their matches stay identical until their behaviour
  first differs, so the difference measures the change, not sampling luck.
- **Benches.** A bench fixes opponents, scenarios, rules, the reader and the seed. Numbers from different benches are
  not compared. The full bench (240 pairs) is for decisions; successive halving spends fewer pairs on clear losers.
  How precisely a difference is known depends on how often the change fires: about ±0.01 for a rare veto, up to about
  ±0.05 for a change that rewrites every match ([04 §6](../04-hill-climbing.md)).

## Log

| # | Question | Status | Result |
|---|---|---|---|
| [000](000-baseline.md) | How good is the baseline? | done | Dev: +0.117 over plain O1 (p<0.0001), 0 deals past the limit. Holdout: +0.033 (ns) and 9 points fewer deals; behind the thinking exploiter, weaker with 5 rounds. League: 3rd of 5, behind boulware and tough-qwen |
| [001](001-reciprocity.md) | Does the baseline concede more than its opponent, and does making reciprocity concrete help? | null | Finalists +0.044 (p=0.09, reciprocity prompt + moves digest) and +0.033 (moves digest), gains only against scripted opponents. The model still outpaces the other side in over half its concessions |
