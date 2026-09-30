"""Start or resume a gym run."""
from __future__ import annotations

from regateo.core.roles import Role
from regateo.gym.early import EarlyStopper
from regateo.gym.spec import GymSpec
from regateo.runner.runner import Progress, RunSummary, run_jobs
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
    summary = await run_jobs(jobs, store=store, run_id=run_id, settings=spec.settings, on_progress=on_progress,
                             skip=stopper.skip if stopper else None, on_result=stopper.record if stopper else None)
    if stopper and stopper.stopped:
        await store.update_run_config(run_id, {"stopped": stopper.stopped})
    await store.finish_run(run_id, "budget_exhausted" if summary.budget_exhausted else "done")
    return run_id, summary
