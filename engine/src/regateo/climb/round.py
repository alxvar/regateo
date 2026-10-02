"""A climb round over several architectures (docs/07-hackathon-plan.md, docs/04-hill-climbing.md §5).

1. `export`: for each candidate (one config per architecture), a workspace holding only what a builder
   session for it may see (docs/06 §5): a copy of its architecture, its own matches and results from the
   last gym run, an anonymous leaderboard, and what was learned (the public view of docs/05 and its
   journal). Optionally a Python environment with only the agent SDK in it.
2. A Claude Code session per workspace, in parallel, in a sandbox (scripts/claude_builder.sh). It studies
   the results and writes 1 to 3 variants: new configs, or a new version of the agent; then a journal entry.
3. `collect`: copies what the sessions made back into agents/, after checking it (new versions and
   configs only, nothing frozen changed, the submission check, a smoke match), and writes the round's gym
   config: every line's parent and its new variants, with successive halving within each line.
4. The gym run, then `record`: each line's finalist becomes its next parent, and every architecture's
   journal gets the round's results.
"""
from __future__ import annotations

import filecmp
import json
import random
import shutil
import subprocess
from pathlib import Path

import yaml
from agent_sdk import packages
from pydantic import BaseModel

from regateo.agents import AgentSpec, TrustedContext, build_agent
from regateo.cli import format as fmt
from regateo.climb.learnings import tried
from regateo.climb.workspace import _match
from regateo.core.config import REPO_DIR, agents_dir, configs_dir
from regateo.core.roles import Role, other
from regateo.gym import build_gym_report
from regateo.gym.report import ChallengerStats, GymReport
from regateo.gym.signals import SidePlay, run_signals, sides
from regateo.storage.store import Store

META = ".regateo-round.json"
MAX_VARIANTS = 3
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


class Line(BaseModel):
    """One architecture in a round: its current best config, and the variants a session made from it."""
    arch: str
    parent: str                         # config, e.g. single_call/v1/baseline
    variants: list[str] = []


class Collected(BaseModel):
    line: Line
    rejected: list[str] = []            # what was refused, and why


# 1. Export


async def export(store: Store, run_id: str, candidates: list[str], out: Path, *, venv: bool = False,
                 also: list[str] = (), redteam: str | None = None) -> list[Path]:
    """One workspace per candidate under `out/<architecture>/`. `run_id`: the last gym run they all played in.
    `also`: configs that play in their architecture's line this round besides the session's variants (e.g. one
    made outside a round, not measured yet). `redteam`: an adversarial gym run whose results, for each line's
    agents, go into the workspace as a summary (data/redteam.md), not as transcripts."""
    run = await store.get_run(run_id)
    if run is None or run.kind != "gym" or run.config.get("mode") != "benchmark":
        raise ValueError(f"{run_id} is not a benchmark gym run")
    if run.config.get("purpose") != "dev":
        raise ValueError(f"{run_id} is not a dev run: only dev transcripts may be shown (docs/04 §4)")
    archs = [c.split("/")[0] for c in candidates]
    if len(set(archs)) != len(archs):
        raise ValueError("one candidate per architecture: a round has one line per architecture")
    extra: dict[str, list[str]] = {}
    for name in also:
        AgentSpec.resolve(name)
        if name.split("/")[0] not in archs:
            raise ValueError(f"{name}: no candidate of its architecture")
        extra.setdefault(name.split("/")[0], []).append(name)
    rt = await _redteam_plays(store, redteam) if redteam else None
    report = await build_gym_report(store, run_id)
    subjects = {"b": report.b.label, **{c.subject: c.side.label for c in report.challengers}}
    rows = [r for r in await store.list_matches(run_id) if r.status == "done" and r.outcome]
    made = []
    for candidate in candidates:
        spec = AgentSpec.resolve(candidate)
        subject = next((s for s, label in subjects.items() if label == spec.label), None)
        if subject is None:
            raise ValueError(f"{candidate} didn't play in {run_id}")
        matches = [_match(r, Role(r.meta["role"]), await store.match_messages(r.id), run_id, "you")
                   for r in rows if r.meta["subject"] == subject]
        arch = spec.kind.split("/")[0]
        ws = _write_workspace(out, candidate, arch, subject, report, matches, venv, extra.get(arch, []),
                              rt is not None)
        if rt is not None:
            labels = [AgentSpec.resolve(c).label for c in [candidate, *extra.get(arch, [])]]
            (ws / "data" / "redteam.md").write_text(_redteam(*rt, labels))
        made.append(ws)
    return made


