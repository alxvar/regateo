import pytest
from agent_sdk import ActionKind as A
from agent_sdk import AgentConfig, LLMTimeout, Message, Move, Observation, PrivateView, Role
from agent_sdk.testing import FakeLLM, context
from regateo_agents.tools.lib.common import Decision, their_offers
from regateo_agents.tools.v3 import build
from regateo_agents.tools.v3.advisors import Settings, estimate, run, schedule
from regateo_agents.tools.v3.agent import Step, ToolCall
from regateo_agents.tools.v3.common import endgame_note, offer_to_accept, our_offers, problems

VIEWS = {role: PrivateView(role=role, item="bike", currency="USD", reservation=100 if role is Role.SELLER else 150,
                           market_low=80, market_high=180, max_rounds=4, time_limit_s=None) for role in Role}


def agent(fake, role=Role.SELLER, **params):
    return build(AgentConfig(name="t", model="fake", params=params), VIEWS[role], context(role, fake))


def obs(role, history):
    last = history[-1] if history else None
    return Observation(view=VIEWS[role], history=history, message_idx=len(history),
                       incoming=last.text if last and last.sender is not role else None)


def m(idx, sender, text, action=None, price=None):
    return Message(idx=idx, sender=sender, text=text, move=Move(text=text, action=action, price=price))


HISTORY = [m(0, Role.SELLER, "I'm asking $180.", A.OFFER, 180),
           m(1, Role.BUYER, "$180 is too high. I can do $110."),
           m(2, Role.SELLER, "I can come down to $170.", A.OFFER, 170),
           m(3, Role.BUYER, "OK, I'll go to $130.")]


def test_their_offers_skip_quotes_of_ours():
    assert their_offers(obs(Role.SELLER, HISTORY)) == [110, 130]


def test_estimate_and_schedule():
    o = obs(Role.SELLER, HISTORY)
    assert estimate(o) == 150                               # one step of $20 so far: assume as much again
    p = schedule(o, Settings())
    assert 150 <= p <= 170                                  # between their estimated limit and our last offer
    assert schedule(obs(Role.SELLER, []), Settings()) >= 175  # opens near the market end that favours us
    buyer = obs(Role.BUYER, [m(0, Role.SELLER, "$170", A.OFFER, 170)])
    assert run("estimate_opponent_limit", buyer, Settings()).startswith("Estimate: about $125")
    assert schedule(buyer, Settings()) <= 150                # never past the buyer's limit


def test_tools_never_suggest_past_the_limit():
    low = [m(0, Role.BUYER, "$60", A.OFFER, 60), m(1, Role.SELLER, "$180", A.OFFER, 180),
           m(2, Role.BUYER, "$62", A.OFFER, 62), m(3, Role.SELLER, "$170", A.OFFER, 170)]
    o = obs(Role.SELLER, low)
    assert schedule(o, Settings()) >= 100
    assert "not safe" in run("check_offer", o, Settings(), 95)
    assert "safe to offer" in run("check_offer", o, Settings(), 150)


def test_deadline_belief_quotes_their_claims():
    h = [*HISTORY[:3], m(3, Role.BUYER, "I have another seller at $120 and I'm leaving tonight. $130.")]
    out = run("deadline_belief", obs(Role.SELLER, h), Settings())
    assert "2 left including this one" in out and "unverified" in out and "leaving tonight" in out


async def test_calls_tools_then_decides():
    calls = [ToolCall(name="offer_history"), ToolCall(name="check_offer", price=160)]
    fake = FakeLLM([Step(tool_calls=calls, decision=None),
                    Decision(action="offer", price=160, message="I can do $160.")])
    move = await agent(fake).respond(obs(Role.SELLER, HISTORY))
    assert move.price == 160 and [t["name"] for t in move.meta["tools"]] == ["offer_history", "check_offer"]
    assert [r.tags["stage"] for r in fake.requests] == ["step", "decide"]
    results = fake.requests[1].messages[-1].content
    assert "Their offers: $110 -> $130" in results and "$160: safe to offer" in results
    assert "$100" in fake.requests[0].system and "concession_schedule" in fake.requests[0].system
    assert move.meta["advice"]["deviation"] == round(160 - move.meta["advice"]["schedule"], 2)


