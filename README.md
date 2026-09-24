# regateo

A negotiation agent for a 1v1 agent-vs-agent price negotiation tournament. Agents take the buyer or seller role, exchange free-text offers, and are ranked by the share of the available surplus they capture. A deal that doesn't close within the round or time budget scores 0.

## Status

We're designing a new system architecture. There is no active code yet: design work happens in Markdown under [`docs/`](docs/).

## Layout

| Path | Contents |
|---|---|
| `docs/` | Design documents for the new architecture. |
| `legacy/idea-1/` | First prototype: deterministic strategy engine with LLM parser/writer ("brain vs. mouth" split) and a local sparring arena. Kept for reference. See its [README](legacy/idea-1/README.md) and [HANDOFF](legacy/idea-1/HANDOFF.md). |

To run the legacy prototype, work from its directory: `cd legacy/idea-1 && python -m arena.run`.
