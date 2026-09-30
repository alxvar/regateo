import random

import pytest

from regateo.agents import AgentContext, AgentSpec, build_agent
from regateo.agents.baselines.o1 import AnalysisFirst, Decision
from regateo.agents.baselines.o2 import check
from regateo.core import ActionKind as A
from regateo.core import Message, Move, Observation, Role, Rules, Scenario
from regateo.llm.errors import LLMTimeout
from regateo.llm.providers.fake import FakeProvider
from regateo.protocol import get_protocol

S = Scenario(id="s", item="bike", seller_reservation=100, buyer_reservation=150, market_low=80, market_high=180,
             rules=Rules(max_rounds=4))


def ctx(role, fake=None, protocol="structured"):
    return AgentContext(role=role, rng=random.Random(0), protocol=get_protocol(protocol), true_rules=S.rules,
                        llm_factory=(lambda profile, stage: fake) if fake else None)


def obs(role, history, idx=None):
    view = S.view_for(role)
    last = history[-1] if history else None
    return Observation(view=view, history=history, message_idx=idx if idx is not None else len(history),
                       incoming=last.text if last and last.sender is not role else None)


def m(idx, sender, text, action=None, price=None, **meta):
    return Message(idx=idx, sender=sender, text=text, move=Move(text=text, action=action, price=price, meta=meta))


async def test_o1_prompt_hides_nothing_it_shouldnt_and_maps_turns():
    fake = FakeProvider([Decision(action="offer", price=170, message="I'd like $170.")])
    agent = build_agent(AgentSpec(kind="o1", model="fake"), S.view_for(Role.SELLER), ctx(Role.SELLER, fake))
    move = await agent.respond(obs(Role.SELLER, []))
    assert move.price == 170 and move.meta["decision"]["price"] == 170
    req = fake.requests[0]
    assert "$100" in req.system and "$150" not in req.system          # own reservation only
    assert [c.role for c in req.messages] == ["user"]


async def test_o1_analysis_is_written_first_and_kept_private():
    fake = FakeProvider([AnalysisFirst(analysis="They opened low; hold at $170.", action="offer", price=170,
                                       message="I'd like $170."),
                         AnalysisFirst(analysis="Still far apart.", action="offer", price=165, message="$165 then.")])
    agent = build_agent(AgentSpec(kind="o1", model="fake", params={"analysis": True}), S.view_for(Role.SELLER),
                        ctx(Role.SELLER, fake, "freetext"))
    move = await agent.respond(obs(Role.SELLER, []))
    assert move.price == 170 and move.meta["decision"]["analysis"].startswith("They opened")
    assert "hold" not in move.text                                      # the analysis is never sent
    req = fake.requests[0]
    assert req.output_schema is AnalysisFirst and list(AnalysisFirst.model_fields)[0] == "analysis"
    assert '"analysis" field' in req.system
    history = [Message(idx=0, sender=Role.SELLER, text=move.text, move=move), m(1, Role.BUYER, "How about $120?")]
    await agent.respond(obs(Role.SELLER, history))
    assert "hold" not in fake.requests[1].messages[1].content           # not replayed to the model either


async def test_o1_state_digest():
    fake = FakeProvider([Decision(action="offer", price=150, message="$150")])
    agent = build_agent(AgentSpec(kind="o1", model="fake", params={"state_digest": True}), S.view_for(Role.SELLER),
                        ctx(Role.SELLER, fake, "freetext"))
    history = [m(0, Role.SELLER, "I'm asking $170.", A.OFFER, 170),
               m(1, Role.BUYER, "$170 is too high. I can do $110."),
               m(2, Role.SELLER, "I can come down to $160.", A.OFFER, 160),
               m(3, Role.BUYER, "OK, I'll go to $125.")]
    await agent.respond(obs(Role.SELLER, history))
    turn = fake.requests[0].messages[-1].content
    assert turn.startswith("[message 4] OK, I'll go to $125.")
    digest = turn.split("\n\n", 1)[1]
    assert "Your offers so far: $170 -> $160" in digest
    assert "Their offers so far: $110 -> $125" in digest                # the quoted $170 is not their offer
    assert "they moved $15 toward you; you moved $10 toward them" in digest
    assert "$125 is $25 better than your walk-away price" in digest
    assert "Gap between your latest offer and theirs: $35" in digest
    assert "messages left, including this one: 2 of 4" in digest
    plain = FakeProvider([Decision(action="offer", price=150, message="$150")])
    await build_agent(AgentSpec(kind="o1", model="fake"), S.view_for(Role.SELLER),
                      ctx(Role.SELLER, plain, "freetext")).respond(obs(Role.SELLER, history))
    assert plain.requests[0].messages[-1].content == "[message 4] OK, I'll go to $125."   # off by default


async def test_o1_falls_back_on_model_error():
    agent = build_agent(AgentSpec(kind="o1", model="fake"), S.view_for(Role.SELLER),
                        ctx(Role.SELLER, FakeProvider([LLMTimeout()])))
    move = await agent.respond(obs(Role.SELLER, []))
    assert move.action is A.OFFER and move.price == 180 and "fallback" in move.meta


