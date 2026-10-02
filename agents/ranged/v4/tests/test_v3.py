"""v3's tests, run on v4 with its new switches (`clock`, `plain_final`) off: v4 then behaves as v3, but for the
ledger's direction of their movement (test_v4.py)."""
import pytest
from agent_sdk import ActionKind as A
from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.ranged.lib.common import Decision
from regateo_agents.ranged.v4 import build
from regateo_agents.ranged.v4.agent import BandPlan, ledger, make_band
from regateo_agents.ranged.v4.offers import their_floor

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
    b = make_band(v, PLAN, "strategist")
    assert (b.worst, b.target, b.best) == (155, 165, 175)
    w = make_band(v, PLAN, 0.1)
    assert (w.worst, w.best) == (160, 170)
    past = make_band(v, PLAN.model_copy(update={"target": 95, "worst": 90, "best": 120}), "strategist")
    assert past.worst == 100 and past.target == 100          # never past the walk-away price


def test_ledger_states_facts_only():
    history = [
        Message(idx=0, sender=Role.BUYER, text="$90.", move=Move(text="$90.", action=A.OFFER, price=90)),
        Message(idx=1, sender=Role.SELLER, text="$170.", move=Move(text="$170.", action=A.OFFER, price=170)),
        Message(idx=2, sender=Role.BUYER, text="$90.", move=Move(text="$90.", action=A.OFFER, price=90)),
    ]
    text = ledger(VIEWS[Role.SELLER], obs(Role.SELLER, history))
    assert "Your offers so far: $170" in text and "Their offers so far" in text and "$90, $90" in text
    assert "They have moved $0 from their first offer." in text
    assert "Messages left for your side, including the next one: 3 of 4." in text
    assert "$100" not in text                                # no walk-away price in the facts


async def test_strategist_sees_ledger_and_negotiator_never_sees_the_limit():
    fake = by_stage(PLAN, Decision(action="offer", price=170, message="I can do $170."))
    move = await agent(fake).respond(obs(Role.SELLER))
    strategist, negotiator = fake.requests
    assert "Facts from your own system" in strategist.messages[0].content
    assert "$100" in strategist.system and "$100" not in negotiator.system
    assert "Offer between $155 and $175; aim for about $165." in negotiator.messages[-1].content
    assert move.price == 170


async def test_hold_false_is_v1_strategist():
    fake = by_stage(PLAN, Decision(action="offer", price=170, message="I can do $170."))
    await agent(fake, hold=False).respond(obs(Role.SELLER))
    assert "Facts from your own system" not in fake.requests[0].messages[0].content


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


async def test_falls_back_on_model_error():
    move = await agent(FakeLLM([LLMTimeout()])).respond(obs(Role.SELLER, []))
    assert move.action is A.OFFER and move.price == 180 and "fallback" in move.meta


def test_rejects_unknown_settings():
    with pytest.raises(ValueError, match="unknown width"):
        agent(FakeLLM(), width="wide")
    with pytest.raises(ValueError, match="unknown params"):
        agent(FakeLLM(), band=True)


BID = [Message(idx=0, sender=Role.BUYER, text="Another seller wants $190, but I can pay $170.",
               move=Move(text="Another seller wants $190, but I can pay $170."))]


async def test_standing_vetoes_offers_worse_than_theirs():
    fake = by_stage(PLAN, Decision(action="offer", price=160, message="I can do $160."),
                    Decision(action="accept", price=170, message="Deal at $170."))
    move = await agent(fake, standing=True).respond(obs(Role.SELLER, BID))
    assert "their latest offer, $170, is already better for you than your offer of $160" in \
        fake.requests[2].messages[-1].content
    assert move.action is A.ACCEPT and move.price == 170


async def test_standing_is_off_by_default():
    fake = by_stage(PLAN, Decision(action="offer", price=160, message="I can do $160."))
    move = await agent(fake).respond(obs(Role.SELLER, BID))
    assert move.action is A.OFFER and move.price == 160 and "vetoes" not in move.meta


def test_their_floor_ignores_quotes_of_ours():
    ours = Message(idx=1, sender=Role.SELLER, text="I can do $175.",
                   move=Move(text="I can do $175.", meta={"intent": {"action": "offer", "price": 175}}))
    quote = Message(idx=2, sender=Role.BUYER, text="$175? Too much.", move=Move(text="$175? Too much."))
    assert their_floor(obs(Role.SELLER, BID)) == 170
    assert their_floor(obs(Role.SELLER, [*BID, ours, quote])) == 170