def _write_workspace(out: Path, candidate: str, arch: str, subject: str, report: GymReport, matches: list[dict],
                     venv: bool, also: list[str] = (), redteam: bool = False) -> Path:
    ws = out / arch
    if ws.exists():
        raise ValueError(f"{ws} exists")
    shutil.copytree(agents_dir() / arch, ws / "agents" / arch, ignore=_IGNORE)
    shutil.copy(agents_dir() / "conftest.py", ws / "agents" / "conftest.py")
    (ws / "data").mkdir()
    for m in matches:
        m.pop("run"), m.pop("agent")
    (ws / "data" / "matches.jsonl").write_text("".join(json.dumps(m) + "\n" for m in matches))
    (ws / "data" / "results.md").write_text(_results(report, subject))
    (ws / "data" / "leaderboard.md").write_text(_leaderboard(report, subject))
    (ws / "data" / "learnings.md").write_text(tried(arch))
    (ws / "README.md").write_text(_task(arch, candidate, list(also), redteam))
    shutil.copy(REPO_DIR / "docs" / "06-agent-contract.md", ws / "CONTRACT.md")
    (ws / META).write_text(json.dumps({"arch": arch, "parent": candidate, "run": report.run_id, "also": list(also),
                                       "versions": _versions(agents_dir() / arch)}, indent=2))
    if venv:
        _make_venv(ws)
    return ws


def _versions(arch_dir: Path) -> dict[str, list[str]]:
    """Each version of an architecture, with its configs."""
    return {v.name: sorted(c.stem for c in (v / "configs").glob("*.yaml"))
            for v in sorted(arch_dir.iterdir()) if v.is_dir() and packages.is_version(f"{arch_dir.name}/{v.name}")}


def _results(report: GymReport, subject: str) -> str:
    """The candidate's own results: against the reference by opponent, role and cell, gates and checks."""
    lines = [f"# Your results in run {report.run_id}", ""]
    c = next((c for c in report.challengers if c.subject == subject), None)
    if c is None:                       # the candidate is the reference
        b = report.b
        lines += [f"You were the reference. Share {fmt.est(b.mean_share)}, deals {fmt.est(b.deal_rate, True)}, "
                  f"deals past your limit {b.past_reservation}.", "",
                  "The leaderboard shows how the other agents did against you."]
        return "\n".join(lines) + "\n"
    lines += [f"Share {fmt.est(c.side.mean_share)} against the reference's {fmt.est(c.reference.mean_share)} on the "
              f"same pairs: {fmt.diff(c.diff)}.",
              f"Deals {fmt.est(c.side.deal_rate, True)}, past your limit "
              f"{c.side.past_reservation + c.gate_past_reservation}.",
              ""]
    lines += _anon_tables(c)
    lines += ["", "## Promotion checks", ""] + [f"- {k.status}: {k.name}: {k.detail}" for k in c.checks]
    return "\n".join(lines) + "\n"


def _anon_tables(c: ChallengerStats) -> list[str]:
    out = []
    for title, rows in (("By opponent (scored)", c.by_opponent), ("Gates (not scored, may not drop by more than "
                        "0.10)", c.gates), ("By role", c.by_role), ("By cell", c.by_cell)):
        if rows:
            out += ["", f"## {title}", "", "| | you | reference | you − reference |", "|---|---|---|---|"]
            out += [f"| {b.key} | {fmt.est(b.a)} | {fmt.est(b.b)} | {fmt.diff(b.diff)} |" for b in rows]
    return out