def test_o2_checks():
    h = [m(0, Role.BUYER, "$120", A.OFFER, 120), m(1, Role.SELLER, "$170", A.OFFER, 170),
         m(2, Role.BUYER, "$130", A.OFFER, 130)]
    o = obs(Role.SELLER, h)
    assert check(Decision(action="offer", price=160, message="I can do $160."), o) == []
    assert any("walk-away" in p for p in check(Decision(action="offer", price=90, message="$90"), o))
    assert any("walk an offer back" in p for p in check(Decision(action="offer", price=175, message="$175"), o))
    leak = Decision(action="offer", price=160, message="$160, I can't go below $100")
    assert any("reveals" in p for p in check(leak, o))
    assert any("exact price" in p for p in check(Decision(action="accept", price=140, message="Deal at $140"), o))
    assert check(Decision(action="accept", price=None, message="Deal at $130."), o) == []
    assert any("must state" in p for p in check(Decision(action="offer", price=160, message="Lower it is."), o))


def test_o2_limit_checks():
    h = [m(0, Role.BUYER, "$120", A.OFFER, 120), m(1, Role.SELLER, "$170", A.OFFER, 170),
         m(2, Role.BUYER, "$95", A.OFFER, 95)]
    o = obs(Role.SELLER, h)
    walk_back = Decision(action="offer", price=175, message="Actually, $175, and I won't go below $100.")
    assert check(walk_back, o, "limit") == []                       # only the limit counts
    assert any("walk-away" in p for p in check(Decision(action="offer", price=90, message="$90"), o, "limit"))
    assert any("walk-away" in p for p in check(Decision(action="accept", price=None, message="Deal."), o, "limit"))
    assert check(Decision(action="accept", price=None, message="Deal."), obs(Role.SELLER, h[:1]), "limit") == []
    # the decision names a price inside the limit, but their standing offer ($95, as read) is past it (exp-004)
    assert any("walk-away" in p for p in check(Decision(action="accept", price=132, message="Deal."), o, "limit"))
    no = Decision(action="reject", message="$95 is far too low. $170 is fair for this bike.")
    assert check(no, o, "limit") == []
    assert any("$95" in p for p in check(no, o, "limit+mentions"))
    assert check(Decision(action="offer", price=160, message="$160 for 2 bikes? No: $160 each."), o,
                 "limit+mentions") == []


def test_o2_accept_word_check():
    from regateo.agents.baselines.o2 import accept_word_check
    chat = Decision(action="offer", price=150, message="Take your time, ready to ship the moment we agree. $150.")
    solid = Decision(action="offer", price=150, message="At $150 I'm confident it's a solid deal for the right person.")
    refuse = Decision(action="reject", price=None, message="I can't accept that.")
    assert accept_word_check(chat, "reader") and accept_word_check(solid, "reader")
    assert accept_word_check(refuse, "reader") == [] and accept_word_check(refuse, "strict")
    assert accept_word_check(Decision(action="accept", price=None, message="Deal, agreed."), "strict") == []
    assert accept_word_check(Decision(action="offer", price=150, message="I can do $150."), "strict") == []


def test_o2_rejects_unknown_checks():
    with pytest.raises(ValueError, match="unknown checks"):
        build_agent(AgentSpec(kind="o2", model="fake", params={"checks": "some"}), S.view_for(Role.SELLER),
                    ctx(Role.SELLER, FakeProvider([])))


async def test_o2_retries_then_repairs():
    bad = Decision(action="offer", price=90, message="Fine, $90.")
    fake = FakeProvider([bad, bad])
    agent = build_agent(AgentSpec(kind="o2", model="fake"), S.view_for(Role.SELLER), ctx(Role.SELLER, fake))
    move = await agent.respond(obs(Role.SELLER, [m(0, Role.BUYER, "$90", A.OFFER, 90)]))
    assert len(fake.requests) == 2 and "past your walk-away" in fake.requests[1].messages[-1].content
    assert move.meta["repaired"] and move.price == 100 and "$100" in move.text


async def test_o2_passes_good_decision_after_retry():
    fake = FakeProvider([Decision(action="offer", price=90, message="$90"),
                         Decision(action="offer", price=140, message="How about $140?")])
    agent = build_agent(AgentSpec(kind="o2", model="fake"), S.view_for(Role.SELLER), ctx(Role.SELLER, fake))
    move = await agent.respond(obs(Role.SELLER, [m(0, Role.BUYER, "$90", A.OFFER, 90)]))
    assert move.price == 140 and move.meta["vetoes"] and "repaired" not in move.meta


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
    (tmp_path / "agents" / "mine.yaml").write_text("kind: o2\nmodel: qwen-local\nparams: {fence: true}\n")
    monkeypatch.setenv("REGATEO_CONFIGS", str(tmp_path))
    spec = AgentSpec.resolve("mine")
    assert spec.kind == "o2" and spec.label == "mine" and spec.params == {"fence": True}
    assert AgentSpec.resolve("scripted:liar").label == "scripted:liar"
    assert spec.ref().key != AgentSpec.resolve({"kind": "o2", "model": "qwen-local"}).ref().key


def test_o2_ignores_non_price_numbers():
    o = obs(Role.SELLER, [m(0, Role.BUYER, "$120", A.OFFER, 120)])
    assert check(Decision(action="offer", price=160, message="I can do $160 if you pick up within 2 days."), o) == []
