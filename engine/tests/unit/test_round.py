"""A climb round end to end, offline: export, sessions (simulated), collect, the round's gym, record."""
import json
import shutil

import pytest
import yaml

from regateo.climb import round as rnd
from regateo.gym import GymSpec, build_gym_report, run_gym
from regateo.storage import Store

TOY = '''from agent_sdk import ActionKind, Move, sign


class Toy:
    def __init__(self, config, view, ctx):
        self.name, self.view, self.n = config.name, view, 0
        self.step = config.params.get("step", 1.0) * STEP

    async def respond(self, obs):
        v = self.view
        s = sign(v.role)
        top = max(s * v.market_low, s * v.market_high)
        u = max(top - 10 * self.step * self.n, s * v.reservation)
        self.n += 1
        return Move(text=f"I can do ${s * u:.0f}.", action=ActionKind.OFFER, price=round(s * u))


def build(config, view, ctx):
    return Toy(config, view, ctx)
'''


def arch(root, name, step=1.0):
    v1 = root / name / "v1"
    (v1 / "configs").mkdir(parents=True)
    (root / name / "lib").mkdir()
    (root / name / "lib" / "__init__.py").write_text("")
    (root / name / "__init__.py").write_text("")
    (v1 / "__init__.py").write_text(f"STEP = {step}\n" + TOY)
    (v1 / "configs" / "base.yaml").write_text("params: {step: 1.0}\n")
    (root / name / "JOURNAL.md").write_text(f"# {name}: journal\n\n## v1\n\nThe first one.\n")


@pytest.fixture
def world(tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "conftest.py").write_text("")
    arch(agents, "toy_a")
    arch(agents, "toy_b", step=2.0)
    configs = tmp_path / "configs"
    for d in ("benches", "gym"):
        (configs / d).mkdir(parents=True)
    (configs / "benches" / "toy.yaml").write_text(yaml.safe_dump({
        "purpose": "dev", "mode": "benchmark", "opponents": ["scripted:hardliner", "scripted:linear"],
        "gates": ["scripted:liar"], "scenarios": {"per_cell": 4, "max_rounds": [4]}, "protocol": "structured",
        "detector": "structured", "reader": "rules", "sim_clock": True, "seed": 1}))
    monkeypatch.setenv("REGATEO_AGENTS", str(agents))
    monkeypatch.setenv("REGATEO_CONFIGS", str(configs))
    monkeypatch.setenv("REGATEO_DATA", str(tmp_path / "data"))
    return tmp_path


