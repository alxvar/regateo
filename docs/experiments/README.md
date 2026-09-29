# Experiments

One file per question: `NNN-<question>.md`. Null results count: they stop us from testing the same idea twice.

**Current reference:** `o1-qwen` on bench `standard-v1`.

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
4. **Write up** the hypothesis, run id and result here. When a challenger wins on the full bench, it becomes the reference.
   Freeze its prompt and config with `regateo freeze <files>`.
   The full promotion rule (holdout, guardrails, league) is in [04-hill-climbing.md](../04-hill-climbing.md).

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
  Tier `screen` (the first 4 scenarios per cell, 96 pairs, share CI about ±0.07) drops clear losers. The full bench
  (240 pairs, about ±0.04) is for decisions.

## Log

| # | Question | Status | Result |
|---|---|---|---|
| [001](001-o1-levers.md) | Which no-new-components levers make O1 stronger? | screened; full bench next | Strategy prompt v2 +0.067 (p=0.10); reasoning, thinking and the digest each hurt (-0.09 to -0.15): more deals, less value; presence penalty no effect |
