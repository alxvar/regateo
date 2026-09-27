# regateo

A negotiation agent for a 1v1 agent-vs-agent price negotiation tournament. Agents take the buyer or seller role, exchange free-text offers, and are ranked by the share of the available surplus they capture. A deal that doesn't close within the round or time budget scores 0.

## Status

We're designing a new system architecture in [`docs/`](docs/). The bottom layers of the backend are implemented: `core`, `llm`, `protocol`, `referee` and `storage`. Agents, the match engine, the gym, the arena, the API and the UI are next.

```bash
cd backend && uv sync && uv run pytest        # unit tests; live model tests: uv run pytest -m live
```

## Layout

| Path | Contents |
|---|---|
| `backend/` | Python (uv project `regateo`): agents, model providers, match engine, gym, arena, stats, storage, API. Configs under `backend/configs/`. |
| `ui/` | React + Vite dashboard for conversations and gym/arena stats (not scaffolded yet). |
| `data/` | Gitignored run output: SQLite DB, transcripts, LLM cache. |
| `docs/` | Design documents for the new architecture. |
| `legacy/idea-1/` | First prototype: deterministic strategy engine with LLM parser/writer ("brain vs. mouth" split) and a local sparring arena. Kept for reference. See its [README](legacy/idea-1/README.md) and [HANDOFF](legacy/idea-1/HANDOFF.md). |

## Glossary

- **match:** one negotiation between two agents on one scenario.
- **gym:** head-to-head experiments. Agent A plays agent B over hundreds of paired matches (same scenarios and seeds, roles swapped) to tell whether one is significantly better.
- **arena:** a tournament across a roster of agents, producing a leaderboard and ratings.

Model access goes through `regateo.llm`: the Claude API for real runs, or a local model served with vLLM behind an OpenAI-compatible endpoint (see `backend/.env.example`).

## Legacy

To run the legacy prototype, work from its directory: `cd legacy/idea-1 && python -m arena.run`.