async def test_a_round(world):
    agents = world / "agents"
    store = await Store.open(world / "db")
    first = GymSpec.model_validate({"name": "r0", "bench": "toy", "reference": "boulware",
                                    "challengers": ["toy_a/v1/base", "toy_b/v1/base"]})
    run0, _ = await run_gym(first, store)

    # 1. Export: one workspace per architecture, with only its own things
    made = await rnd.export(store, run0, ["toy_a/v1/base", "toy_b/v1/base"], world / "round")
    a, b = made
    assert sorted(p.name for p in (a / "agents").iterdir()) == ["conftest.py", "toy_a"]
    assert (a / "CONTRACT.md").exists() and "toy_a/v1/base" in (a / "README.md").read_text()
    m = json.loads((a / "data" / "matches.jsonl").read_text().splitlines()[0])
    assert {"our_limit", "their_limit", "messages", "result"} <= set(m) and "agent" not in m
    board = (a / "data" / "leaderboard.md").read_text()
    assert "**you**" in board and "agent 1" in board and "toy_b" not in board and "boulware" not in board
    assert "toy_b" not in (a / "data" / "results.md").read_text()

    # 2. Sessions, simulated. toy_a: a settings variant, and a new version with changed code.
    (a / "agents/toy_a/v1/configs/slower.yaml").write_text("extends: toy_a/v1/base\nparams: {step: 0.5}\n")
    shutil.copytree(a / "agents/toy_a/v1", a / "agents/toy_a/v2")
    for c in (a / "agents/toy_a/v2/configs").iterdir():
        c.unlink()
    (a / "agents/toy_a/v2/__init__.py").write_text("STEP = 0.25\n" + TOY)
    (a / "agents/toy_a/v2/configs/patient.yaml").write_text("params: {step: 1.0}\n")
    journal = a / "agents/toy_a/JOURNAL.md"
    journal.write_text(journal.read_text() + "\n## Round 1\n\nslower and patient: concede less per turn.\n")
    # toy_b: edits a version with results, and adds one that fails the submission check
    (b / "agents/toy_b/v1/__init__.py").write_text("STEP = 9.0\n" + TOY)
    shutil.copytree(b / "agents/toy_b/v1", b / "agents/toy_b/v2")
    (b / "agents/toy_b/v2/__init__.py").write_text("import os\n" + TOY)

    # 3. Collect
    got_a, got_b = await rnd.collect(a), await rnd.collect(b)
    assert got_a.line.variants == ["toy_a/v1/slower", "toy_a/v2/patient"] and got_a.rejected == []
    assert (agents / "toy_a/v2/__init__.py").exists() and "Round 1" in (agents / "toy_a/JOURNAL.md").read_text()
    assert got_b.line.variants == [] and len(got_b.rejected) == 2
    assert "STEP = 2.0" in (agents / "toy_b/v1/__init__.py").read_text()      # untouched
    assert not (agents / "toy_b/v2").exists()                                   # refused, not copied
    path = rnd.write_round("round-01", [got_a.line, got_b.line], reference="boulware", bench="toy")
    spec = GymSpec.model_validate(yaml.safe_load(path.read_text()))
    assert spec.lines == {"toy_a-v1-base": "toy_a", "toy_a-v1-slower": "toy_a", "toy_a-v2-patient": "toy_a",
                          "toy_b-v1-base": "toy_b"}

    # 4. The round: halving within each line down to one finalist; record picks the next parents
    spec = spec.model_copy(update={"halving": spec.halving.model_copy(update={"first": 4})})
    run1, _ = await run_gym(spec, store)
    report = await build_gym_report(store, run1)
    finalists = [c.side.label for c in report.challengers if c.halved_at is None]
    assert sorted(spec.lines[f] for f in finalists) == ["toy_a", "toy_b"]       # one per line
    parents = await rnd.record(store, run1)
    assert parents["toy_b"] == "toy_b/v1/base" and parents["toy_a"].startswith("toy_a/")
    assert "next parent" in (agents / "toy_a/JOURNAL.md").read_text()


async def test_holdout_runs_are_not_exported(world):
    (world / "configs/benches/hold.yaml").write_text(yaml.safe_dump({
        "purpose": "holdout", "mode": "benchmark", "opponents": ["scripted:hardliner"],
        "scenarios": {"per_cell": 2, "max_rounds": [4]}, "protocol": "structured", "detector": "structured",
        "reader": "rules", "sim_clock": True, "seed": 1}))
    store = await Store.open(world / "db")
    run, _ = await run_gym(GymSpec.model_validate({"name": "h", "bench": "hold", "reference": "boulware",
                                                   "challengers": ["toy_a/v1/base"]}), store)
    with pytest.raises(ValueError, match="not a dev run"):
        await rnd.export(store, run, ["toy_a/v1/base"], world / "round")


