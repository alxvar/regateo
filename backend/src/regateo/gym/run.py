"""Start or resume a gym run."""
from __future__ import annotations

from regateo.gym.spec import GymSpec
from regateo.runner.runner import Progress, RunSummary, run_jobs
from regateo.storage.store import Store


async def run_gym(spec: GymSpec, store: Store, *, resume: str | None = None,
                  on_progress: Progress | None = None) -> tuple[str, RunSummary]:
    jobs = spec.jobs()
    config = spec.model_dump(mode="json")
    if resume:
        run = await store.get_run(resume)
        if run is None or run.kind != "gym":
            raise ValueError(f"no gym run {resume!r} to resume")
        run_id = resume
    else:
        run_id = await store.create_run("gym", spec.name, config)
    summary = await run_jobs(jobs, store=store, run_id=run_id, settings=spec.settings, on_progress=on_progress)
    await store.finish_run(run_id, "budget_exhausted" if summary.budget_exhausted else "done")
    return run_id, summary
