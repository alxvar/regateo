# single_call: journal

The record of what was tried on this architecture, version by version: the hypothesis, what changed, the run, and what it showed. Every session that changes this architecture reads it first and adds an entry when it's done. Newest last.

## v1

Ported from the engine's O1 and O2 agents (docs/02) when agents became packages. The configs keep their meaning:

| Config | Was |
|---|---|
| `o1-qwen`, `o1-claude` | `o1-qwen`, `o1-claude` |
| `o2-qwen` | `o2-qwen` (O2's original checks) |
| `baseline` | `baseline`: prompt v2, `checks: limit+mentions`, `accept_words: reader` |
| `reciprocity`, `moves`, `reciprocity-moves` | experiment 001's `b1/*` |

What the experiments before the packages showed is in the learnings you are given.

v1 depends only on `agent_sdk`: prices in text come from `agent_sdk.prices`, and the rules it reads the other side's messages with (the state digest, `accept_words: reader`) are its own copy of the referee's first rule reader, in `lib/reading.py`. On every stored match (6,010 histories, 65,096 messages) the copy reads every message exactly as the referee's rules-v1 did, and every model request of the configs above is byte-for-byte what it was before the packages.

**2026-10-01, measured again as a package.** Dev run_01a0f788e0c49683e4d1: `baseline` 0.343 against `o1-qwen` 0.227, Δ +0.115 (p < 0.0001), no deals past the limit. Same result as before the packages within noise.

## v2 (round 01 session)

v2 is v1's code with one new param, `attempts` (default 2, so v1 behaviour), a new prompt `negotiator_system.v4`, and the `dict.fromkeys` dedupe of repeated veto feedback. Both variants extend `single_call/v1/baseline` and live in `v2/configs/`. Not run: no model access in this session, so nothing below is measured. `regateo-agent` and `pytest` have a broken shebang here (missing interpreter), so I ran `python -m pytest agents/single_call` (16 passed) and `python -m agent_sdk.cli check agents/single_call/v2` (ok).

**Failure targeted, from `data/matches.jsonl` (125 baseline matches).** Of our 651 messages, 252 (39%) were vetoed on the first draft and 138 (21%) fell through to the deterministic repair, which sends "I can do $X." with no reasoning and freezes the price at the previous offer. The commonest veto is "the message mentions $68, past your walk-away price": the model rejects a lowball by quoting it. Examples: 0-3-b (hardliner), 0-4-b (liar), 20-0-s (tough). Shares: buyer 0.313 vs seller 0.415; hidden-deadline cell 0.310 vs known 0.415, with deal rate 57% vs 82%. Terse repaired messages give the opponent nothing to respond to, and no-deal scores 0.

**no-quote** (prompt v4): adds a rule to never repeat their figure or any other price in the message, only our own offer.
- Hypothesis: vetoes and repairs per match drop clearly (first-draft veto rate well under 39%), and share and deal rate rise because our messages keep their reasoning.
- Wrong if: the veto rate does not fall, or share is not above the baseline's lower bound on the LLM opponents, or a deal past our limit appears.

**retry3** (`attempts: 3`): a third draft with feedback before the repair.
- Hypothesis: of the turns that reach repair today, a meaningful share would pass on a third draft, so the repair rate falls and share rises slightly.
- Wrong if: the repair rate stays about the same (the model repeats the same mistake), or share is unchanged within noise. A change in share larger than the repair-rate change would point to noise.

Both keep every veto, so the walk-away guarantees are unchanged.

**Round round-01** (run_01a0f9180ca60d701354), Δshare against the reference `single_call-v1-baseline` on standard-v2:

- `single_call/v1/baseline` (the reference): 0
- `single_call/v2/no-quote`: +0.032 [-0.023, +0.087]  p=0.2516 (not significant, n=240); A ahead in 43% of pairs, B in 36% **(next parent)**
- `single_call/v2/retry3`: -0.008 [-0.074, +0.064]  p=1.0000 (not significant, n=24); A ahead in 4% of pairs, B in 8%, cut after 48 pairs
