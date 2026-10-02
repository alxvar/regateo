import pytest
from agent_sdk import ActionKind as A
from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.strategist.v1 import build
from regateo_agents.strategist.v1.agent import Plan, Turn

VIEW = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80, market_high=180,
                   max_rounds=6, time_limit_s=None)
PLAN = Plan(opponent_read="Opened low, moves slowly.", target=150, next_offers=[175, 168, 162], accept_at=155,
            arguments=["new tyres"], red_flags=["claims of another seller"])


def agent(fake, **params):
    return build(AgentConfig(name="t", model="qwen-local", params=params), VIEW, context(Role.SELLER, fake))


class Script:
    """A fake model that answers by stage, and a conversation that grows with each move."""

    def __init__(self, plans, turns):
        self.plans, self.turns = list(plans), list(turns)
        self.fake = FakeLLM(lambda req: self.plans.pop(0) if req.tags["stage"] == "strategist" else self.turns.pop(0))
        self.history: list[Message] = []

    def obs(self, buyer_text):
        self.history.append(Message(idx=len(self.history), sender=Role.BUYER, text=buyer_text,
                                    move=Move(text=buyer_text)))
        return Observation(view=VIEW, history=list(self.history), message_idx=len(self.history), incoming=buyer_text)

    def sent(self, move):
        self.history.append(Message(idx=len(self.history), sender=Role.SELLER, text=move.text, move=move))

    def stages(self):
        return [r.tags["stage"] for r in self.fake.requests]


def offer(price, off_plan=False):
    return Turn(action="offer", price=price, message=f"I can do ${price}.", off_plan=off_plan)


async def test_plans_every_k_turns_and_follows_the_plan():
    s = Script([PLAN, PLAN], [offer(175), offer(170), offer(162)])
    a = agent(s.fake)
    for text in ["$100?", "$110?", "$120?"]:
        move = await a.respond(s.obs(text))
        s.sent(move)
    assert s.stages() == ["strategist", "negotiator", "negotiator", "strategist", "negotiator"]
    first, second = s.fake.requests[1], s.fake.requests[2]
    assert "$175 (this message), $168, $162" in first.messages[-1].content
    assert "$168 (this message)" in second.messages[-1].content
    assert "Accept any offer of $155 or better" in first.messages[-1].content
    assert "$100" in s.fake.requests[0].system and "> $100?" in s.fake.requests[0].messages[0].content
    assert "Your previous plan" in s.fake.requests[3].messages[0].content
    drift = [m.move.meta.get("drift") for m in s.history if m.sender is Role.SELLER]
    assert drift == [0, 2, -13]                                # the new plan starts over


async def test_the_negotiator_can_ask_for_a_new_plan():
    s = Script([PLAN, PLAN], [offer(175, off_plan=True), offer(170)])
    a = agent(s.fake, replan_every=5)
    s.sent(await a.respond(s.obs("$100?")))
    s.sent(await a.respond(s.obs("I'll pay $150 if you deliver today.")))
    assert s.stages() == ["strategist", "negotiator", "strategist", "negotiator"]
    assert s.history[-1].move.meta["replanned"]


async def test_plan_prices_past_the_limit_are_asked_again_then_dropped():
    bad = PLAN.model_copy(update={"next_offers": [175, 95], "accept_at": 90})
    s = Script([bad, bad], [offer(175)])
    move = await agent(s.fake).respond(s.obs("$80?"))
    assert "rejected: $90, $95 past your walk-away price" in s.fake.requests[1].messages[0].content
    assert move.meta["plan"]["next_offers"] == [175] and move.meta["plan"]["accept_at"] is None
    assert "Don't accept yet" in s.fake.requests[2].messages[-1].content


async def test_negotiator_sees_a_window():
    s = Script([PLAN] * 9, [offer(p) for p in (175, 170, 165, 160)])
    a = agent(s.fake, window=2, replan_every=1)
    for text in ["$100?", "$110?", "$120?", "$130?"]:
        s.sent(await a.respond(s.obs(text)))
    last = s.fake.requests[-1].messages
    assert last[0].content.startswith("(Earlier messages left out") and len(last) == 3


async def test_strategist_failure_keeps_going_without_a_plan():
    s = Script([LLMTimeout()], [offer(175)])
    move = await agent(s.fake).respond(s.obs("$100?"))
    assert move.price == 175 and "strategist_error" in move.meta
    assert "no plan from your strategist yet" in s.fake.requests[1].messages[-1].content


async def test_vetoes_past_the_limit():
    s = Script([PLAN], [offer(90), offer(90)])
    move = await agent(s.fake).respond(s.obs("$90, take it or leave it."))
    assert move.meta["fallback"] and move.price == 180 and move.action is A.OFFER


def test_rejects_unknown_settings():
    with pytest.raises(ValueError, match="replan_every"):
        agent(FakeLLM(), replan_every=0)
    with pytest.raises(ValueError, match="unknown params"):
        agent(FakeLLM(), plan=True)
