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
from regateo.core import frozen
from regateo.core.config import configs_dir, data_dir, load_env, load_yaml
from regateo.core.scenario import ScenarioSpec, sample_scenarios
from regateo.core.version import code_version
from regateo.gym import GymSpec, build_gym_report, run_gym
from regateo.gym.signals import run_signals, sides
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


def _warn_dirty() -> None:
    code = code_version()
    if code.get("dirty"):
        sys.stderr.write(f"warning: uncommitted changes (recorded as {code['commit'][:8]}+{code['changes']}). "
                         "Commit before a run you plan to quote.\n")


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
    seller: Annotated[str, typer.Option(help="agent config name or kind, e.g. single_call/v1/baseline, scripted:liar")],
    buyer: Annotated[str, typer.Option(help="agent config name or kind")],
    model: Annotated[str | None, typer.Option(help="model profile for LLM agents that don't name one")] = None,
    scenario_seed: Annotated[int, typer.Option(help="which sampled scenario to play")] = 0,
    max_rounds: int = 5,
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
    _warn_dirty()

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
    _warn_dirty()

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
                get_client(load_profile(profile)), data_dir() / "llm_cache.db", CacheMode.READWRITE,
                profile_key=load_profile(profile).fingerprint()))
            gate = asyncio.Semaphore(concurrency)

            async def one(mm: MatchMessages) -> MatchMessages:
                async with gate:
                    return mm.model_copy(update={"messages": await reread_transcript(mm.messages, reader)})
            matches = list(await asyncio.gather(*(one(mm) for mm in matches)))
        typer.echo(fmt.reading_audit(audit_readings(run_id, matches, max_examples=examples)))

    asyncio.run(go())


@app.command()
def signals(
    run_id: str,
    by_opponent: Annotated[bool, typer.Option("--by-opponent", help="one row per opponent under each agent")] = False,
    agent: Annotated[str | None, typer.Option(help="only agents whose label contains this")] = None,
    db: DbOpt = None,
) -> None:
    """Exploit signals: patterns in each agent's play an opponent could use (regateo.gym.signals)."""
    async def go() -> list:
        store = await Store.open(_db(db), readonly=True)
        try:
            if await store.get_run(run_id) is None:
                raise typer.BadParameter(f"no run {run_id}")
            plays = []
            for row in await store.list_matches(run_id):
                if row.status == "done":
                    plays += sides(row, await store.match_messages(row.id))
            return plays
        finally:
            await store.close()

    plays = [p for p in asyncio.run(go()) if agent is None or agent in p.agent]
    typer.echo(fmt.signals(run_id, run_signals(plays, by_opponent=by_opponent)))


@app.command()
def thinking(
    run_id: str,
    agent: Annotated[str | None, typer.Option(help="only this agent's calls (its label, or 'referee')")] = None,
    stage: Annotated[str | None, typer.Option(help="only this stage, e.g. strategist")] = None,
    out: Annotated[Path | None, typer.Option(help="JSONL file (default: data/thinking/<run_id>.jsonl)")] = None,
    db: DbOpt = None,
) -> None:
    """Export a run's stored thinking traces as JSONL, one call per line, and summarise them by agent and stage.
    Traces include the referee's and opponents' thinking: engine tier, for people (docs/06 §5)."""
    import json
    from collections import defaultdict

    async def go() -> list[dict]:
        store = await Store.open(_db(db))
        try:
            if await store.get_run(run_id) is None:
                raise typer.BadParameter(f"no run {run_id}")
            return await store.run_reasoning(run_id)
        finally:
            await store.close()

    rows = [r for r in asyncio.run(go())
            if (agent is None or r["tags"].get("agent", r["tags"].get("stage")) == agent)
            and (stage is None or r["tags"].get("stage") == stage)]
    path = out or data_dir() / "thinking" / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["tags"].get("agent", "-"), r["tags"].get("stage", "-"))].append(r)
    typer.echo(f"{len(rows)} traces -> {path}")
    for (a, s), rs in sorted(groups.items()):
        chars = sum(len(r["reasoning"]) for r in rs) / len(rs)
        errors = sum(bool(r["error"]) for r in rs)
        typer.echo(f"  {a:32} {s:12} {len(rs):5} traces  {chars:8,.0f} chars avg  {errors} failed")


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