def _leaderboard(report: GymReport, subject: str) -> str:
    """Everyone's Δshare against the reference, without names: what others built stays theirs."""
    rows = sorted(report.challengers, key=lambda c: -(c.diff.mean_diff or 0))
    lines = ["# Leaderboard", "", "Every agent in the run against the same reference, on the same pairs. Names are "
             "hidden; only yours is shown.", "", "| | Δshare vs reference | share |", "|---|---|---|"]
    others = 0
    for c in rows:
        if c.subject == subject:
            name = "**you**"
        else:
            others += 1
            name = f"agent {others}"
        lines.append(f"| {name} | {fmt.diff(c.diff)} | {fmt.est(c.side.mean_share)} |")
    ref = "**you**" if subject == "b" else "the reference"
    lines.append(f"| {ref} | 0 | {fmt.est(report.b.mean_share)} |")
    return "\n".join(lines) + "\n"


async def _redteam_plays(store: Store, run_id: str) -> tuple[GymReport, list[SidePlay], set[str]]:
    run = await store.get_run(run_id)
    if run is None or run.kind != "gym" or run.config.get("purpose") != "adversarial":
        raise ValueError(f"{run_id} is not an adversarial gym run")
    plays = []
    for row in await store.list_matches(run_id):
        if row.status == "done":
            plays += sides(row, await store.match_messages(row.id))
    return await build_gym_report(store, run_id), plays, set(run.config.get("twins") or {})


def _redteam(report: GymReport, plays: list[SidePlay], plain: set[str], labels: list[str]) -> str:
    """What the red-team opponents cost each of `labels`: share by opponent, each attack against its plain twin,
    the exploit signals, and the last messages of its worst match against each attack. No full transcripts: the
    scripted attackers play the same way every time, and the point is to fix a weakness, not learn their wording."""
    out = [f"# Red-team results (run {report.run_id})", "",
           "Opponents written after reading our agents' code, each attacking one weakness seen in earlier rounds. "
           "Most attacks have a plain twin: the same price moves in plain words, without the trap, on the same "
           "scenarios and seeds. Share against the attack minus share against its twin is what the attack itself "
           "costs. Stonewall and anchor attack with their moves, so they have no twin. `redteam:llm` is Qwen with "
           "thinking and a brief of our agents' weaknesses; `redteam:llm-plain` is the same without the brief.", "",
           "This bench is for finding weaknesses, not for scoring: the round is measured on the dev bench, and these "
           "agents will be red-teamed again afterwards. Fix the weakness so it holds against any opponent; the "
           "tournament's opponents won't use these exact words or schedules.", ""]
    for label in labels:
        c = next((c for c in report.challengers if c.side.label == label), None)
        mine = [p for p in plays if p.agent == label]
        if c is None and not mine:
            continue
        out += [f"## {label}", ""]
        if c is not None:
            out += [f"Share {fmt.est(c.side.mean_share)} against the reference's {fmt.est(c.reference.mean_share)} "
                    f"on the same pairs; deals past your limit {c.side.past_reservation}.", "",
                    "| opponent | you | reference | you − reference |", "|---|---|---|---|"]
            out += [f"| {b.key} | {fmt.est(b.a)} | {fmt.est(b.b)} | {fmt.diff(b.diff)} |" for b in c.by_opponent]
        costs = [t for t in report.twins if t.key.split(" | ", 1)[0] == label]
        if costs:
            out += ["", "What each attack costs you:", "",
                    "| attack | against it | against its plain twin | cost |", "|---|---|---|---|"]
            out += [f"| {t.key.split(' | ', 1)[1]} | {fmt.est(t.a)} | {fmt.est(t.b)} | {fmt.diff(t.diff)} |"
                    for t in costs]
        rows = [s for s in run_signals(mine, by_opponent=True) if s.opponent != "all"]
        if rows:
            out += ["", "Exploit signals (count / out of): dominated = matches where you offered worse for yourself "
                    "than their standing offer; unreciprocated = concessions made with no move from them; missed = "
                    "no-deals where they had offered a price within your limit; broken = offers you called final "
                    "and conceded from; near limit = matches where you named your own walk-away price.", "",
                    "| opponent | matches | dominated | unreciprocated | missed | broken | near limit | repeats |",
                    "|---|---|---|---|---|---|---|---|"]
            out += [f"| {s.opponent} | {s.matches} | {s.dominated}/{s.matches} | {s.unreciprocated}/{s.concessions} "
                    f"| {s.missed}/{s.no_deals} | {s.broken_finals}/{s.finals} | {s.near_limit}/{s.matches} "
                    f"| {s.repeats}/{s.turns} |" for s in rows]
        worst = {}
        for p in mine:
            if p.opponent not in plain and (p.opponent not in worst
                                            or p.outcome.share(p.role) < worst[p.opponent].outcome.share(p.role)):
                worst[p.opponent] = p
        if worst:
            out += ["", "Your worst match against each attack, its last four messages:"]
        for opponent in sorted(worst):
            p = worst[opponent]
            s, o = p.scenario, p.outcome
            out += ["", f"**{opponent}**, you as {p.role.value}: your limit {s.reservation(p.role):g}, theirs "
                    f"{s.reservation(other(p.role)):g}; " + (f"deal at {o.price:g}" if o.deal else "no deal")
                    + f", your share {o.share(p.role):.2f}.", ""]
            out += [f"> {'us' if m.sender is p.role else 'them'}: {_short(m.text)}" for m in p.messages[-4:]]
    return "\n".join(out) + "\n"


