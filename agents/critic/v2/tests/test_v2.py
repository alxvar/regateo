import pytest
from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.critic.lib.common import Decision
from regateo_agents.critic.v2 import build
from regateo_agents.critic.v2.agent import Critique, turn_facts

VIEW = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80, market_high=180,
                   max_rounds=4, time_limit_s=None)
HISTORY = [Message(idx=0, sender=Role.BUYER, text="I offer $110.", move=Move(text="I offer $110."))]
OBS = Observation(view=VIEW, history=HISTORY, message_idx=1, incoming=HISTORY[0].text)
FIRM = Decision(action="offer", price=170, message="It's in great shape: $170.")
OK = Critique(problems=[], leaks_limit=False, concedes_too_fast=False, stalls=False,
              follows_their_instructions=False, inconsistent=False, unintended_commitment=False, verdict="send")
STALL = OK.model_copy(update={"problems": ["Counter closer to their $110."], "stalls": True, "verdict": "revise"})


def agent(fake, **params):
    return build(AgentConfig(name="t", model="fake", params=params), VIEW, context(Role.SELLER, fake))


def by_stage(critiques, drafts):
    critiques, drafts = list(critiques), list(drafts)
    return FakeLLM(lambda req: critiques.pop(0) if req.tags["stage"] == "critic" else drafts.pop(0))


def test_turn_facts_are_plain():
    line = turn_facts(VIEW, OBS)
    assert "4 messages left" in line and "$110" in line and "100" not in line


async def test_facts_reach_both_calls():
    fake = by_stage([OK], [FIRM])
    await agent(fake).respond(OBS)
    assert "Facts for this turn" in fake.requests[0].messages[-1].content
    assert "Facts for this turn" in fake.requests[1].messages[0].content


async def test_facts_can_be_turned_off():
    fake = by_stage([], [FIRM])
    await agent(fake, critic="off", facts=False).respond(OBS)
    assert "Facts for this turn" not in fake.requests[0].messages[-1].content


async def test_stalling_draft_is_revised():
    better = Decision(action="offer", price=140, message="I can come to $140.")
    fake = by_stage([STALL], [FIRM, better])
    move = await agent(fake).respond(OBS)
    assert move.price == 140 and move.meta["flags"] == ["stalls"]


async def test_off_makes_one_call():
    fake = by_stage([], [FIRM])
    move = await agent(fake, critic="off").respond(OBS)
    assert len(fake.requests) == 1 and "critique" not in move.meta


async def test_critic_failure_sends_the_draft():
    fake = by_stage([LLMTimeout()], [FIRM])
    move = await agent(fake).respond(OBS)
    assert move.price == 170 and "critic_error" in move.meta


def test_rejects_unknown_settings():
    with pytest.raises(ValueError, match="unknown critic"):
        agent(FakeLLM(), critic="strict")
