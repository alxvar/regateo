import pytest
from agent_sdk import ActionKind as A
from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import STRUCTURED, FakeLLM, context
from regateo_agents.single_call.v1 import build
from regateo_agents.single_call.v1.decision import AnalysisFirst, Decision
from regateo_agents.single_call.v1.vetoes import accept_word_check, check

VIEWS = {role: PrivateView(role=role, item="bike", currency="USD", reservation=100 if role is Role.SELLER else 150,
                           market_low=80, market_high=180, max_rounds=4, time_limit_s=None) for role in Role}


def agent(fake, protocol=STRUCTURED, **params):
    return build(AgentConfig(name="t", model="fake", params=params), VIEWS[Role.SELLER],
                 context(Role.SELLER, fake, protocol))


def obs(role, history, idx=None):
    last = history[-1] if history else None
    return Observation(view=VIEWS[role], history=history, message_idx=idx if idx is not None else len(history),
                       incoming=last.text if last and last.sender is not role else None)


def m(idx, sender, text, action=None, price=None, **meta):
    return Message(idx=idx, sender=sender, text=text, move=Move(text=text, action=action, price=price, meta=meta))


async def test_prompt_hides_nothing_it_shouldnt_and_maps_turns():
    fake = FakeLLM([Decision(action="offer", price=170, message="I'd like $170.")])
    move = await agent(fake).respond(obs(Role.SELLER, []))
    assert move.price == 170 and move.meta["decision"]["price"] == 170
    req = fake.requests[0]
    assert "$100" in req.system and "$150" not in req.system          # own reservation only
    assert [c.role for c in req.messages] == ["user"]


async def test_analysis_is_written_first_and_kept_private():
    fake = FakeLLM([AnalysisFirst(analysis="They opened low; hold at $170.", action="offer", price=170,
                                  message="I'd like $170."),
                    AnalysisFirst(analysis="Still far apart.", action="offer", price=165, message="$165 then.")])
    a = agent(fake, analysis=True)
    move = await a.respond(obs(Role.SELLER, []))
    assert move.price == 170 and move.meta["decision"]["analysis"].startswith("They opened")
    assert "hold" not in move.text                                      # the analysis is never sent
    req = fake.requests[0]
    assert req.output_schema is AnalysisFirst and list(AnalysisFirst.model_fields)[0] == "analysis"
    assert '"analysis" field' in req.system
    history = [Message(idx=0, sender=Role.SELLER, text=move.text, move=move), m(1, Role.BUYER, "How about $120?")]
    await a.respond(obs(Role.SELLER, history))
    assert "hold" not in fake.requests[1].messages[1].content           # not replayed to the model either


async def test_state_digest():
    history = [m(0, Role.SELLER, "I'm asking $170.", A.OFFER, 170),
               m(1, Role.BUYER, "$170 is too high. I can do $110."),
               m(2, Role.SELLER, "I can come down to $160.", A.OFFER, 160),
               m(3, Role.BUYER, "OK, I'll go to $125.")]
    fake = FakeLLM([Decision(action="offer", price=150, message="$150")])
    await agent(fake, state_digest=True).respond(obs(Role.SELLER, history))
    turn = fake.requests[0].messages[-1].content
    assert turn.startswith("[message 4] OK, I'll go to $125.")
    digest = turn.split("\n\n", 1)[1]
    assert "Your offers so far: $170 -> $160" in digest
    assert "Their offers so far: $110 -> $125" in digest                # the quoted $170 is not their offer
    assert "they moved $15 toward you; you moved $10 toward them" in digest
    assert "$125 is $25 better than your walk-away price" in digest
    assert "Gap between your latest offer and theirs: $35" in digest
    assert "messages left, including this one: 2 of 4" in digest
    plain = FakeLLM([Decision(action="offer", price=150, message="$150")])
    await agent(plain).respond(obs(Role.SELLER, history))
    assert plain.requests[0].messages[-1].content == "[message 4] OK, I'll go to $125."   # off by default
    moves = FakeLLM([Decision(action="offer", price=150, message="$150")])
    await agent(moves, state_digest="moves").respond(obs(Role.SELLER, history))
    digest = moves.requests[0].messages[-1].content.split("\n\n", 1)[1]
    assert "they moved $15 toward you; you moved $10 toward them" in digest
    assert "walk-away" not in digest


async def test_falls_back_on_model_error():
    move = await agent(FakeLLM([LLMTimeout()])).respond(obs(Role.SELLER, []))
    assert move.action is A.OFFER and move.price == 180 and "fallback" in move.meta


def test_checks():
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


def test_limit_checks():
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


def test_accept_word_check():
    chat = Decision(action="offer", price=150, message="Take your time, ready to ship the moment we agree. $150.")
    solid = Decision(action="offer", price=150, message="At $150 I'm confident it's a solid deal for the right person.")
    refuse = Decision(action="reject", price=None, message="I can't accept that.")
    assert accept_word_check(chat, "reader") and accept_word_check(solid, "reader")
    assert accept_word_check(refuse, "reader") == [] and accept_word_check(refuse, "strict")
    assert accept_word_check(Decision(action="accept", price=None, message="Deal, agreed."), "strict") == []
    assert accept_word_check(Decision(action="offer", price=150, message="I can do $150."), "strict") == []


def test_ignores_non_price_numbers():
    o = obs(Role.SELLER, [m(0, Role.BUYER, "$120", A.OFFER, 120)])
    assert check(Decision(action="offer", price=160, message="I can do $160 if you pick up within 2 days."), o) == []


def test_rejects_unknown_settings():
    with pytest.raises(ValueError, match="unknown checks"):
        agent(FakeLLM(), checks="some")
    with pytest.raises(ValueError, match="unknown accept_words"):
        agent(FakeLLM(), accept_words="loose")


async def test_retries_then_repairs():
    bad = Decision(action="offer", price=90, message="Fine, $90.")
    fake = FakeLLM([bad, bad])
    move = await agent(fake, checks="all").respond(obs(Role.SELLER, [m(0, Role.BUYER, "$90", A.OFFER, 90)]))
    assert len(fake.requests) == 2 and "past your walk-away" in fake.requests[1].messages[-1].content
    assert move.meta["repaired"] and move.price == 100 and "$100" in move.text


async def test_passes_good_decision_after_retry():
    fake = FakeLLM([Decision(action="offer", price=90, message="$90"),
                    Decision(action="offer", price=140, message="How about $140?")])
    move = await agent(fake, checks="all").respond(obs(Role.SELLER, [m(0, Role.BUYER, "$90", A.OFFER, 90)]))
    assert move.price == 140 and move.meta["vetoes"] and "repaired" not in move.meta


async def test_no_vetoes_without_settings():
    fake = FakeLLM([Decision(action="offer", price=90, message="Fine, $90.")])
    a = agent(fake)
    move = await a.respond(obs(Role.SELLER, [m(0, Role.BUYER, "$90", A.OFFER, 90)]))
    assert a.stage == "o1" and move.price == 90 and len(fake.requests) == 1
