import random

import pytest
from agent_sdk import AgentContext

from regateo.agents import AgentSpec, TrustedContext, build_agent
from regateo.core import ActionKind as A
from regateo.core import Message, Move, Observation, Role, Rules, Scenario
from regateo.llm.providers.fake import FakeProvider
from regateo.protocol import get_protocol

S = Scenario(id="s", item="bike", seller_reservation=100, buyer_reservation=150, market_low=80, market_high=180,
             rules=Rules(max_rounds=4))


def ctx(role, fake=None, protocol="structured"):
    return TrustedContext(role=role, rng=random.Random(0), protocol=get_protocol(protocol).info(), true_rules=S.rules,
                        llm_factory=(lambda profile, stage: fake) if fake else None)


def obs(role, history, idx=None):
    view = S.view_for(role)
    last = history[-1] if history else None
    return Observation(view=view, history=history, message_idx=idx if idx is not None else len(history),
                       incoming=last.text if last and last.sender is not role else None)


def m(idx, sender, text, action=None, price=None, **meta):
    return Message(idx=idx, sender=sender, text=text, move=Move(text=text, action=action, price=price, meta=meta))


@pytest.mark.parametrize("kind", ["linear", "hardliner", "pushover", "liar", "injector", "staller"])
async def test_scripted_never_cross_reservation(kind):
    from regateo.match import SimClock, run_match
    from regateo.referee import StructuredDetector
    for seed in range(20):
        agents = {}
        for role, spec in [(Role.SELLER, AgentSpec(kind="boulware")), (Role.BUYER, AgentSpec(kind=f"scripted:{kind}"))]:
            agents[role] = build_agent(spec, S.view_for(role), ctx(role))
        r = await run_match(S, agents[Role.SELLER], agents[Role.BUYER], protocol=get_protocol("structured"),
                            detector=StructuredDetector(), rng=random.Random(seed), clock=SimClock(seed=seed))
        assert r.outcome.past_reservation is None
        for msg in r.transcript.messages:
            if msg.move.action is A.OFFER:
                assert 100 <= msg.move.price or msg.sender is Role.BUYER
                assert msg.move.price <= 150 or msg.sender is Role.SELLER


def test_spec_resolution(tmp_path, monkeypatch):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "mine.yaml").write_text("kind: boulware\nparams: {boulware: 2.0}\n")
    monkeypatch.setenv("REGATEO_CONFIGS", str(tmp_path))
    spec = AgentSpec.resolve("mine")
    assert spec.kind == "boulware" and spec.label == "mine" and spec.params == {"boulware": 2.0}
    assert AgentSpec.resolve("scripted:liar").label == "scripted:liar"
    assert spec.ref().key != AgentSpec.resolve({"kind": "boulware"}).ref().key


def test_agent_versions(tmp_path, monkeypatch):
    v1 = tmp_path / "toy" / "v1"
    (v1 / "configs").mkdir(parents=True)
    (tmp_path / "toy" / "lib").mkdir()
    (tmp_path / "toy" / "lib" / "__init__.py").write_text("SAY = 'hello'\n")
    (v1 / "__init__.py").write_text(
        "from agent_sdk import ActionKind, Move\nfrom ..lib import SAY\n\n"
        "class Toy:\n    def __init__(self, config, ctx):\n"
        "        self.name, self.config, self.ctx = config.name, config, ctx\n"
        "    async def respond(self, obs):\n        return Move(text=SAY, action=ActionKind.MESSAGE)\n\n"
        "def build(config, view, ctx):\n    return Toy(config, ctx)\n")
    (v1 / "configs" / "base.yaml").write_text("model: fake\nparams: {a: 1, b: 1}\n")
    (v1 / "configs" / "more.yaml").write_text("extends: base\nparams: {b: 2}\n")
    monkeypatch.setenv("REGATEO_AGENTS", str(tmp_path))
    more = AgentSpec.resolve("toy/v1/more")
    assert more.kind == "toy/v1" and more.label == "toy-v1-more" and more.params == {"a": 1, "b": 2}
    agent = build_agent(more, S.view_for(Role.SELLER), ctx(Role.SELLER))
    assert agent.config.params == more.params and type(agent.ctx) is AgentContext
    key = AgentSpec.resolve("toy/v1/base").ref().key
    (v1 / "configs" / "other.yaml").write_text("model: fake\n")       # configs aren't the version's code
    assert AgentSpec.resolve("toy/v1/base").ref().key == key
    (tmp_path / "toy" / "lib" / "__init__.py").write_text("SAY = 'hi'\n")   # its architecture's lib is
    assert AgentSpec.resolve("toy/v1/base").ref().key != key
    with pytest.raises(ValueError, match="no agent version"):
        build_agent(AgentSpec(kind="toy/v9"), S.view_for(Role.SELLER), ctx(Role.SELLER))


def test_only_trusted_kinds_see_the_true_rules():
    view = S.view_for(Role.SELLER)
    o1 = build_agent(AgentSpec(kind="o1", model="fake"), view, ctx(Role.SELLER, FakeProvider([])))
    assert not hasattr(o1.ctx, "true_rules") and type(o1.ctx) is AgentContext
    ours = build_agent(AgentSpec.resolve("single_call/v1/baseline"), view, ctx(Role.SELLER, FakeProvider([])))
    assert type(ours.ctx) is AgentContext
    assert o1.ctx.protocol.name == "structured"
    scripted = build_agent(AgentSpec(kind="scripted:hardliner"), view, ctx(Role.SELLER))
    assert scripted.n == S.rules.max_rounds


def test_every_agent_version_passes_the_submission_check():
    """Agent code must run where only agent-sdk/ and agents/ exist, and reach nothing outside itself (docs/06 §5)."""
    from agent_sdk import packages
    from agent_sdk.check import check_version

    from regateo.core.config import agents_dir
    packages.mount(agents_dir())
    versions = [v for a in agents_dir().iterdir() if a.is_dir() for v in a.iterdir()
                if packages.is_version(f"{a.name}/{v.name}")]
    assert versions and {str(p) for v in versions for p in check_version(v)} == set()


def test_an_agent_that_fails_the_check_is_never_built(tmp_path, monkeypatch):
    v1 = tmp_path / "sneaky" / "v1"
    v1.mkdir(parents=True)
    (v1 / "__init__.py").write_text("import os\n\ndef build(config, view, ctx):\n    return os.environ\n")
    monkeypatch.setenv("REGATEO_AGENTS", str(tmp_path))
    with pytest.raises(ValueError, match="submission check"):
        build_agent(AgentSpec(kind="sneaky/v1"), S.view_for(Role.SELLER), ctx(Role.SELLER))