@app.command(name="delete-run")
def delete_run(
    run_ids: Annotated[list[str], typer.Argument(help="runs to remove, e.g. ones stopped and never resumed")],
    force: Annotated[bool, typer.Option(help="also remove runs that finished")] = False,
    db: DbOpt = None,
) -> None:
    """Remove runs with their matches, messages, model calls and thinking traces. Refuses finished runs
    unless --force: their results may be quoted somewhere. The response cache is kept."""
    async def go() -> None:
        store = await Store.open(_db(db))
        try:
            for run_id in run_ids:
                run = await store.get_run(run_id)
                if run is None:
                    typer.echo(f"{run_id}: no such run")
                elif run.status == "done" and not force:
                    typer.echo(f"{run_id} ({run.name}): finished; kept (use --force)")
                else:
                    n = await store.delete_run(run_id)
                    typer.echo(f"{run_id} ({run.name}, {run.status}): removed with {n} matches")
        finally:
            await store.close()

    asyncio.run(go())


@app.command()
def mine(
    run_id: str,
    subject: Annotated[str, typer.Option(help="a, b (the reference) or a2... of a benchmark gym")] = "b",
    worst: Annotated[int, typer.Option(help="transcripts to include")] = 5,
    out: Annotated[Path | None, typer.Option(help="write the bundle here instead of printing it")] = None,
    db: DbOpt = None,
) -> None:
    """Failure bundle of a dev gym run: where an agent loses value, and its worst matches."""
    from regateo.climb.mine import mine as mine_run

    async def go() -> None:
        store = await Store.open(_db(db), readonly=True)
        bundle = await mine_run(store, run_id, subject=subject, worst=worst)
        await store.close()
        if out:
            out.write_text(bundle.markdown())
            typer.echo(f"wrote {out}")
        else:
            typer.echo(bundle.markdown())

    asyncio.run(go())


@app.command()
def propose(
    run_id: str,
    parent: Annotated[str, typer.Option(help="agent config the challengers extend, e.g. single_call/v1/baseline")],
    reference: Annotated[str | None, typer.Option(help="reference for the gym (default: the parent)")] = None,
    subject: str = "b",
    n: Annotated[int, typer.Option(help="challengers to ask for")] = 6,
    proposer: Annotated[str, typer.Option(help="model profile that proposes")] = "qwen-local-propose",
    bench: str = "standard-v2",
    db: DbOpt = None,
) -> None:
    """Ask a local model for challengers from a run's failures; write their configs and a gym."""
    from regateo.climb.mine import mine as mine_run
    from regateo.climb.propose import ask, known_agents, write, write_experiment

    async def go() -> None:
        store = await Store.open(_db(db), readonly=True)
        bundle = await mine_run(store, run_id, subject=subject)
        known = await known_agents(store)
        await store.close()
        written, rejected = write(await ask(get_client(proposer), bundle, n=n), parent, known=known)
        typer.echo(fmt.proposals(written, rejected))
        if written:
            name = write_experiment(written, reference=reference or parent, bench=bench, source_run=run_id)
            typer.echo(f"\nNext: regateo gym {name}")

    asyncio.run(go())


@app.command()
def workspace(
    runs: Annotated[list[str], typer.Argument(help="dev benchmark gym runs whose matches it may read")],
    parent: Annotated[str, typer.Option(help="agent config to improve, e.g. single_call/v1/baseline")],
    out: Annotated[Path, typer.Option(help="empty folder to write the workspace to")],
    db: DbOpt = None,
) -> None:
    """Write a workspace for an agentic proposer: our agent, dev matches and results, nothing else."""
    from regateo.climb.workspace import export

    async def go() -> None:
        store = await Store.open(_db(db), readonly=True)
        await export(store, runs, parent, out)
        await store.close()

    asyncio.run(go())
    typer.echo(f"wrote {out}\nNext: bash engine/scripts/claude_proposer.sh {out}, then regateo adopt {out}")


