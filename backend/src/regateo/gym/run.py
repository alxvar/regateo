"""Start or resume a gym run."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import fmean

from regateo.core.roles import Role
from regateo.gym.early import EarlyStopper, Halving
from regateo.gym.spec import GymSpec
from regateo.runner.runner import MatchJob, Progress, RunSummary, run_jobs
from regateo.storage.store import Store


async def run_gym(spec: GymSpec, store: Store, *, resume: str | None = None,
                  on_progress: Progress | None = None) -> tuple[str, RunSummary]:
    jobs = spec.jobs()
    config = spec.model_dump(mode="json")
    stopper = None
    if resume:
        run = await store.get_run(resume)
        if run is None or run.kind != "gym":
            raise ValueError(f"no gym run {resume!r} to resume")
        run_id = resume
    else:
        run_id = await store.create_run("gym", spec.name, config)
    if spec.early_stop and spec.mode == "benchmark":
        stopper = EarlyStopper(spec.early_stop, [s for s in spec.subjects() if s != "b"])
        for row in await store.list_matches(run_id):          # on resume: what was already played counts
            if row.status == "done" and row.outcome:
                stopper.add(row.meta["pair"], row.meta["subject"], row.outcome.share(Role(row.meta["role"])))
    skip, on_result = (stopper.skip, stopper.record) if stopper else (None, None)
    if spec.halving and spec.mode == "benchmark":
        summary = await _halving(spec.halving, jobs, store, run_id, spec, skip, on_result, on_progress, stopper)
    else:
        summary = await run_jobs(jobs, store=store, run_id=run_id, settings=spec.settings, on_progress=on_progress,
                                 skip=skip, on_result=on_result)
    if stopper and stopper.stopped:
        await store.update_run_config(run_id, {"stopped": stopper.stopped})
    await store.finish_run(run_id, "budget_exhausted" if summary.budget_exhausted else "done")
    return run_id, summary


async def _halving(cfg: Halving, jobs: list[MatchJob], store: Store, run_id: str, spec: GymSpec, skip, on_result,
                   on_progress: Progress | None, stopper: EarlyStopper | None) -> RunSummary:
    """Plays the bench in rungs of pairs (in job order, which interleaves cells), cutting the challengers
    after each rung. `halved` in the run config maps a cut challenger to the pairs it had played."""
    pairs = list(dict.fromkeys(j.meta["pair"] for j in jobs))
    index = {p: i for i, p in enumerate(pairs)}
    run = await store.get_run(run_id)
    halved: dict[str, int] = dict((run.config.get("halved") if run else None) or {})
    alive = [s for s in spec.subjects() if s != "b" and s not in halved]
    end = min(cfg.first, len(pairs))
    while True:
        limit = {s: halved.get(s, end) for s in spec.subjects()}
        limit["b"] = end
        summary = await run_jobs([j for j in jobs if index[j.meta["pair"]] < limit[j.meta["subject"]]],
                                 store=store, run_id=run_id, settings=spec.settings, on_progress=on_progress,
                                 skip=skip, on_result=on_result)
        if end >= len(pairs) or summary.budget_exhausted:
            return summary
        alive = [s for s in alive if not (stopper and s in stopper.stopped)]
        if len(alive) > cfg.finalists:
            gains = await _gains(store, run_id, {p for p in pairs if index[p] < end})
            keep = max(cfg.finalists, math.ceil(len(alive) * cfg.keep))
            ranked = sorted(alive, key=lambda s: -gains.get(s, -math.inf))
            for s in ranked[keep:]:
                halved[s] = end
            alive = ranked[:keep]
            await store.update_run_config(run_id, {"halved": halved})
            end = min(2 * end, len(pairs))
        else:
            end = len(pairs)


async def _gains(store: Store, run_id: str, pairs: set[str]) -> dict[str, float]:
    """Mean challenger - reference share per challenger, over the given pairs that both finished."""
    shares: dict[str, dict[str, float]] = defaultdict(dict)
    for r in await store.list_matches(run_id):
        if r.status == "done" and r.outcome and r.meta["pair"] in pairs:
            shares[r.meta["pair"]][r.meta["subject"]] = r.outcome.share(Role(r.meta["role"]))
    diffs: dict[str, list[float]] = defaultdict(list)
    for got in shares.values():
        if "b" in got:
            for s, v in got.items():
                if s != "b":
                    diffs[s].append(v - got["b"])
    return {s: fmean(d) for s, d in diffs.items()}
