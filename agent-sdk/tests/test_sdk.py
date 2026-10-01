import random

import pytest

from agent_sdk import (
    ActionKind,
    Agent,
    AgentContext,
    LLMRequest,
    LLMResponse,
    Message,
    Move,
    Observation,
    PrivateView,
    ProtocolInfo,
    Role,
    sign,
)

VIEW = PrivateView(role=Role.BUYER, item="bike", currency="USD", reservation=150, market_low=80, market_high=180,
                   max_rounds=4, time_limit_s=None)
PROTOCOL = ProtocolInfo(name="freetext", structured=False, description="Offers are read from the text.")


class Echo:
    """The smallest agent: answers every model call's text as its message."""

    name = "echo"

    def __init__(self, ctx: AgentContext):
        self.llm = ctx.llm("some-profile", "writer")

    async def respond(self, obs: Observation) -> Move:
        resp = await self.llm.complete(LLMRequest.of(obs.incoming or "open"))
        return Move(text=resp.text, action=ActionKind.MESSAGE)


class Parrot:
    async def complete(self, req: LLMRequest) -> LLMResponse:
        return LLMResponse(text=f"you said: {req.messages[-1].content}")


async def test_an_agent_reaches_models_only_through_its_context():
    stages = []
    ctx = AgentContext(role=Role.BUYER, rng=random.Random(0), protocol=PROTOCOL,
                       llm_factory=lambda profile, stage: stages.append(stage) or Parrot())
    agent = Echo(ctx)
    assert isinstance(agent, Agent) and stages == ["writer"]
    hello = Message(idx=0, sender=Role.SELLER, text="hello", move=Move(text="hello"))
    move = await agent.respond(Observation(view=VIEW, history=[hello], incoming="hello", message_idx=1))
    assert move.text == "you said: hello"


def test_context_without_model_access():
    ctx = AgentContext(role=Role.BUYER, rng=random.Random(0), protocol=PROTOCOL)
    with pytest.raises(ValueError):
        ctx.llm(None, "writer")
    with pytest.raises(RuntimeError):
        ctx.llm("some-profile", "writer")


def test_u_space():
    assert sign(Role.SELLER) * 120 > sign(Role.SELLER) * 100
    assert sign(Role.BUYER) * 100 > sign(Role.BUYER) * 120
