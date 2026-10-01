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

What the experiments before the packages showed is in docs/05-learnings.md and docs/experiments/000 and 001.

v1 depends only on `agent_sdk`: prices in text come from `agent_sdk.prices`, and the rules it reads the other side's messages with (the state digest, `accept_words: reader`) are its own copy of the referee's first rule reader, in `lib/reading.py`. On every stored match (6,010 histories, 65,096 messages) the copy reads every message exactly as the referee's rules-v1 did, and every model request of the configs above is byte-for-byte what it was before the packages.
