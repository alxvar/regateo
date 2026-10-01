# regateo

A negotiation agent for a 1v1 agent-vs-agent price negotiation tournament. Agents take the buyer or seller role, exchange free-text offers, and are ranked by the share of the available surplus they capture. A deal that doesn't close within the round or time budget scores 0.

## Status

The evaluation stack is in place. Our agents so far are one architecture, `single_call` (O1, and O2 with code vetoes, including the baseline). The engine's opponents are idea-1's Boulware engine, scripted sparring partners and LLM personas. The docs/03 pipeline stages come next, measured in the gym.

## Quick start

```bash
uv sync --all-packages                    # from the repo root: the engine and the agent SDK
uv run pytest                             # the SDK, the engine and every agent version
cd engine
uv run regateo gym smoke-offline          # ~2k offline matches in seconds, then a report
uv run regateo arena offline              # offline round robin
uv run regateo serve                      # API + UI on http://localhost:8000 (after building the UI)
cd ../ui && npm install && npm run build  # or `npm run dev` for hot reload on :5173
```

LLM runs use model profiles in `engine/configs/models/`. For local Qwen (Qwen3.8-27B NVFP4 on the RTX 5090), install vLLM once in its own venv (`uv venv ~/venvs/vllm --python 3.12 && VIRTUAL_ENV=~/venvs/vllm uv pip install vllm --torch-backend=auto`), start it with `engine/scripts/serve_qwen_vllm.sh` (port 8001; the dashboard keeps 8000), then try `uv run regateo gym baseline`. Runs resume with `--resume <run_id>` and stop at `--budget <usd>`.

## Layout

| Path | Contents |
|---|---|
| `engine/` | Python (uv project `regateo`): match engine, opponents, model providers, referee, gym, arena, climb, stats, storage, CLI, API. Configs under `engine/configs/`. |
| `agents/` | Our negotiating agents, one package per architecture and version (`agents/<architecture>/v<N>/`), with their prompts, configs, tests and a journal per architecture. See [06](docs/06-agent-contract.md#2-packaging). |
| `agent-sdk/` | Python (uv project `regateo-agent-sdk`, package `agent_sdk`): what agents are written against, and all an agent may import from the engine's world. See [06](docs/06-agent-contract.md). |
| `ui/` | React + Vite dashboard for conversations and gym/arena stats. See its [README](ui/README.md). |
| `data/` | Gitignored run output: SQLite DB, transcripts, LLM cache. |
| `docs/` | Design documents for the new architecture. |
| `legacy/idea-1/` | First prototype: deterministic strategy engine with LLM parser/writer ("brain vs. mouth" split) and a local sparring arena. Kept for reference. See its [README](legacy/idea-1/README.md) and [HANDOFF](legacy/idea-1/HANDOFF.md). |

## Glossary

- **match:** one negotiation between two agents on one scenario.
- **gym:** head-to-head experiments. Agent A plays agent B over hundreds of paired matches (same scenarios and seeds, roles swapped) to tell whether one is significantly better.
- **arena:** a tournament across a roster of agents, producing a leaderboard and ratings.
- **reading:** the referee's interpretation of one message (offer, accept, reject or none, and the price), made once when the message arrives. Rules decide the clear cases; `reader: llm:<profile>` asks a model for the ambiguous ones, choosing only among amounts the message names. `shadow:rules+llm:<profile>` records the model's view without letting it decide. `regateo readings RUN_ID [--reread <reader>]` scores readings against what each agent meant to say.

Model access goes through `regateo.llm`: the Claude API for real runs, or a local model served with vLLM behind an OpenAI-compatible endpoint (see `engine/.env.example`).

## Legacy

To run the legacy prototype, work from its directory: `cd legacy/idea-1 && python -m arena.run`.