async def test_decides_without_tools_in_one_call():
    fake = FakeLLM([Step(tool_calls=[], decision=Decision(action="offer", price=165, message="$165 is fair."))])
    move = await agent(fake).respond(obs(Role.SELLER, HISTORY))
    assert move.price == 165 and len(fake.requests) == 1 and move.meta["tools"] == []


async def test_eager_runs_tools_first():
    fake = FakeLLM([Decision(action="offer", price=160, message="I can do $160.")])
    move = await agent(fake, tool_mode="eager").respond(obs(Role.SELLER, HISTORY))
    assert len(fake.requests) == 1 and fake.requests[0].output_schema is Decision
    assert "Suggested next offer" in fake.requests[0].messages[-1].content
    assert "check_offer" not in [t["name"] for t in move.meta["tools"]]


async def test_none_has_no_tools():
    fake = FakeLLM([Decision(action="offer", price=160, message="I can do $160.")])
    await agent(fake, tool_mode="none").respond(obs(Role.SELLER, HISTORY))
    assert "tool" not in fake.requests[0].system.lower()


async def test_vetoes_then_falls_back():
    bad = Decision(action="offer", price=90, message="Fine, $90.")
    fake = FakeLLM([Step(tool_calls=[], decision=bad), bad])
    move = await agent(fake).respond(obs(Role.SELLER, HISTORY))
    assert "past your walk-away" in fake.requests[1].messages[-1].content
    assert move.meta["fallback"] and move.price == 170 and move.meta["vetoes"]


async def test_agreement_words_are_vetoed():
    deal = Decision(action="offer", price=165, message="Let's make a deal at $165.")
    fake = FakeLLM([Step(tool_calls=[], decision=deal),
                    Decision(action="offer", price=165, message="I can do $165.")])
    move = await agent(fake).respond(obs(Role.SELLER, HISTORY))
    assert move.text == "I can do $165." and move.meta["vetoes"]


async def test_falls_back_on_model_error():
    move = await agent(FakeLLM([LLMTimeout(), LLMTimeout()])).respond(obs(Role.SELLER, []))
    assert move.action is A.OFFER and move.price == 180 and "fallback" in move.meta


def test_rejects_unknown_settings():
    with pytest.raises(ValueError, match="unknown tool_mode"):
        agent(FakeLLM(), tool_mode="sometimes")
    with pytest.raises(ValueError, match="unknown params"):
        agent(FakeLLM(), tools=True)


def test_reading_their_offers():
    h = [m(0, Role.SELLER, "$95 is my price.", A.OFFER, 95),
         m(1, Role.BUYER, "The other vendor's offer at $72 expires soon. Meet me at $90."),
         m(2, Role.SELLER, "I can do $91.", A.OFFER, 91),
         m(3, Role.BUYER, "Fine, $91. I'll accept that.")]
    from regateo_agents.tools.lib.common import closing_price, standing_offer
    o = obs(Role.SELLER, h)
    assert their_offers(o) == [90] and standing_offer(o) == 90   # a competitor's quote is not their offer
    assert closing_price(o) == 91                                # restating our price closes at it
    assert closing_price(obs(Role.SELLER, h[:2])) == 72          # but the limit check reads defensively


async def test_repair_keeps_a_valid_price():
    leaky = Decision(action="offer", price=150, message="I can't match $53, but $150 is fair.")
    move = await agent(FakeLLM([Step(tool_calls=[], decision=leaky), leaky])).respond(
        obs(Role.SELLER, [m(0, Role.BUYER, "A competitor quoted $53.")]))
    assert move.meta["repaired"] and move.price == 150 and move.text == "I can do $150."