@app.command()
def adopt(
    folder: Annotated[Path, typer.Argument(help="a workspace from `regateo workspace`, with candidates written")],
    reference: Annotated[str | None, typer.Option(help="reference to beat (default: the parent)")] = None,
    bench: str = "standard-v2",
    db: DbOpt = None,
) -> None:
    """Validate a workspace's candidates; write their configs and a gym (successive halving)."""
    from regateo.climb.propose import known_agents, write_experiment
    from regateo.climb.workspace import adopt as adopt_candidates
    from regateo.climb.workspace import workspace_meta

    async def known() -> dict[str, str]:
        store = await Store.open(_db(db), readonly=True)
        try:
            return await known_agents(store)
        finally:
            await store.close()

    meta = workspace_meta(folder)
    written, rejected = adopt_candidates(folder, known=asyncio.run(known()))
    typer.echo(fmt.proposals(written, rejected))
    if written:
        name = write_experiment(written, reference=reference or meta["parent"], bench=bench,
                                source_run=", ".join(meta["runs"]), by="an agentic proposer (`regateo workspace`)")
        typer.echo(f"\nNext: regateo gym {name}")


@app.command()
def climb(
    run_id: Annotated[str, typer.Argument(help="dev gym run whose failures to mine")],
    parent: Annotated[str, typer.Option(help="agent config the challengers extend")],
    reference: Annotated[str | None, typer.Option(help="reference to beat (default: the parent)")] = None,
    subject: str = "b",
    rounds: int = 1,
    n: int = 6,
    proposer: str = "qwen-local-propose",
    bench: str = "standard-v2",
    db: DbOpt = None,
) -> None:
    """Unattended rounds: mine, propose, successive halving on the full bench. Promotion stays manual."""
    from regateo.climb.loop import climb_round

    async def go() -> None:
        store = await Store.open(_db(db))
        source = run_id
        for i in range(rounds):
            typer.echo(f"Round {i + 1}/{rounds} (mining {source})")
            r = await climb_round(store, from_run=source, parent=parent, reference=reference or parent,
                                  subject=subject, bench=bench, n=n, proposer=proposer, on_progress=_progress)
            sys.stderr.write("\n")
            typer.echo(fmt.proposals(r.written, r.rejected))
            for agent, res in r.results.items():
                typer.echo(f"  {agent}: {res}")
            # The next round mines this one: the reference played the whole bench there, next to fresh
            # challengers to measure its regret against.
            source = r.run or source
        await store.close()

    asyncio.run(go())


@app.command("reader-eval")
def reader_eval(
    readers: Annotated[list[str], typer.Argument(help="readers to score, e.g. rules-v2 llm-first:qwen-local")],
    runs: Annotated[list[str] | None, typer.Option("--run", help="also score on these dev runs' matches, "
                                                   "against what LLM agents meant")] = None,
    sample: Annotated[int, typer.Option(help="matches to sample from --run")] = 150,
    out: Annotated[Path | None, typer.Option(help="write the misread examples here (YAML)")] = None,
    db: DbOpt = None,
) -> None:
    """Score message readers on the labeled corpus (configs/referee/reading-corpus.yaml), and optionally
    on stored dev matches against each LLM agent's recorded intent."""
    import yaml

    from regateo.referee.evaluate import evaluate, evaluate_on_runs
    from regateo.referee.registry import build_reader

    async def go() -> None:
        for name in readers:
            s = await evaluate(build_reader(name, get_client), name)
            typer.echo(f"corpus  {name}: {s.correct}/{s.cases} correct, {s.false_accepts} false acceptances, "
                       f"{s.missed_accepts} missed acceptances, {s.fallbacks} model failures (rules read those)")
            for m in s.misses:
                typer.echo(f"  - expected {m.case.kind.value} {m.case.price}, got {m.got_kind.value} {m.got_price}"
                           f"  ({m.case.source}) {m.case.messages[-1][:90]!r}")
        if not runs:
            return
        store = await Store.open(_db(db), readonly=True)
        scores = await evaluate_on_runs(store, runs, {n: build_reader(n, get_client) for n in readers},
                                        sample=sample)
        await store.close()
        for s in scores:
            typer.echo(f"intent  {s.reader}: {s.correct}/{s.messages} messages in {s.matches} matches agree, "
                       f"{s.false_accepts} false acceptances, {s.missed_accepts} missed acceptances, "
                       f"{s.fallbacks} model failures")
        if out:
            out.write_text(yaml.safe_dump([s.model_dump() for s in scores], sort_keys=False, allow_unicode=True,
                                          width=110))
            typer.echo(f"wrote {out}")

    asyncio.run(go())