def _short(text: str, n: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _make_venv(ws: Path) -> None:
    """A Python environment in the workspace with only the agent SDK and pytest: no engine to import."""
    subprocess.run(["uv", "venv", "-q", str(ws / ".venv")], check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(ws / ".venv" / "bin" / "python"),
                    str(REPO_DIR / "agent-sdk"), "pytest", "pytest-asyncio"], check=True)
    (ws / "pytest.ini").write_text("[pytest]\nasyncio_mode = auto\naddopts = --import-mode=importlib\n")


def _task(arch: str, parent: str, also: list[str] = (), redteam: bool = False) -> str:
    also_note = (f"""
Also in this round's line, besides your variants: {", ".join(f"`{a}`" for a in also)}, not measured on the
benchmark yet (the journal says what it is). You may build on it instead of on `{parent}`: a variant of it
counts as a variant like any other. Every variant is still measured against the same reference, and the best
of the line goes on.
""" if also else "")
    redteam_md = ("""- `data/redteam.md`: how this line's agents did against red-team opponents written to exploit known
  weaknesses: what each attack costs, exploit signals, and the end of the worst match against each.
""" if redteam else "")
    return f"""# Improve a negotiating agent

You are improving `{parent}`, an agent of the architecture `{arch}`. It negotiates the price of one item against
another AI agent, as buyer or seller, in free text. Several architectures compete in this round; each is improved
by its own session, and none can see the others. After this session, every agent's new variants play the same
benchmark, and within each architecture only a variant that beats its parent goes on.
{also_note}
## What you have

- `agents/{arch}/`: the architecture: its versions (`v<N>/`, each with its code, `prompts/`, `configs/` and
  `tests/`), shared code in `lib/`, and `JOURNAL.md`, what was tried on it so far. Read the journal first.
- `data/results.md`: how `{parent}` did against the reference, by opponent, role and rules cell, and the
  promotion checks. `data/leaderboard.md`: where it stands among the others, names hidden.
- `data/matches.jsonl`: every match it played: the scenario, both walk-away prices (the other side's is there
  for your analysis; the agent never knows it), the result, and every message with its own decision and how the
  referee read it.
{redteam_md}- `data/learnings.md`: what we have learned across architectures, and this one's journal.
- `CONTRACT.md`: what any agent must do, and may not. Its rules are this session's rules.
- The agent SDK, the only thing agent code may import from our side, is installed in `.venv`
  (`.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/regateo-agent`); its source is in
  `.venv/lib/python*/site-packages/agent_sdk/`.

## The rules

- Scoring: share of the zone of possible agreement captured, 0 at our walk-away price, 1 at theirs; no deal is
  0. Only the LLM opponents are scored. Against the scripted ones (gates) a variant may not drop by more than
  0.10, and a deal past our walk-away price anywhere disqualifies it.
- Strategy lives in the model: code may veto a move that breaks a hard rule (never past the walk-away price,
  never sound like accepting when not accepting, never reveal the walk-away price), compute facts for the model
  and handle failures. Code may not pick prices, concession schedules or when to accept.
- Opponents in the tournament will be stronger and adaptive. Prefer changes that should hold against any
  opponent over ones that fit these.
- Agent code may import only `agent_sdk`, a short list of standard-library modules, pydantic and its own
  architecture. No files, network or processes. `regateo-agent check agents/{arch}/v<N>` tells you if a version
  passes; a version that doesn't is thrown away.

## What to deliver

Up to {MAX_VARIANTS} variants of `{parent}`, each testing one hypothesis:

- **Settings only:** a new config in the parent's version: `agents/{arch}/<version>/configs/<name>.yaml`,
  `extends: {parent}` plus the params it changes.
- **Code or prompts:** a new version, `agents/{arch}/v<N+1>/`, a copy of the parent's version with your change,
  and its configs. Never change an existing version or `lib/`: they have results, and changing them would make
  those results meaningless. Put new shared code in your new version.
- Run `regateo-agent check` and `pytest agents/{arch}` on what you made.
- **List them** in `variants.txt` in this folder, one per line, as `{arch}/<version>/<config>` (e.g.
  `{arch}/v2/firmer`): only the configs listed there are measured.
- **Journal:** add an entry at the end of `agents/{arch}/JOURNAL.md`: for each variant, its name, the failure it
  targets with evidence from the data, the hypothesis, and what result would prove it wrong. Don't edit earlier
  entries.

## The shell

The shell allows only these programs, called by their bare name from this folder: `python`, `python3`,
`pytest`, `regateo-agent` (all from `.venv`, already on PATH), `cp`, `mkdir`, `ls`, `wc`, `head`, `tail`, `jq`
and `diff`. Anything else is refused, including `cd`, `cat`, `rm`, paths like `.venv/bin/python`, and chains
with `;`, `&&` or pipes into other programs. So: one program per command, run from here (for example
`pytest agents/{arch} -q` or `regateo-agent check agents/{arch}/v2`). Read files with the Read tool, write them
with Write and Edit, and do analysis in a script you write to a file and run with `python <file>`.

Work only inside this folder.
"""