async def test_the_reference_can_be_a_lines_parent(world):
    """The reference's own line: its parent plays as B, and a variant replaces it only by beating it."""
    agents = world / "agents"
    (agents / "toy_a/v1/configs/slower.yaml").write_text("extends: toy_a/v1/base\nparams: {step: 0.5}\n")
    (agents / "toy_a/v1/configs/faster.yaml").write_text("extends: toy_a/v1/base\nparams: {step: 3.0}\n")
    lines = [rnd.Line(arch="toy_a", parent="toy_a/v1/base", variants=["toy_a/v1/slower", "toy_a/v1/faster"]),
             rnd.Line(arch="toy_b", parent="toy_b/v1/base")]
    path = rnd.write_round("round-01", lines, reference="toy_a/v1/base", bench="toy")
    spec = GymSpec.model_validate(yaml.safe_load(path.read_text()))
    assert [s.label for s in spec.subjects().values()] == ["toy_a-v1-slower", "toy_a-v1-base", "toy_a-v1-faster",
                                                           "toy_b-v1-base"]
    with pytest.raises(ValueError, match="nothing to measure"):
        rnd.write_round("round-02", [rnd.Line(arch="toy_a", parent="toy_a/v1/base")], reference="toy_a/v1/base",
                        bench="toy")

    store = await Store.open(world / "db")
    spec = spec.model_copy(update={"halving": spec.halving.model_copy(update={"first": 4})})
    run, _ = await run_gym(spec, store)
    report = await build_gym_report(store, run)
    finalist = next(c for c in report.challengers if c.halved_at is None and spec.lines[c.side.label] == "toy_a")
    parents = await rnd.record(store, run)
    beat = (finalist.diff.mean_diff or 0) > 0
    assert parents["toy_a"] == (f"toy_a/v1/{finalist.side.label.removeprefix('toy_a-v1-')}" if beat else
                                "toy_a/v1/base")
    assert "`toy_a/v1/base` (the reference): 0" in (agents / "toy_a/JOURNAL.md").read_text()


async def test_listed_variants_also_configs_and_a_red_team_summary(world):
    """variants.txt picks what is measured; `also` configs join their line; a red-team run is summarised."""
    agents = world / "agents"
    (agents / "toy_a/v1/configs/later.yaml").write_text("extends: toy_a/v1/base\nparams: {step: 0.8}\n")
    (world / "configs/benches/adv.yaml").write_text(yaml.safe_dump({
        "purpose": "adversarial", "mode": "benchmark",
        "opponents": ["scripted:hardliner", {"kind": "scripted:hardliner", "name": "hardliner-plain"}],
        "twins": {"hardliner-plain": "scripted:hardliner"}, "scenarios": {"per_cell": 2, "max_rounds": [4]},
        "protocol": "structured", "detector": "structured", "reader": "rules", "sim_clock": True, "seed": 2}))
    store = await Store.open(world / "db")
    dev, _ = await run_gym(GymSpec.model_validate({"name": "r0", "bench": "toy", "reference": "boulware",
                                                   "challengers": ["toy_a/v1/base"]}), store)
    adv, _ = await run_gym(GymSpec.model_validate({"name": "rt", "bench": "adv", "reference": "boulware",
                                                   "challengers": ["toy_a/v1/base", "toy_a/v1/later"]}), store)
    with pytest.raises(ValueError, match="not an adversarial"):
        await rnd.export(store, dev, ["toy_a/v1/base"], world / "r1", redteam=dev)
    [ws] = await rnd.export(store, dev, ["toy_a/v1/base"], world / "round", also=["toy_a/v1/later"], redteam=adv)
    assert "`toy_a/v1/later`" in (ws / "README.md").read_text() and "redteam.md" in (ws / "README.md").read_text()
    summary = (ws / "data/redteam.md").read_text()
    assert "## toy_a-v1-base" in summary and "## toy_a-v1-later" in summary
    assert "What each attack costs you" in summary and "**scripted:hardliner**" in summary
    assert "**hardliner-plain**" not in summary                     # excerpts only against attacks

    for name in ("one", "two", "three", "four", "unlisted"):
        (ws / f"agents/toy_a/v1/configs/{name}.yaml").write_text("extends: toy_a/v1/base\nparams: {step: 0.6}\n")
    (ws / "variants.txt").write_text("toy_a/v1/two\ntoy_a/v1/one\ntoy_a/v1/three\ntoy_a/v1/four\ntoy_a/v1/nope\n")
    got = await rnd.collect(ws)
    assert got.line.variants == ["toy_a/v1/later", "toy_a/v1/two", "toy_a/v1/one", "toy_a/v1/three"]
    assert any("nope" in r for r in got.rejected) and any("four" in r for r in got.rejected)
    assert not (agents / "toy_a/v1/configs/unlisted.yaml").exists()
    path = rnd.write_round("round-02", [got.line], reference="boulware", bench="toy")
    assert yaml.safe_load(path.read_text())["early_stop"] is True
