"""One unattended climb round (docs/04-hill-climbing.md §5.1, steps 1-4): mine the failures of a
dev run, propose challengers, and play them on the full bench with successive halving, so the best
finish it and the rest are cut early. Promotion (the holdout, the reading audit, freezing) stays with a person."""
from __future__ import annotations

from pydantic import BaseModel

from regateo.climb.mine import mine
from regateo.climb.propose import Rejected, Written, ask, log, write, write_experiment
from regateo.core.config import REPO_DIR, configs_dir, load_yaml
from regateo.gym import GymSpec, build_gym_report, run_gym
from regateo.gym.report import ChallengerStats, GymReport
from regateo.llm.registry import get_client
from regateo.runner.runner import Progress
from regateo.storage.store import Store


class RoundResult(BaseModel):
    experiment: str = ""
    written: list[Written] = []
    rejected: list[Rejected] = []
    run: str | None = None
    results: dict[str, str] = {}


def _result(c: ChallengerStats, where: str) -> str:
    d = c.diff
    if c.stopped_at is not None:
        return f"{where}: stopped early after {c.stopped_at} pairs, behind the reference"
    if c.halved_at is not None:
        return f"{where}: {d.mean_diff:+.3f} vs reference after {c.halved_at} pairs; cut by successive halving"
    verdict = "passes the automatic checks" if all(k.status in ("pass", "warn") for k in c.checks) else \
        "fails " + ", ".join(k.name for k in c.checks if k.status == "fail")
    return f"{where}: {d.mean_diff:+.3f} vs reference (p={d.p_value:.3f}, n={d.n}); {verdict}"


def _by_agent(report: GymReport, spec: GymSpec) -> dict[str, ChallengerStats]:
    names = {"a": spec.a.label, **{f"a{n}": s.label for n, s in enumerate(spec.extra, start=2)}}
    return {names[c.subject]: c for c in report.challengers}


async def climb_round(store: Store, *, from_run: str, parent: str, reference: str, subject: str = "b",
                      bench: str = "standard-v1", n: int = 6, proposer: str = "qwen-local-propose",
                      on_progress: Progress | None = None) -> RoundResult:
    bundle = await mine(store, from_run, subject=subject)
    proposals = await ask(get_client(proposer), bundle, n=n)
    written, rejected = write(proposals, parent)
    out = RoundResult(written=written, rejected=rejected)
    if not written:
        return out
    out.experiment = write_experiment(written, reference=reference, bench=bench, source_run=from_run)
    labels = {w.agent: w.agent.replace("/", "-") for w in written}

    spec = load_yaml(configs_dir() / "gym" / f"{out.experiment}.yaml", GymSpec)
    out.run, _ = await run_gym(spec, store, on_progress=on_progress)
    report = _by_agent(await build_gym_report(store, out.run), spec)
    for agent, label in labels.items():
        out.results[agent] = _result(report[label], "bench")
    log(written, out.results)
    _write_results(out)
    return out


def _write_results(r: RoundResult) -> None:
    num = r.experiment.split("-")[1]
    doc = REPO_DIR / "docs" / "experiments" / f"{num}-climb.md"
    lines = [f"Run: {r.run}.", ""]
    lines += [f"- **{agent}**: {res}" for agent, res in r.results.items()]
    doc.write_text(doc.read_text().replace("(pending)", "\n".join(lines)))
