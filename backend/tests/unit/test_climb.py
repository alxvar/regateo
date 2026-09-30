"""The climb loop's pieces: mining a run's failures, and validating and writing proposals."""
import pytest

from regateo.agents import AgentSpec, prompts
from regateo.climb import propose as prop
from regateo.climb.mine import mine
from regateo.climb.propose import PromptEdit, Proposal, Proposals, ask, validate, write, write_experiment
from regateo.gym import GymSpec, run_gym
from regateo.llm.providers.fake import FakeProvider
from regateo.storage import Store

V1 = prompts.path("negotiator_system.v1").read_text()


@pytest.fixture
def configs(tmp_path, monkeypatch):
    (tmp_path / "agents" / "o1").mkdir(parents=True)
    (tmp_path / "gym").mkdir()
    (tmp_path / "benches").mkdir()
    (tmp_path / "agents" / "o1" / "base.yaml").write_text("kind: o1\nmodel: qwen-local\n")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "negotiator_system.v1.md").write_text(V1)
    (tmp_path / "prompts" / "proposer_system.v1.md").write_text(prompts.path("proposer_system.v1").read_text())
    (tmp_path / "docs" / "experiments").mkdir(parents=True)
    (tmp_path / "docs" / "experiments" / "007-old.md").write_text("x")
    monkeypatch.setenv("REGATEO_CONFIGS", str(tmp_path))
    monkeypatch.setenv("REGATEO_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(prompts, "_DIR", tmp_path / "prompts")
    monkeypatch.setattr(prop, "REPO_DIR", tmp_path)
    return tmp_path


def test_validate(configs):
    parent = AgentSpec.resolve("o1/base")
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


def test_write(configs):
    written, rejected = write([
        Proposal(name="guard", failure="deals past limit", hypothesis="h1", checks="limit"),
        Proposal(name="close-early", failure="round-limit no-deals", hypothesis="h2",
                 prompt_edit=PromptEdit(find="", replace="Close early when their offer is within 5% of $1,000.")),
        Proposal(name="nothing", failure="f", hypothesis="h3"),
    ], "o1/base")
    assert [w.agent for w in written] == ["o2/guard", "o1/close-early"] and rejected[0].proposal.name == "nothing"
    guard = AgentSpec.resolve("o2/guard")
    assert guard.kind == "o2" and guard.params == {"checks": "limit"}
    early = AgentSpec.resolve("o1/close-early")
    assert early.params == {"prompt": "negotiator_system.v2"} and written[1].prompt_file == "negotiator_system.v2.md"
    v2 = (configs / "prompts" / "negotiator_system.v2.md").read_text()
    assert v2.startswith(V1.rstrip("\n")) and v2.endswith("within 5% of $$1,000.\n")
    assert "hypothesis: h2" in (configs / "agents" / "o1" / "close-early.yaml").read_text().lower()
    name = write_experiment(written, reference="o1/base", bench="standard-v1", source_run="run_x")
    assert name == "exp-008-climb"
    gym = GymSpec.model_validate({**__import__("yaml").safe_load((configs / "gym" / f"{name}.yaml").read_text()),
                                  "bench": None, "opponents": ["scripted:liar"]})
    assert gym.tier is None and gym.halving is not None and gym.early_stop is not None
    assert [s.label for s in [gym.a, *gym.extra]] == ["o2-guard", "o1-close-early"]
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
