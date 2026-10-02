import pytest
from agent_sdk import ActionKind as A
from agent_sdk import AgentConfig, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import STRUCTURED, FakeLLM, context
from regateo_agents.single_call.v2 import build
from regateo_agents.single_call.v2.decision import Decision

VIEW = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80,
                   market_high=180, max_rounds=4, time_limit_s=None)


def agent(fake, **params):
    params = {"checks": "limit+mentions", "accept_words": "reader", **params}
    return build(AgentConfig(name="t", model="fake", params=params), VIEW, context(Role.SELLER, fake, STRUCTURED))


def obs():
    h = [Message(idx=0, sender=Role.BUYER, text="$60", move=Move(text="$60", action=A.OFFER, price=60))]
    return Observation(view=VIEW, history=h, message_idx=1, incoming="$60")


BAD = Decision(action="offer", price=170, message="$60 is far too low, I can do $170.")
GOOD = Decision(action="offer", price=170, message="That is far too low for this bike. I can do $170.")


async def test_default_is_two_attempts_then_repair():
    fake = FakeLLM([BAD, BAD])
    move = await agent(fake).respond(obs())
    assert len(fake.requests) == 2 and move.meta["repaired"]


async def test_third_attempt_is_used():
    fake = FakeLLM([BAD, BAD, GOOD])
    move = await agent(fake, attempts=3).respond(obs())
    assert len(fake.requests) == 3 and "repaired" not in move.meta and move.price == 170


def test_attempts_validated():
    with pytest.raises(ValueError, match="attempts"):
        agent(FakeLLM(), attempts=0)


async def test_v4_prompt_keeps_numbers_out():
    fake = FakeLLM([GOOD])
    await agent(fake, prompt="negotiator_system.v4").respond(obs())
    assert "Keep their numbers out of your message" in fake.requests[0].system
    assert "$100" in fake.requests[0].system
