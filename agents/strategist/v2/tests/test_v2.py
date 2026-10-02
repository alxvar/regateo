from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.strategist.v2 import build
from regateo_agents.strategist.v2.agent import Plan, Turn

VIEW = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80, market_high=180,
                   max_rounds=6, time_limit_s=None)
PLAN = Plan(opponent_read="Opened low.", target=150, next_offers=[175, 168], accept_at=155, hold_rule="Hold once.",
            endgame="Accept their last offer if it is above $100.", arguments=["new tyres"], red_flags=[])


def history(*texts):
    out = []
    for i, t in enumerate(texts):
        sender = Role.BUYER if i % 2 == 0 else Role.SELLER
        out.append(Message(idx=i, sender=sender, text=t, move=Move(text=t)))
    return out


async def test_notes_carry_plan_and_facts():
    fake = FakeLLM(lambda req: PLAN if req.tags["stage"] == "strategist"
                   else Turn(action="offer", price=175, message="I can do $175."))
    a = build(AgentConfig(name="t", model="qwen-local", params={}), VIEW, context(Role.SELLER, fake))
    h = history("I offer $110.")
    move = await a.respond(Observation(view=VIEW, history=h, message_idx=1, incoming="I offer $110."))
    assert move.price == 175
    plan_prompt = fake.requests[0].messages[0].content
    assert "the other side has written 1 of 6" in plan_prompt
    note = fake.requests[1].messages[-1].content
    assert "Endgame: Accept their last offer" in note and "How to adapt: Hold once." in note
    assert "Their latest offer: $110" in note


async def test_no_plan_still_gets_facts():
    def answer(req):
        if req.tags["stage"] == "strategist":
            raise LLMTimeout("slow")
        return Turn(action="offer", price=170, message="I can do $170.")

    fake = FakeLLM(answer)
    a = build(AgentConfig(name="t", model="qwen-local", params={}), VIEW, context(Role.SELLER, fake))
    h = history("I offer $110.")
    move = await a.respond(Observation(view=VIEW, history=h, message_idx=1, incoming="I offer $110."))
    assert move.price == 170
    assert "no plan" in fake.requests[-1].messages[-1].content
    assert "Messages: your side has written 0 of 6" in fake.requests[-1].messages[-1].content
