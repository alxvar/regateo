import pytest
from agent_sdk import ActionKind as A
from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.ranged.lib.common import Decision
from regateo_agents.ranged.v1 import build
from regateo_agents.ranged.v1.agent import BandPlan, make_band

VIEWS = {role: PrivateView(role=role, item="bike", currency="USD", reservation=100 if role is Role.SELLER else 150,
                           market_low=80, market_high=180, max_rounds=4, time_limit_s=None) for role in Role}
HISTORY = [Message(idx=0, sender=Role.BUYER, text="I can do $110.", move=Move(text="I can do $110."))]
PLAN = BandPlan(read="They opened low.", target=165, best=175, worst=155, angle="Stress the new tyres.")


def agent(fake, role=Role.SELLER, **params):
    return build(AgentConfig(name="t", model="fake", params=params), VIEWS[role], context(role, fake))


def obs(role, history=HISTORY):
    return Observation(view=VIEWS[role], history=history, message_idx=len(history),
                       incoming=history[-1].text if history else None)


def by_stage(plan, *decisions):
    queue = list(decisions)
    return FakeLLM(lambda req: plan if req.tags["stage"] == "strategist" else queue.pop(0))


def test_bands_by_width():
    v = VIEWS[Role.SELLER]
    assert make_band(v, PLAN, "strategist") == make_band(v, PLAN.model_copy(update={"best": 155, "worst": 175}),
                                                         "strategist")
    b = make_band(v, PLAN, "strategist")
    assert (b.worst, b.target, b.best) == (155, 165, 175)
    assert make_band(v, PLAN, 0).best == make_band(v, PLAN, 0).worst == 165
    w = make_band(v, PLAN, 0.1)
    assert (w.worst, w.best) == (160, 170)                  # 10% of the $100 market range around $165
    full = make_band(v, PLAN, "full")
    assert (full.worst, full.best) == (100, None)
    past = make_band(v, PLAN.model_copy(update={"target": 95, "worst": 90, "best": 120}), "strategist")
    assert past.worst == 100 and past.target == 100          # never past the walk-away price
    buyer = make_band(VIEWS[Role.BUYER], BandPlan(read="", target=120, best=100, worst=160, angle=""), "strategist")
    assert (buyer.worst, buyer.target, buyer.best) == (150, 120, 100)


async def test_negotiator_never_sees_the_limit():
    fake = by_stage(PLAN, Decision(action="offer", price=170, message="I can do $170."))
    move = await agent(fake).respond(obs(Role.SELLER))
    strategist, negotiator = fake.requests
    assert "$100" in strategist.system and "$100" not in negotiator.system
    assert "Offer between $155 and $175; aim for about $165." in negotiator.messages[-1].content
    assert "> I can do $110." in strategist.messages[0].content
    assert move.price == 170 and move.meta["band"] == {"worst": 155, "target": 165, "best": 175}
    seen = by_stage(PLAN, Decision(action="offer", price=170, message="I can do $170."))
    await agent(seen, negotiator_sees_limit=True).respond(obs(Role.SELLER))
    assert "$100" in seen.requests[1].system


async def test_holds_offers_to_the_band_then_repairs():
    out = Decision(action="offer", price=140, message="How about $140?")
    fake = by_stage(PLAN, out, out)
    move = await agent(fake).respond(obs(Role.SELLER))
    assert "outside the band for this turn ($155 to $175)" in fake.requests[2].messages[-1].content
    assert move.meta["repaired"] and move.price == 155 and move.text == "I can do $155."


async def test_accept_only_within_the_band():
    fake = by_stage(PLAN, Decision(action="accept", price=110, message="Deal."),
                    Decision(action="offer", price=160, message="I can do $160."))
    move = await agent(fake).respond(obs(Role.SELLER))
    assert "only accept an offer of $155 or better" in fake.requests[2].messages[-1].content and move.price == 160


async def test_mentions_past_the_limit_are_vetoed_without_naming_it():
    fake = by_stage(PLAN, Decision(action="offer", price=160, message="$90 is absurd. $160."),
                    Decision(action="offer", price=160, message="I can do $160."))
    await agent(fake).respond(obs(Role.SELLER))
    feedback = fake.requests[2].messages[-1].content
    assert "mentions $90" in feedback and "walk-away" not in feedback


async def test_strategist_past_the_limit_is_asked_again():
    bad = PLAN.model_copy(update={"target": 95, "worst": 90})
    plans = [bad, PLAN]
    fake = FakeLLM(lambda req: plans.pop(0) if req.tags["stage"] == "strategist" else
                   Decision(action="offer", price=165, message="I can do $165."))
    move = await agent(fake).respond(obs(Role.SELLER))
    assert "past your walk-away price" in fake.requests[1].messages[0].content and move.price == 165


async def test_falls_back_on_model_error():
    move = await agent(FakeLLM([LLMTimeout()])).respond(obs(Role.SELLER, []))
    assert move.action is A.OFFER and move.price == 180 and "fallback" in move.meta


def test_rejects_unknown_settings():
    with pytest.raises(ValueError, match="unknown width"):
        agent(FakeLLM(), width="wide")
    with pytest.raises(ValueError, match="unknown params"):
        agent(FakeLLM(), band=True)