# 3. Collect


async def collect(ws: Path, *, smoke: bool = True) -> Collected:
    """Copy a session's new versions, configs and journal entry into agents/, after checking them. The variants are
    the configs the session listed in variants.txt (without one, its new configs in name order), at most
    MAX_VARIANTS, after the export's `also` configs."""
    meta = json.loads((ws / META).read_text())
    arch, parent = meta["arch"], meta["parent"]
    src, dst = ws / "agents" / arch, agents_dir() / arch
    line, rejected = Line(arch=arch, parent=parent, variants=list(meta.get("also", []))), []
    listed = None
    if (ws / "variants.txt").exists():
        listed = [x.strip() for x in (ws / "variants.txt").read_text().splitlines() if x.strip()]
    packages.mount(agents_dir())
    new_versions, new_configs = [], []
    for v in sorted(p for p in src.iterdir() if p.is_dir()):
        if v.name == "lib":
            if _changed(v, dst / "lib"):
                rejected.append("lib/ was changed: shared code is frozen with the versions using it")
            continue
        if not packages.is_version(f"{arch}/{v.name}"):
            continue
        if v.name not in meta["versions"]:
            new_versions.append(v.name)
            continue
        if _changed(v, dst / v.name, skip_configs=True):
            rejected.append(f"{v.name} was changed: an existing version's code, prompts and tests stay as they are")
        new_configs += [(v.name, c) for c in sorted((v / "configs").glob("*.yaml")) if c.stem not in
                        meta["versions"][v.name]]
    for name in new_versions:
        shutil.copytree(src / name, dst / name, ignore=_IGNORE)
        try:
            from regateo.agents.base import check_agent
            check_agent(f"{arch}/{name}")
        except ValueError as e:
            shutil.rmtree(dst / name)
            rejected.append(str(e))
            continue
        new_configs += [(name, c) for c in sorted((dst / name / "configs").glob("*.yaml"))]
    made = {f"{arch}/{version}/{path.stem}": (version, path) for version, path in new_configs}
    if listed is not None:
        rejected += [f"{name} (variants.txt): not a new config of this session" for name in listed if name not in made]
        for name in made.keys() - set(listed):
            version, path = made[name]
            if version in new_versions:          # copied with its version: an unlisted config doesn't stay
                (dst / version / "configs" / path.name).unlink(missing_ok=True)
        new_configs = [made[name] for name in dict.fromkeys(listed) if name in made]
    taken = 0
    for version, path in new_configs:
        name = f"{arch}/{version}/{path.stem}"
        if taken >= MAX_VARIANTS:
            rejected.append(f"{name}: more than {MAX_VARIANTS} variants")
            if version in new_versions:
                (dst / version / "configs" / path.name).unlink(missing_ok=True)
            continue
        target = dst / version / "configs" / path.name
        if not target.exists():
            shutil.copy(path, target)
        if (why := await _try(name, smoke)) is not None:
            target.unlink()
            rejected.append(f"{name}: {why}")
            continue
        line.variants.append(name)
        taken += 1
    for name in new_versions:                    # a new version none of whose configs made it goes too
        if (dst / name).exists() and not any(v.startswith(f"{arch}/{name}/") for v in line.variants):
            shutil.rmtree(dst / name)
    journal_src, journal_dst = src / "JOURNAL.md", dst / "JOURNAL.md"
    old = journal_dst.read_text() if journal_dst.exists() else ""
    new = journal_src.read_text() if journal_src.exists() else old
    if not new.startswith(old.rstrip()):
        rejected.append("JOURNAL.md: earlier entries were changed; its new entry was not taken")
    elif new != old:
        journal_dst.write_text(new)
    return Collected(line=line, rejected=rejected)