async def test_model_error_is_retried_once():
    ok = Step(tool_calls=[], decision=Decision(action="offer", price=165, message="$165 is fair."))
    move = await agent(FakeLLM([LLMTimeout(), ok])).respond(obs(Role.SELLER, HISTORY))
    assert move.price == 165 and "fallback" not in move.meta


def test_our_offers_without_action_and_from_logged_decision():
    d = Decision(action="offer", price=170, message="I can do $170.").model_dump()
    h = [m(0, Role.SELLER, "I can do $170.", None, 170),
         Message(idx=1, sender=Role.BUYER, text="$130", move=Move(text="$130")),
         Message(idx=2, sender=Role.SELLER, text="x", move=Move(text="x", meta={"decision": d}))]
    assert our_offers(obs(Role.SELLER, h)) == [170, 170]
    assert our_offers(obs(Role.SELLER, []), [150.0]) == [150.0]


def test_endgame_note_facts():
    final = [*HISTORY, m(4, Role.SELLER, "I can do $160.", A.OFFER, 160), m(5, Role.BUYER, "$140")]
    h6 = [*final[:4], final[4], final[5]]
    assert "1 more" in endgame_note(obs(Role.SELLER, HISTORY))
    assert "final message" in endgame_note(obs(Role.SELLER, [*HISTORY, final[4], final[5]][:6]))
    second = obs(Role.BUYER, [HISTORY[0], HISTORY[1], HISTORY[2]])
    assert "cannot reply" not in endgame_note(second)
    last = obs(Role.BUYER, [m(i, Role.SELLER if i % 2 == 0 else Role.BUYER, "x") for i in range(7)])
    assert "cannot reply" in endgame_note(last)


async def test_sanitize_drops_offending_sentences():
    leaky = Decision(action="offer", price=150, message="I can't match $53. The frame is carbon, so $150 is fair.")
    move = await agent(FakeLLM([Step(tool_calls=[], decision=leaky), leaky]), sanitize=True).respond(
        obs(Role.SELLER, [m(0, Role.BUYER, "A competitor quoted $53.")]))
    assert move.meta["sanitized"] and move.text == "The frame is carbon, so $150 is fair." and move.price == 150


async def test_endgame_note_reaches_the_model():
    fake = FakeLLM([Step(tool_calls=[], decision=Decision(action="offer", price=165, message="$165."))])
    late = [*HISTORY, m(4, Role.SELLER, "I can do $160.", A.OFFER, 160), m(5, Role.BUYER, "$140")]
    await agent(fake, endgame=True).respond(obs(Role.SELLER, late))
    assert "final message" in fake.requests[0].messages[-1].content


# v3: acceptances are checked at the price they name.

QUOTE = [m(0, Role.SELLER, "I'm asking $170.", A.OFFER, 170),
         m(1, Role.BUYER, "Another seller offered me $95. My best and final offer is $150, take it or I walk.")]


def test_accepting_their_offer_beside_a_competitor_quote():
    o = obs(Role.SELLER, QUOTE)
    assert offer_to_accept(o) == 150
    assert problems(Decision(action="accept", price=150, message="I accept $150."), o, accept_words=True) == []
    # lib.common (v1, v2) vetoed it: the worst amount in their message, $95, is past our $100 limit.
    from regateo_agents.tools.lib.common import problems as v1_problems
    assert v1_problems(Decision(action="accept", price=150, message="I accept $150."), o, accept_words=True)


