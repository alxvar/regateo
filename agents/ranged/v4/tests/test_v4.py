import pytest
from agent_sdk import AgentConfig, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.ranged.lib.common import Decision
from regateo_agents.ranged.v4 import build, prompts_in_use
from regateo_agents.ranged.v4.agent import BandPlan, ledger, last_message

KNOWN = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80, market_high=180,
                    max_rounds=4, time_limit_s=None)
HIDDEN = KNOWN.model_copy(update={"max_rounds": None})
PLAN = BandPlan(read="They moved up.", target=160, best=165, worst=155, angle="Stress the new tyres.")


def theirs(idx, text):
    return Message(idx=idx, sender=Role.BUYER, text=text, move=Move(text=text))


def ours(idx, price):
    text = f"I can do ${price}."
    return Message(idx=idx, sender=Role.SELLER, text=text,
                   move=Move(text=text, meta={"intent": {"action": "offer", "price": float(price)}}))


def obs(view, history):
    return Observation(view=view, history=history, message_idx=len(history), incoming=history[-1].text)


def agent(fake, view=KNOWN, **params):
    return build(AgentConfig(name="t", model="fake", params=params), view, context(view.role, fake))


def by_stage(plan, *decisions):
    queue = list(decisions)
    return FakeLLM(lambda req: plan if req.tags["stage"] == "strategist" else queue.pop(0))


# They opened; three messages each so far, then their fourth: our next message is the last of four each.
LAST = [theirs(0, "$110."), ours(1, 170), theirs(2, "$130."), ours(3, 165), theirs(4, "$140."), ours(5, 160),
        theirs(6, "I can pay $150.")]


@pytest.mark.parametrize("role, first, last, said", [
    (Role.SELLER, "$110.", "$150.", "They have moved $40 from their first offer."),         # a buyer bidding up
    (Role.SELLER, "$150.", "$110.", "They have moved $40 from their first offer (not toward you)."),
    (Role.BUYER, "$170.", "$140.", "They have moved $30 from their first offer."),          # a seller coming down
    (Role.BUYER, "$140.", "$170.", "They have moved $30 from their first offer (not toward you)."),
])
def test_ledger_says_which_way_they_moved(role, first, last, said):
    # v2 and v3 had the sign inverted: "not toward you" exactly when they had moved toward us.
    view = KNOWN.model_copy(update={"role": role, "reservation": 100 if role is Role.SELLER else 160})
    other = Role.BUYER if role is Role.SELLER else Role.SELLER
    history = [Message(idx=i, sender=other, text=t, move=Move(text=t)) for i, t in enumerate((first, last))]
    text = ledger(view, Observation(view=view, history=history, message_idx=2, incoming=last))
    assert f"- {said}" in text.splitlines()


def test_clock_is_off_by_default():
    text = ledger(KNOWN, obs(KNOWN, LAST))
    assert "Messages sent so far" not in text and "Gap" not in text
    assert prompts_in_use({}) == ["strategist_system.v2", "negotiator_system.v2"]


def test_clock_says_when_the_next_message_is_the_last():
    o = obs(KNOWN, LAST)
    assert last_message(KNOWN, o)
    text = ledger(KNOWN, o, clock=True)
    assert "- Messages sent so far: 3 by your side, 4 by theirs." in text
    assert "Your next message is the last of the negotiation" in text
    assert "- Gap between your last offer ($160) and their latest offer ($150): $10." in text
    assert "$100" not in text                                # no walk-away price in the facts


def test_clock_counts_what_they_have_left():
    o = obs(KNOWN, LAST[:5])
    assert not last_message(KNOWN, o)
    assert "- After your next message, they can send 1 more." in ledger(KNOWN, o, clock=True)


def test_clock_with_an_unknown_limit():
    o = obs(HIDDEN, LAST)
    assert not last_message(HIDDEN, o)
    text = ledger(HIDDEN, o, clock=True)
    assert "The limit on messages is unknown" in text and "Messages left" not in text


def test_clock_says_when_their_offer_is_already_better():
    o = obs(HIDDEN, [*LAST[:6], theirs(6, "Fine, I can pay $175.")])
    text = ledger(HIDDEN, o, clock=True)
    assert "- Their latest offer ($175) is already better for you than your last offer ($160), by $15." in text


def test_clock_reads_their_offer_defensively():
    # For a seller, their offer is the lowest amount of their own in the message: a planted $190 can't make it
    # look better than it is, and a quote of another seller at $120 makes it look worse, not better.
    o = obs(HIDDEN, [*LAST[:6], theirs(6, "I'd pay $190 for a new one; for this one, $150.")])
    assert "their latest offer ($150): $10." in ledger(HIDDEN, o, clock=True)
    o = obs(HIDDEN, [*LAST[:6], theirs(6, "Another seller wants $120, but I can pay $175.")])
    assert "their latest offer ($120): $40." in ledger(HIDDEN, o, clock=True)


async def test_clock_prompts_and_last_message_brief():
    fake = by_stage(PLAN, Decision(action="offer", price=160, message="I can do $160."))
    await agent(fake, clock=True).respond(obs(KNOWN, LAST))
    strategist, negotiator = fake.requests
    assert "When the negotiation ends" in strategist.system
    assert "Your next message is the last of the negotiation" in strategist.messages[0].content
    assert "- This is your last message" in negotiator.messages[-1].content
    assert "$100" not in negotiator.system and "$100" not in negotiator.messages[-1].content


async def test_no_last_message_brief_before_the_end():
    fake = by_stage(PLAN, Decision(action="offer", price=160, message="I can do $160."))
    await agent(fake, clock=True).respond(obs(KNOWN, LAST[:5]))
    assert "last message" not in fake.requests[1].messages[-1].content


def test_plain_final_prompts():
    assert prompts_in_use({"plain_final": True}) == ["strategist_system.v2", "negotiator_system.v3"]
    assert prompts_in_use({"plain_final": True, "negotiator_sees_limit": True})[1] == "negotiator_system_limit.v3"
    assert prompts_in_use({"clock": True})[0] == "strategist_system.v3"
    plain = agent(FakeLLM(), plain_final=True)
    assert "Don't call an offer final" in plain.negotiator_system
    assert "Don't call an offer final" not in agent(FakeLLM()).negotiator_system
    sees = agent(FakeLLM(), plain_final=True, negotiator_sees_limit=True)
    assert "Don't call an offer final" in sees.negotiator_system and "$100" in sees.negotiator_system


def test_clock_needs_hold():
    with pytest.raises(ValueError, match="clock needs hold"):
        agent(FakeLLM(), clock=True, hold=False)