def _changed(a: Path, b: Path, skip_configs: bool = False) -> bool:
    """True when folder `a` differs from `b` (configs/ aside when `skip_configs`)."""
    if not b.exists():
        return True
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".pytest_cache", *(["configs"] if skip_configs else [])])
    return _differs(cmp)


def _differs(cmp: filecmp.dircmp) -> bool:
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return True
    _, mismatch, errors = filecmp.cmpfiles(cmp.left, cmp.right, cmp.common_files, shallow=False)
    return bool(mismatch or errors) or any(_differs(sub) for sub in cmp.subdirs.values())


async def _try(name: str, smoke: bool) -> str | None:
    """Why config `name` can't be played, or None: it must resolve, and play one match on a fake model."""
    try:
        spec = AgentSpec.resolve(name)
        if not smoke:
            return None
        from regateo.core import Rules, Scenario
        from regateo.llm.providers.fake import FakeProvider
        from regateo.match import SimClock, run_match
        from regateo.protocol import get_protocol
        from regateo.referee import TextDetector

        s = Scenario(id="smoke", item="a used bike", seller_reservation=100, buyer_reservation=150, market_low=80,
                     market_high=180, rules=Rules(max_rounds=3))
        protocol, fake = get_protocol("freetext"), FakeProvider(lambda req: "ok")
        def ctx(role):  # noqa: E306
            return TrustedContext(role=role, rng=random.Random(0), protocol=protocol.info(), true_rules=s.rules,
                                  llm_factory=lambda profile, stage: fake)
        agent = build_agent(spec.model_copy(update={"model": "fake"}), s.view_for(Role.SELLER), ctx(Role.SELLER))
        other = build_agent(AgentSpec(kind="scripted:linear"), s.view_for(Role.BUYER), ctx(Role.BUYER))
        result = await run_match(s, agent, other, protocol=protocol, detector=TextDetector(),
                                 rng=random.Random(0), clock=SimClock(seed=0))
        if result.outcome.end_reason.value == "error":
            return f"crashed in a smoke match: {result.outcome.detail}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None


