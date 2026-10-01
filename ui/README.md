# ui

React + Vite + TypeScript dashboard over the engine's read-only API (`engine/src/regateo/api`).

- **Runs:** totals and every gym, arena and match run, with live progress.
- **Gym run:** the A − B verdict with its 95% CI and p-value, per-side stats, and a forest plot of where the difference comes from (by opponent, role or scenario cell).
- **Arena run:** a Bradley-Terry leaderboard and the pairwise results heatmap.
- **Match:** the price path against both walk-away prices, the conversation with agent internals, and model calls. It updates live while the match runs.

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api to `regateo serve` on :8000
npm run build        # dist/ is then served by `regateo serve` itself on :8000
```
