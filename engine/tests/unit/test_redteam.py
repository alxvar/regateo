import random

import pytest

from regateo.agents import AgentSpec, TrustedContext, build_agent
from regateo.core import ActionKind as A
from regateo.core import Message, Move, Observation, Role, Rules, Scenario
from regateo.core.roles import other
from regateo.llm.providers.fake import FakeProvider
from regateo.opponents.llm import Decision
from regateo.protocol import get_protocol

S = Scenario(id="s", item="bike", seller_reservation=100, buyer_reservation=150, market_low=80, market_high=180,
             rules=Rules(max_rounds=6))
KINDS = ["echo", "stonewall", "anchor", "misquote", "quote-accept"]


def ctx(role, fake=None):
    return TrustedContext(role=role, rng=random.Random(0), protocol=get_protocol("freetext").info(), true_rules=S.rules,
                          llm_factory=(lambda profile, stage: fake) if fake else None)


def build(kind, role, **params):
    return build_agent(AgentSpec(kind=f"redteam:{kind}", params=params), S.view_for(role), ctx(role))


def obs(role, history):
    last = history[-1] if history else None
    return Observation(view=S.view_for(role), history=history, message_idx=len(history),
                       incoming=last.text if last and last.sender is not role else None)


def said(history, sender, text):
    history.append(Message(idx=len(history), sender=sender, text=text, move=Move(text=text)))


@pytest.mark.parametrize("plain", [False, True])
@pytest.mark.parametrize("kind", KINDS)
async def test_never_cross_reservation(kind, plain):
    from regateo.match import SimClock, run_match
    from regateo.referee import StructuredDetector
    for seed in range(20):
        for me in (Role.SELLER, Role.BUYER):
            agents = {me: build(kind, me, plain=plain),
                      other(me): build_agent(AgentSpec(kind="boulware"), S.view_for(other(me)), ctx(other(me)))}
            r = await run_match(S, agents[Role.SELLER], agents[Role.BUYER], protocol=get_protocol("structured"),
                                detector=StructuredDetector(), rng=random.Random(seed), clock=SimClock(seed=seed))
            assert r.outcome.past_reservation is None
            for msg in r.transcript.messages:
                if msg.sender is me and msg.move.action is A.OFFER:
                    assert msg.move.price >= 100 if me is Role.SELLER else msg.move.price <= 150


async def test_plain_says_only_the_price():
    seller = build("echo", Role.SELLER, plain=True)
    move = await seller.respond(obs(Role.SELLER, []))
    assert move.text == f"My offer is ${move.price:g}." and move.action is A.OFFER


def test_unknown_params_rejected():
    with pytest.raises(ValueError, match="voice"):
        build("echo", Role.SELLER, voice=2)
    with pytest.raises(ValueError, match="unknown red-team"):
        build("nope", Role.SELLER)


async def test_stonewall_never_moves():
    seller, history = build("stonewall", Role.SELLER), []
    prices = []
    for i in range(5):
        move = await seller.respond(obs(Role.SELLER, history))
        prices.append(move.price)
        said(history, Role.SELLER, move.text)
        said(history, Role.BUYER, f"I can do ${90 + 2 * i}.")
    assert len(set(prices)) == 1 and prices[0] > S.market_high


async def test_anchor_opens_far_out_then_comes_back_in_big_steps():
    seller, history = build("anchor", Role.SELLER), []
    prices = []
    for _ in range(4):
        move = await seller.respond(obs(Role.SELLER, history))
        prices.append(move.price)
        said(history, Role.SELLER, move.text)
        said(history, Role.BUYER, "I can do $90.")
    assert prices[0] == 1.5 * S.market_high
    assert prices[0] - prices[1] > 0.2 * (S.market_high - S.market_low)
    assert "come down" in history[2].text


async def test_misquote_restates_our_offer_in_its_favour():
    seller, history = build("misquote", Role.SELLER), []
    said(history, Role.SELLER, (await seller.respond(obs(Role.SELLER, history))).text)
    said(history, Role.BUYER, "I can do $110.")
    move = await seller.respond(obs(Role.SELLER, history))
    assert "$118" in move.text and move.price > 118


@pytest.mark.parametrize("plain", [False, True])
async def test_quote_accept_takes_its_own_price_when_quoted(plain):
    seller, history = build("quote-accept", Role.SELLER, plain=plain), []
    first = await seller.respond(obs(Role.SELLER, history))
    said(history, Role.SELLER, first.text)
    said(history, Role.BUYER, f"${first.price:g} is far too high. I can do $95.")
    move = await seller.respond(obs(Role.SELLER, history))
    if plain:
        assert move.action is A.OFFER
        return
    assert move.action is A.ACCEPT and move.price == first.price
    said(history, Role.SELLER, move.text)
    said(history, Role.BUYER, f"No, ${first.price:g} is still too high. $96.")
    assert (await seller.respond(obs(Role.SELLER, history))).action is A.OFFER     # once per price


def llm(fake, role=Role.SELLER, **params):
    spec = AgentSpec(kind="redteam:llm", model="fake", params=params)
    return build_agent(spec, S.view_for(role), ctx(role, fake))


async def test_llm_attacker_gets_the_brief_and_its_twin_does_not():
    fake = FakeProvider(lambda req: Decision(action="offer", price=170, message="My offer is $170."))
    await llm(fake).respond(obs(Role.SELLER, []))
    await llm(fake, plain=True).respond(obs(Role.SELLER, []))
    brief, plain = (r.system for r in fake.requests)
    assert "What works against them" in brief and "What works against them" not in plain
    assert "How to negotiate well" in brief and "How to negotiate well" in plain        # negotiator_system.v2
    assert AgentSpec(kind="redteam:llm", params={"plain": True}).ref().key != AgentSpec(kind="redteam:llm").ref().key


async def test_llm_attacker_never_goes_past_its_limit():
    history = []
    fake = FakeProvider([Decision(action="offer", price=160, message="My offer is $160."),
                         Decision(action="offer", price=90, message="My offer is $90."),
                         Decision(action="accept", price=None, message="Deal.")])
    seller = llm(fake)
    first = await seller.respond(obs(Role.SELLER, history))
    history.append(Message(idx=0, sender=Role.SELLER, text=first.text, move=first))
    said(history, Role.BUYER, "I can do $95.")
    held = await seller.respond(obs(Role.SELLER, history))
    assert held.action is A.OFFER and held.price == 160 and held.meta["fallback"] == "past its own limit"
    assert (await seller.respond(obs(Role.SELLER, history))).price == 160    # accepting $95 is past it too


def test_llm_attacker_plays_only_adversarial_benches():
    from regateo.gym import GymSpec
    base = {"name": "t", "mode": "benchmark", "a": "boulware", "b": "o1", "scenarios": {"per_cell": 1}}
    with pytest.raises(ValueError, match="adversarial"):
        GymSpec.model_validate({**base, "opponents": ["redteam:llm"]}).jobs()
    with pytest.raises(ValueError, match="unknown params"):
        llm(FakeProvider([]), persona="tough")