def write_round(name: str, lines: list[Line], *, reference: str, bench: str = "standard-v2") -> Path:
    """The round's gym config: every line's parent and variants against `reference`, with successive halving
    within each line down to one finalist, the line's next parent. When the reference is a line's parent, it
    plays as B, and its variants have to beat it (Δshare > 0) to replace it."""
    members = {m: line.arch for line in lines for m in [line.parent, *line.variants]}
    ref = AgentSpec.resolve(reference).label
    challengers = [m for m in members if AgentSpec.resolve(m).label != ref]   # a reference line's parent is B
    if not challengers:
        raise ValueError("nothing to measure: no line has a member other than the reference")
    gym = {"name": name, "bench": bench, "reference": reference, "challengers": challengers,
           "halving": True, "early_stop": True,
           "lines": {AgentSpec.resolve(m).label: arch for m, arch in members.items()},
           "settings": {"concurrency": 32, "cache": "readwrite"}}
    path = configs_dir() / "gym" / f"{name}.yaml"
    path.write_text(f"# Climb round {name} (regateo.climb.round): {len(lines)} lines.\n"
                    + yaml.safe_dump(gym, sort_keys=False, width=1000))
    return path


# 4. Record


async def record(store: Store, run_id: str) -> dict[str, str]:
    """Each line's finalist (its next parent), and a journal entry per architecture with every member's result."""
    run = await store.get_run(run_id)
    if run is None or not run.config.get("lines"):
        raise ValueError(f"{run_id} is not a climb round (no lines)")
    report = await build_gym_report(store, run_id)
    labels = {AgentSpec.model_validate(s).label: AgentSpec.model_validate(s)
              for s in [run.config["a"], run.config["b"], *run.config.get("extra", [])]}
    by_line: dict[str, list[ChallengerStats]] = {}
    for c in report.challengers:
        by_line.setdefault(run.config["lines"].get(c.side.label, c.side.label), []).append(c)
    ref_line = run.config["lines"].get(report.b.label)      # the line whose parent is the reference, if any
    parents = {}
    for arch, members in by_line.items():
        full = [c for c in members if c.halved_at is None and c.stopped_at is None]
        best = max(full or members, key=lambda c: (c.diff.mean_diff or -1e9))
        if arch == ref_line and (not full or (best.diff.mean_diff or 0) <= 0):
            best = None                                     # no variant beat the reference: it stays the parent
        parents[arch] = _config_name(labels[best.side.label if best else report.b.label])
        rows = [f"- `{_config_name(labels[c.side.label])}`: {fmt.diff(c.diff)}"
                + (f", cut after {c.halved_at} pairs" if c.halved_at is not None else "")
                + (" **(next parent)**" if c is best else "") for c in members]
        if arch == ref_line:
            rows.insert(0, f"- `{_config_name(labels[report.b.label])}` (the reference): 0"
                        + (" **(next parent)**" if best is None else ""))
        journal = agents_dir() / arch / "JOURNAL.md"
        if journal.exists():
            journal.write_text(journal.read_text().rstrip() + f"\n\n**Round {run.name}** ({run_id}), Δshare against "
                               f"the reference `{report.b.label}` on {run.config.get('bench')}:\n\n"
                               + "\n".join(rows) + "\n")
    return parents


def _config_name(spec: AgentSpec) -> str:
    """`single_call/v1/baseline` for the spec of that config (its label is single_call-v1-baseline)."""
    return f"{spec.kind}/{spec.label.removeprefix(spec.kind.replace('/', '-') + '-')}"