@app.command()
def freeze(paths: Annotated[list[Path], typer.Argument(help="files to freeze, e.g. a prompt with results")]) -> None:
    """Record files in configs/frozen.json; a unit test then fails if they change."""
    for key in frozen.freeze(paths):
        typer.echo(f"frozen {key}")


round_app = typer.Typer(help="A climb round over several architectures (regateo.climb.round).", no_args_is_help=True)
app.add_typer(round_app, name="round")


@round_app.command("export")
def round_export(
    run: Annotated[str, typer.Argument(help="the last dev gym run the candidates played in")],
    candidate: Annotated[list[str], typer.Option(help="a config per architecture, e.g. single_call/v1/baseline")],
    out: Annotated[Path, typer.Option(help="folder for the workspaces, one per architecture")],
    venv: Annotated[bool, typer.Option(help="give each workspace a .venv with only the agent SDK and pytest")] = True,
    db: DbOpt = None,
) -> None:
    """Step 1: a workspace per candidate, holding only what its builder session may see."""
    from regateo.climb.round import export

    async def go() -> None:
        store = await Store.open(_db(db))
        try:
            for ws in await export(store, run, candidate, out, venv=venv):
                typer.echo(f"wrote {ws}")
        finally:
            await store.close()

    asyncio.run(go())
    typer.echo(f"Next: for ws in {out}/*/; do bash engine/scripts/claude_builder.sh \"$ws\" & done; wait\n"
               f"Then: regateo round collect {out}/* --name <round> --reference <agent>")


@round_app.command("collect")
def round_collect(
    workspaces: Annotated[list[Path], typer.Argument(help="the round's workspaces, after their sessions")],
    name: Annotated[str, typer.Option(help="the round's gym config name, e.g. round-01")],
    reference: Annotated[str, typer.Option(help="the agent every member is measured against")],
    bench: str = "standard-v2",
) -> None:
    """Step 3: take the sessions' variants into agents/ (checked), and write the round's gym config."""
    from regateo.climb.round import collect, write_round
    lines = []
    for ws in workspaces:
        got = asyncio.run(collect(ws))
        lines.append(got.line)
        typer.echo(f"{got.line.arch}: {got.line.parent} + {got.line.variants or 'no variants'}")
        for why in got.rejected:
            typer.echo(f"  refused: {why}")
    path = write_round(name, lines, reference=reference, bench=bench)
    typer.echo(f"wrote {path}\nNext: regateo gym {name}, then regateo round record <run>")


@round_app.command("record")
def round_record(run: str, db: DbOpt = None) -> None:
    """Step 4: each line's finalist, its next parent; the round's results go into every architecture's journal."""
    from regateo.climb.round import record

    async def go() -> None:
        store = await Store.open(_db(db))
        try:
            for arch, parent in (await record(store, run)).items():
                typer.echo(f"{arch}: next parent {parent}")
        finally:
            await store.close()

    asyncio.run(go())


@app.command(name="check-agent")
def check_agent_cmd(kinds: Annotated[list[str], typer.Argument(help="agent versions, e.g. single_call/v1")]) -> None:
    """The submission check (agent_sdk.check): what an agent version's code may import and call."""
    from agent_sdk import packages
    from agent_sdk.check import check_version

    from regateo.core.config import agents_dir
    packages.mount(agents_dir())
    failed = False
    for kind in kinds:
        problems = check_version(packages.folder(kind))
        for p in problems:
            typer.echo(f"  {p}")
        typer.echo(f"{kind}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        failed |= bool(problems)
    raise typer.Exit(1 if failed else 0)


@app.command()
def learnings(
    public: Annotated[bool, typer.Option(help="only what agent builders may see (docs/05, visibility)")] = False,
    arch: Annotated[str | None, typer.Option(help="everything a proposer for this architecture is given")] = None,
) -> None:
    """Print docs/05-learnings.md: whole, its public view, or what a session on one architecture is given."""
    from regateo.climb.learnings import learnings_path, public_view, tried
    if arch:
        typer.echo(tried(arch))
    else:
        text = learnings_path().read_text()
        typer.echo(public_view(text) if public else text)


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
