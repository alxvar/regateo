"""regateo command line: run matches, gyms and arenas; print reports; serve the API."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from regateo.agents import AgentSpec
from regateo.arena import ArenaSpec, build_arena_report, run_arena
from regateo.cli import format as fmt
from regateo.core.config import configs_dir, data_dir, load_env, load_yaml
from regateo.core.scenario import ScenarioSpec, sample_scenarios
from regateo.gym import GymSpec, build_gym_report, run_gym
from regateo.llm.cache import CachedClient, CacheMode
from regateo.llm.profiles import load_profile
from regateo.llm.registry import get_client
from regateo.referee.audit import MatchMessages, audit_readings
from regateo.referee.audit import reread as reread_transcript
from regateo.referee.registry import build_reader
from regateo.runner import MatchJob, RunSettings, RunSummary, match_id, run_jobs
from regateo.storage import Store

app = typer.Typer(no_args_is_help=True, add_completion=False)

DbOpt = Annotated[Path | None, typer.Option("--db", help="SQLite file (default: data/regateo.db or $REGATEO_DB)")]


def _db(db: Path | None) -> Path:
    return db or Path(os.environ.get("REGATEO_DB", data_dir() / "regateo.db"))


def _config(value: str, kind: str) -> Path:
    path = Path(value)
    if path.suffix in (".yaml", ".yml"):
        return path
    return configs_dir() / kind / f"{value}.yaml"


def _progress(summary: RunSummary) -> None:
    finished = summary.done + summary.failed + summary.skipped
    sys.stderr.write(f"\r  {finished}/{summary.total} matches  failed {summary.failed}  ${summary.cost_usd:.4f}   ")
    sys.stderr.flush()


@app.callback()
def main(verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False) -> None:
    load_env()
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")


@app.command()
def match(
    seller: Annotated[str, typer.Option(help="agent config name or kind, e.g. o2-qwen, scripted:liar")],
    buyer: Annotated[str, typer.Option(help="agent config name or kind")],
    model: Annotated[str | None, typer.Option(help="model profile for LLM agents that don't name one")] = None,
    scenario_seed: Annotated[int, typer.Option(help="which sampled scenario to play")] = 0,
    max_rounds: int = 6,
    deadline_known: bool = True,
    protocol: str = "structured",
    detector: str = "structured",
    reader: Annotated[str, typer.Option(help="rules, llm:<profile>, or shadow:rules+llm:<profile>")] = "rules",
    sim_clock: Annotated[bool, typer.Option(help="simulated latency (code-only agents)")] = False,
    db: DbOpt = None,
) -> None:
    """Play one match and print the transcript."""
    def spec(value: str) -> AgentSpec:
        s = AgentSpec.resolve(value)
        return s.model_copy(update={"model": model}) if model and not s.model else s

    scenario = sample_scenarios(ScenarioSpec(per_cell=1, max_rounds=[max_rounds], deadline_known=[deadline_known]),
                                scenario_seed)[0]
    job = MatchJob(key="0", scenario=scenario, seller=spec(seller), buyer=spec(buyer), protocol=protocol,
                   detector=detector, reader=reader, seed=scenario_seed, sim_clock=sim_clock)

    async def go() -> None:
        store = await Store.open(_db(db))
        run_id = await store.create_run("match", f"{job.seller.label} vs {job.buyer.label}", {
            "scenario_seed": scenario_seed, "protocol": protocol, "detector": detector, "reader": reader})
        summary = await run_jobs([job], store=store, run_id=run_id, settings=RunSettings(concurrency=1))
        await store.finish_run(run_id, "done" if summary.done else "failed")
        mid = match_id(run_id, job)
        row = await store.get_match(mid)
        typer.echo(f"{scenario.item}: seller walk-away {scenario.seller_reservation:g}, "
                   f"buyer walk-away {scenario.buyer_reservation:g}  (match {mid})\n")
        typer.echo(fmt.transcript(await store.match_messages(mid), row.outcome if row else None))
        await store.close()

    asyncio.run(go())


@app.command()
def gym(
    config: Annotated[str, typer.Argument(help="configs/gym/<name>.yaml, or a path")],
    resume: Annotated[str | None, typer.Option(help="run id to resume")] = None,
    concurrency: int | None = None,
    budget: Annotated[float | None, typer.Option(help="USD cap for this run")] = None,
    db: DbOpt = None,
) -> None:
    """Run (or resume) a head-to-head gym experiment and print its report."""
    spec = load_yaml(_config(config, "gym"), GymSpec)
    spec.settings = _override(spec.settings, concurrency, budget)

    async def go() -> None:
        store = await Store.open(_db(db))
        run_id, summary = await run_gym(spec, store, resume=resume, on_progress=_progress)
        sys.stderr.write("\n")
        if summary.budget_exhausted:
            typer.echo(f"Budget exhausted: resume with --resume {run_id} --budget <more>")
        typer.echo(fmt.gym_report(await build_gym_report(store, run_id)))
        await store.close()

    asyncio.run(go())


@app.command()
def arena(
    config: Annotated[str, typer.Argument(help="configs/arena/<name>.yaml, or a path")],
    resume: Annotated[str | None, typer.Option(help="run id to resume")] = None,
    concurrency: int | None = None,
    budget: Annotated[float | None, typer.Option(help="USD cap for this run")] = None,
    db: DbOpt = None,
) -> None:
    """Run (or resume) a round-robin tournament and print the leaderboard."""
    spec = load_yaml(_config(config, "arena"), ArenaSpec)
    spec.settings = _override(spec.settings, concurrency, budget)

    async def go() -> None:
        store = await Store.open(_db(db))
        run_id, summary = await run_arena(spec, store, resume=resume, on_progress=_progress)
        sys.stderr.write("\n")
        if summary.budget_exhausted:
            typer.echo(f"Budget exhausted: resume with --resume {run_id} --budget <more>")
        typer.echo(fmt.arena_report(await build_arena_report(store, run_id)))
        await store.close()

    asyncio.run(go())


@app.command()
def report(run_id: str, db: DbOpt = None) -> None:
    """Print the report of a gym or arena run."""
    async def go() -> None:
        store = await Store.open(_db(db), readonly=True)
        run = await store.get_run(run_id)
        if run is None:
            raise typer.BadParameter(f"no run {run_id}")
        if run.kind == "gym":
            typer.echo(fmt.gym_report(await build_gym_report(store, run_id)))
        elif run.kind == "arena":
            typer.echo(fmt.arena_report(await build_arena_report(store, run_id)))
        else:
            for row in await store.list_matches(run_id):
                typer.echo(fmt.transcript(await store.match_messages(row.id), row.outcome))
        await store.close()

    asyncio.run(go())


@app.command()
def readings(
    run_id: str,
    examples: Annotated[int, typer.Option(help="mismatches to print")] = 20,
    reread: Annotated[str | None, typer.Option(
        help="re-read the transcripts with this reader first, e.g. shadow:rules+llm:qwen-local")] = None,
    concurrency: int = 16,
    db: DbOpt = None,
) -> None:
    """How well the referee read a run's messages, checked against what each agent meant."""
    async def go() -> None:
        store = await Store.open(_db(db), readonly=True)
        if await store.get_run(run_id) is None:
            raise typer.BadParameter(f"no run {run_id}")
        matches = [MatchMessages(match_id=row.id, seller=row.seller.name, buyer=row.buyer.name,
                                 messages=await store.match_messages(row.id))
                   for row in await store.list_matches(run_id)]
        await store.close()
        if reread:
            reader = build_reader(reread, lambda profile: CachedClient(
                get_client(load_profile(profile)), data_dir() / "llm_cache.db", CacheMode.READWRITE))
            gate = asyncio.Semaphore(concurrency)

            async def one(mm: MatchMessages) -> MatchMessages:
                async with gate:
                    return mm.model_copy(update={"messages": await reread_transcript(mm.messages, reader)})
            matches = list(await asyncio.gather(*(one(mm) for mm in matches)))
        typer.echo(fmt.reading_audit(audit_readings(run_id, matches, max_examples=examples)))

    asyncio.run(go())


@app.command()
def runs(kind: str | None = None, limit: int = 20, db: DbOpt = None) -> None:
    """List recent runs."""
    async def go() -> None:
        store = await Store.open(_db(db), readonly=True)
        for r in await store.list_runs(kind, limit):
            p = await store.run_progress(r.id)
            typer.echo(f"{r.id}  {r.kind:6} {r.status:17} {p['done']:>5}/{p['total'] or '?':<5} "
                       f"${p['cost_usd']:<9.4f} {r.name}")
        await store.close()

    asyncio.run(go())


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, db: DbOpt = None) -> None:
    """Serve the read-only API (and the built UI, if ui/dist exists)."""
    import uvicorn

    from regateo.api import create_app

    uvicorn.run(create_app(_db(db)), host=host, port=port)


def _override(settings: RunSettings, concurrency: int | None, budget: float | None) -> RunSettings:
    update = {k: v for k, v in {"concurrency": concurrency, "budget_usd": budget}.items() if v is not None}
    return settings.model_copy(update=update)


if __name__ == "__main__":
    app()