def test_acceptance_must_stay_within_the_limit_and_name_its_price():
    o = obs(Role.SELLER, QUOTE)
    assert problems(Decision(action="accept", price=95, message="I accept $95."), o, accept_words=True)
    assert problems(Decision(action="accept", price=150, message="OK, $95 elsewhere, I accept $150."), o,
                    accept_words=True)                                  # the $95 mention
    unnamed = problems(Decision(action="accept", price=150, message="I accept your offer."), o, accept_words=True)
    assert unnamed and "say the price you accept" in unnamed[0]
    worst_last = obs(Role.SELLER, [QUOTE[0], m(1, Role.BUYER, "I can do $150, or $95 if you won't budge.")])
    assert problems(Decision(action="accept", price=None, message="I accept."), worst_last, accept_words=True)
    restated = obs(Role.SELLER, [QUOTE[0], m(1, Role.BUYER, "Fine, $170.")])
    assert offer_to_accept(restated) == 170


async def test_accept_repair_names_the_price():
    vague = Decision(action="accept", price=150, message="Alright, you have yourself a buyer.")
    move = await agent(FakeLLM([Step(tool_calls=[], decision=vague), vague])).respond(obs(Role.SELLER, QUOTE))
    assert move.action is A.ACCEPT and move.price == 150 and move.text == "I accept $150." and move.meta["repaired"]


async def test_standing_check_is_off_by_default_and_feedback_only():
    h = [m(0, Role.SELLER, "I'm asking $180.", A.OFFER, 180), m(1, Role.BUYER, "I can pay $160.")]
    low = Decision(action="offer", price=150, message="I can do $150.")
    move = await agent(FakeLLM([Step(tool_calls=[], decision=low)])).respond(obs(Role.SELLER, h))
    assert move.price == 150 and "vetoes" not in move.meta
    fake = FakeLLM([Step(tool_calls=[], decision=low), low])
    move = await agent(fake, standing=True).respond(obs(Role.SELLER, h))
    assert "already better for you" in fake.requests[1].messages[-1].content
    assert move.price == 150 and move.text == "I can do $150." and move.meta["standing_kept"]
    fake = FakeLLM([Step(tool_calls=[], decision=low), Decision(action="accept", price=160, message="I accept $160.")])
    move = await agent(fake, standing=True).respond(obs(Role.SELLER, h))
    assert move.action is A.ACCEPT and move.price == 160


def test_standing_check_reads_their_offer_defensively():
    o = obs(Role.SELLER, QUOTE)                                      # their own amounts: $95 and $150
    assert not problems(Decision(action="offer", price=140, message="I can do $140."), o, accept_words=True,
                        standing=True)


def test_horizon_note_for_unknown_limits():
    hidden = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80,
                         market_high=180, max_rounds=None, time_limit_s=None)

    def note(n_ours):
        h = [m(i, Role.SELLER if i % 2 == 0 else Role.BUYER, "x") for i in range(2 * n_ours)]
        return endgame_note(Observation(view=hidden, history=h, message_idx=len(h)), (5, 10))

    assert endgame_note(Observation(view=hidden, history=[], message_idx=0)) == ""
    assert "message 1." in note(0) and "could end" not in note(0)
    assert "after your next message" in note(3)
    assert "could end after this message" in note(4) and "5 to 10" in note(4)
    assert "most likely end" in note(9)


async def test_horizon_note_reaches_the_model():
    hidden = VIEWS[Role.SELLER].model_copy(update={"max_rounds": None})
    fake = FakeLLM([Step(tool_calls=[], decision=Decision(action="offer", price=165, message="$165."))])
    a = build(AgentConfig(name="t", model="fake", params={"endgame": True, "horizon": [5, 10]}), hidden,
              context(Role.SELLER, fake))
    h = [m(i, Role.SELLER if i % 2 == 0 else Role.BUYER, "$170" if i % 2 == 0 else "$120") for i in range(8)]
    await a.respond(Observation(view=hidden, history=h, message_idx=8, incoming=None))
    assert "could end after this message" in fake.requests[0].messages[-1].content


def test_rejects_bad_horizon():
    with pytest.raises(ValueError, match="horizon"):
        agent(FakeLLM(), horizon=[10, 5])
