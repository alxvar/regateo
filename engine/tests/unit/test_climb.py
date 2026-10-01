"""The climb loop's pieces: mining a run's failures, and validating and writing proposals."""
import shutil

import pytest

from regateo.agents import AgentSpec
from regateo.climb import propose as prop
from regateo.climb.mine import mine
from regateo.climb.propose import PromptEdit, Proposal, Proposals, ask, validate, write, write_experiment
from regateo.core.config import REPO_DIR
from regateo.gym import GymSpec, run_gym
from regateo.llm.providers.fake import FakeProvider
from regateo.storage import Store

REAL = REPO_DIR / "agents" / "single_call"
V1 = (REAL / "v1" / "prompts" / "negotiator_system.v1.md").read_text()


@pytest.fixture
def configs(tmp_path, monkeypatch):
    """A copy of the single_call architecture with one config, `single_call/v1/base` (plain O1 on Qwen)."""
    (tmp_path / "gym").mkdir()
    (tmp_path / "benches").mkdir()
    arch = tmp_path / "agents" / "single_call"
    shutil.copytree(REAL, arch, ignore=shutil.ignore_patterns("configs", "tests", "__pycache__"))
    (arch / "v1" / "configs").mkdir()
    (arch / "v1" / "configs" / "base.yaml").write_text("model: qwen-local\n")
    (tmp_path / "docs" / "experiments").mkdir(parents=True)
    (tmp_path / "docs" / "experiments" / "007-old.md").write_text("x")
    monkeypatch.setenv("REGATEO_CONFIGS", str(tmp_path))
    monkeypatch.setenv("REGATEO_AGENTS", str(tmp_path / "agents"))
    monkeypatch.setenv("REGATEO_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(prop, "REPO_DIR", tmp_path)
    return tmp_path


def test_validate(configs):
    parent = AgentSpec.resolve("single_call/v1/base")
    ok = Proposal(name="firm", failure="f", hypothesis="h", fence=True)
    assert validate(ok, parent, set()) == []
    assert any("taken" in r for r in validate(ok, parent, {"firm"}))
    assert any("nothing" in r for r in validate(Proposal(name="idle", failure="f", hypothesis="h"), parent, set()))
    assert any("slug" in r for r in validate(ok.model_copy(update={"name": "Firm Close"}), parent, set()))
    assert any("already" in r for r in validate(ok.model_copy(update={"model": "qwen-local"}), parent, set()))
    missing = ok.model_copy(update={"prompt_edit": PromptEdit(find="$reservation", replace="your limit")})
    assert any("missing ['reservation']" in r for r in validate(missing, parent, set()))
    absent = ok.model_copy(update={"prompt_edit": PromptEdit(find="no such passage", replace="x")})
    assert any("occurs 0 times" in r for r in validate(absent, parent, set()))
    priced = ok.model_copy(update={"prompt_edit": PromptEdit(find="", replace="Never open below $150 or 20%.")})
    assert validate(priced, parent, set()) == []                # "$150" is escaped, not a placeholder
    assert any("levers are single_call's" in r for r in validate(ok, AgentSpec(kind="boulware"), set()))


def test_write(configs):
    written, rejected = write([
        Proposal(name="guard", failure="deals past limit", hypothesis="h1", checks="limit"),
        Proposal(name="close-early", failure="round-limit no-deals", hypothesis="h2",
                 prompt_edit=PromptEdit(find="", replace="Close early when their offer is within 5% of $1,000.")),
        Proposal(name="nothing", failure="f", hypothesis="h3"),
    ], "single_call/v1/base")
    assert [w.agent for w in written] == ["single_call/v1/guard", "single_call/v2/close-early"]
    assert rejected[0].proposal.name == "nothing"
    guard = AgentSpec.resolve("single_call/v1/guard")
    assert guard.kind == "single_call/v1" and guard.params == {"checks": "limit"} and guard.model == "qwen-local"
    # a prompt rewrite is a new version: a copy of the parent's with the new prompt next to the old ones
    early = AgentSpec.resolve("single_call/v2/close-early")
    assert early.kind == "single_call/v2" and early.params == {"prompt": "negotiator_system.v4"}
    assert written[1].prompt_file == "single_call/v2/prompts/negotiator_system.v4.md"
    v2 = configs / "agents" / "single_call" / "v2"
    new = (v2 / "prompts" / "negotiator_system.v4.md").read_text()
    assert new.startswith(V1.rstrip("\n")) and new.endswith("within 5% of $$1,000.\n")
    assert sorted(p.name for p in (v2 / "configs").iterdir()) == ["close-early.yaml"]
    assert "hypothesis: h2" in (v2 / "configs" / "close-early.yaml").read_text().lower()
    name = write_experiment(written, reference="single_call/v1/base", bench="standard-v1", source_run="run_x")
    assert name == "exp-008-climb"
    gym = GymSpec.model_validate({**__import__("yaml").safe_load((configs / "gym" / f"{name}.yaml").read_text()),
                                  "bench": None, "opponents": ["scripted:liar"]})
    assert gym.tier is None and gym.halving is not None and gym.early_stop is not None
    assert [s.label for s in [gym.a, *gym.extra]] == ["single_call-v1-guard", "single_call-v2-close-early"]
    assert "(pending)" in (configs / "docs" / "experiments" / "008-climb.md").read_text()


async def test_ask_uses_one_structured_call(configs):
    fake = FakeProvider([Proposals(proposals=[Proposal(name="firm", failure="f", hypothesis="h", fence=True)])])
    bundle_run = await _run(configs)
    bundle = await mine(bundle_run[0], bundle_run[1])
    out = await ask(fake, bundle, n=1)
    assert [p.name for p in out] == ["firm"] and len(fake.requests) == 1
    req = fake.requests[0]
    assert "exactly 1 challengers" in req.system and "Where it loses value" in req.messages[0].content


async def _run(configs, purpose="dev"):
    (configs / "benches" / "b.yaml").write_text(
        f"purpose: {purpose}\nopponents: [scripted:hardliner, scripted:liar]\n"
        "scenarios: {per_cell: 3, max_rounds: [4]}\nsim_clock: true\nseed: 1\n")
    store = await Store.open(configs / "db")
    spec = GymSpec.model_validate({"name": "t", "bench": "b", "reference": "boulware",
                                   "challengers": [{"kind": "scripted:pushover", "name": "soft"}]})
    run_id, _ = await run_gym(spec, store)
    return store, run_id


async def test_mine(configs):
    store, run_id = await _run(configs)
    b = await mine(store, run_id, worst=3)
    assert b.subject == "b" and b.agent["kind"] == "boulware" and b.prompts == {}
    assert len(b.transcripts) == 3 and {"scripted:hardliner", "scripted:liar"} <= set(b.summary.split())
    assert "Our walk-away price" in b.transcripts[0] and "Result:" in b.transcripts[0]
    assert "Mean regret" in b.summary
    # ranked by regret against the other subject, with its transcript next to the top ones
    soft = await mine(store, run_id, subject="a", worst=3)
    assert soft.transcripts[0].startswith("Regret ") and "What boulware did in the same pair" in soft.transcripts[0]
    md = b.markdown()
    assert "## Where it loses value" in md and "persona" not in md


async def test_holdout_runs_are_not_mined(configs):
    store, run_id = await _run(configs, purpose="holdout")
    with pytest.raises(ValueError, match="holdout"):
        await mine(store, run_id)


async def test_workspace_export_and_adopt(configs):
    import json

    import yaml

    from regateo.climb.workspace import adopt, export
    store, run_id = await _run(configs)
    ws = await export(store, [run_id], "single_call/v1/base", configs / "ws")
    assert [p.name for p in (ws / "agent" / "prompts").iterdir()] == ["negotiator_system.v1.md"]
    assert (ws / "agent" / "prompts" / "negotiator_system.v1.md").read_text() == V1
    assert not list(ws.rglob("persona_*")) and "single_call/v1/base" in (ws / "README.md").read_text()
    lines = (ws / "data" / run_id / "matches.jsonl").read_text().splitlines()
    m = json.loads(lines[0])
    assert {"our_limit", "their_limit", "messages", "result"} <= set(m) and m["agent"] in ("boulware", "soft")

    def cand(name, **data):
        (ws / "candidates" / name).mkdir()
        (ws / "candidates" / name / "candidate.yaml").write_text(yaml.safe_dump(
            {"failure": "f", "hypothesis": "h", **data}))
    cand("think-first", changes={"analysis": True})
    cand("rewrite", prompt="prompt.md")
    (ws / "candidates" / "rewrite" / "prompt.md").write_text(V1.replace("negotiating", "bargaining", 1)
                                                             + "Never open below USD 150.\n")
    cand("bad-lever", changes={"telepathy": True})
    written, rejected = adopt(ws)
    assert sorted(w.agent for w in written) == ["single_call/v1/think-first", "single_call/v2/rewrite"]
    assert [r.proposal.name for r in rejected] == ["bad-lever"] and "telepathy" in rejected[0].reasons[0]
    rewrite = next(w for w in written if w.agent == "single_call/v2/rewrite")
    assert "bargaining" in (configs / "agents" / rewrite.prompt_file).read_text()


async def test_workspace_refuses_holdout_runs(configs):
    from regateo.climb.workspace import export
    store, run_id = await _run(configs, purpose="holdout")
    with pytest.raises(ValueError, match="holdout"):
        await export(store, [run_id], "single_call/v1/base", configs / "ws")


def test_repeats_are_rejected(configs):
    from regateo.climb.propose import behaviour_key
    rule = PromptEdit(find="", replace="Close early when their offer is within 5% of your aim.")
    first, _ = write([Proposal(name="firm", failure="f", hypothesis="h", fence=True),
                      Proposal(name="close", failure="f", hypothesis="h", prompt_edit=rule)], "single_call/v1/base")
    known = {behaviour_key(AgentSpec.resolve(w.agent)): f"{w.agent} in exp-1 (run_x)" for w in first}
    # the same changes under other names; the prompt edit lands in a new file with the same text
    same = Proposal(name="firm-again", failure="f", hypothesis="h", fence=True)
    reworded = Proposal(name="close-again", failure="f", hypothesis="h", prompt_edit=rule)
    fresh = Proposal(name="digest", failure="f", hypothesis="h", state_digest=True)
    written, rejected = write([same, reworded, fresh, fresh.model_copy(update={"name": "digest-2"})],
                              "single_call/v1/base", known=known)
    assert [w.agent for w in written] == ["single_call/v1/digest"]
    reasons = {r.proposal.name: r.reasons[0] for r in rejected}
    assert "single_call/v1/firm in exp-1" in reasons["firm-again"]
    assert "single_call/v2/close in exp-1" in reasons["close-again"]
    assert "this batch" in reasons["digest-2"]
    assert not (configs / "agents" / "single_call" / "v1" / "configs" / "firm-again.yaml").exists()
    assert not (configs / "agents" / "single_call" / "v3").exists()     # the duplicate version is removed


def test_learnings_public_view_and_tried(configs, monkeypatch):
    from regateo.climb import learnings
    doc = configs / "docs" / "05-learnings.md"
    doc.write_text(
        "# 05\n\nIntro.\n\n## Internal section\n\n<!-- visibility: internal -->\n\nThe baseline is X.\n\n"
        "## Strategy\n\n**L1. Secret.**\n- Status: holds.\n- Visibility: internal.\n\n"
        "**L2. Shared.**\n- Status: holds.\n- Visibility: public.\n")
    monkeypatch.setattr(learnings, "REPO_DIR", configs)
    view = learnings.public_view(doc.read_text())
    assert "Intro." in view and "L2. Shared" in view
    assert "Secret" not in view and "baseline is X" not in view
    (configs / "agents" / "single_call" / "JOURNAL.md").write_text("# single_call: journal\n\nv1 tried.\n")
    (configs / "data" / "climb").mkdir(parents=True)
    (configs / "data" / "climb" / "log.jsonl").write_text(
        '{"agent": "single_call/v1/a", "hypothesis": "h-mine", "changes": {}, "result": "r"}\n'
        '{"agent": "pipeline/v1/b", "hypothesis": "h-other", "changes": {}, "result": "r"}\n')
    text = learnings.tried("single_call")
    assert "L2. Shared" in text and "v1 tried." in text and "h-mine" in text
    assert "Secret" not in text and "h-other" not in text
