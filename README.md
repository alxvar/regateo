# regateo

A negotiation agent for a 1v1 agent-vs-agent price negotiation tournament. Agents take the buyer or seller role, exchange free-text offers, and are ranked by the share of the available surplus they capture. A deal that doesn't close within the round or time budget scores 0.

## Status

The evaluation stack is in place. The agents available so far are two LLM baselines (O1, and O2 with a code veto), idea-1's Boulware engine, scripted sparring partners and LLM personas. The docs/03 pipeline stages come next, measured in the gym.

## Quick start

```bash
cd backend && uv sync
uv run regateo gym smoke-offline          # ~2k offline matches in seconds, then a report
uv run regateo arena offline              # offline round robin
uv run regateo serve                      # API + UI on http://localhost:8000 (after building the UI)
cd ../ui && npm install && npm run build  # or `npm run dev` for hot reload on :5173
```

LLM runs use model profiles in `backend/configs/models/`. For local Qwen, start vLLM with `backend/scripts/serve_qwen_vllm.sh`, then try `uv run regateo gym o2-vs-o1-duel`. Runs resume with `--resume <run_id>` and stop at `--budget <usd>`.

## Layout

| Path | Contents |
|---|---|
| `backend/` | Python (uv project `regateo`): agents, model providers, match engine, gym, arena, stats, storage, API. Configs under `backend/configs/`. |
| `ui/` | React + Vite dashboard for conversations and gym/arena stats. See its [README](ui/README.md). |
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
