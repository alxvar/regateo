import asyncio
import random

import pytest

from regateo.core import Abort, EndReason, Move, Observation, Role, Rules, Scenario
from regateo.core import ActionKind as A
from regateo.match import SimClock, run_match
from regateo.protocol import get_protocol
from regateo.referee import StructuredDetector, TextDetector
from regateo.storage import Store


class Script:
    """Plays a fixed list of moves; records what it observed."""

    def __init__(self, moves, name="script"):
        self.name = name
        self.moves = list(moves)
        self.seen: list[Observation] = []

    async def respond(self, obs):
        self.seen.append(obs)
        m = self.moves.pop(0)
        if isinstance(m, Exception):
            raise m
        if m == "sleep":
            await asyncio.sleep(1)
        return m


def scen(**rules):
    return Scenario(id="s", item="bike", seller_reservation=100, buyer_reservation=150, market_low=80,
                    market_high=180, rules=Rules(first_mover="seller", **rules))


def offer(p, text=None, **meta):
    return Move(text=text or f"${p}", action=A.OFFER, price=p, meta=meta)


async def play(s, seller, buyer, protocol="structured", detector=None, **kw):
    return await run_match(s, seller, buyer, protocol=get_protocol(protocol),
                           detector=detector or StructuredDetector(), rng=random.Random(0), **kw)


async def test_deal():
    seller = Script([offer(170), offer(160)])
    buyer = Script([offer(120), Move(text="ok", action=A.ACCEPT)])
    r = await play(scen(), seller, buyer)
    assert r.outcome.end_reason is EndReason.DEAL and r.outcome.price == 160
    assert r.outcome.closed_by is Role.BUYER and len(r.transcript) == 4
    assert seller.seen[0].incoming is None and seller.seen[1].incoming == "$120"


async def test_round_limit():
    r = await play(scen(max_rounds=2), Script([offer(170)] * 2), Script([offer(120)] * 2))
    assert r.outcome.end_reason is EndReason.ROUND_LIMIT and len(r.transcript) == 4 and not r.outcome.deal


async def test_time_limit_with_sim_clock():
    clock = SimClock(latency_s=(10, 10))
    r = await play(scen(max_rounds=8, time_limit_s=25), Script([offer(170)] * 8), Script([offer(120)] * 8),
                   clock=clock)
    assert r.outcome.end_reason is EndReason.TIME_LIMIT and len(r.transcript) == 2   # third message arrives at 30s


async def test_walk_away_and_error():
    r = await play(scen(), Script([offer(170)]), Script([Move(text="bye", action=A.WALK_AWAY)]))
    assert r.outcome.end_reason is EndReason.WALK_AWAY
    r = await play(scen(), Script([offer(170)]), Script([RuntimeError("boom")]))
    assert r.outcome.end_reason is EndReason.ERROR and r.outcome.error_by is Role.BUYER and "boom" in r.outcome.detail


async def test_abort_propagates():
    with pytest.raises(Abort):
        await play(scen(), Script([Abort("budget")]), Script([]))


async def test_per_message_timeout_forfeits_turn():
    seller = Script([offer(170), offer(165)])
    buyer = Script(["sleep", offer(130)])
    r = await play(scen(max_rounds=2, per_message_timeout_s=0.05), seller, buyer)
    assert r.transcript.messages[1].move.meta == {"timeout": True} and r.transcript.messages[1].text == ""
    assert r.outcome.end_reason is EndReason.ROUND_LIMIT


async def test_opponent_never_sees_meta_or_structure_in_freetext():
    seller = Script([offer(170, secret="hold at 160"), offer(165)])
    buyer = Script([Move(text="$120 max", action=A.OFFER, price=120), Move(text="Deal, $165.")])
    r = await play(scen(), seller, buyer, protocol="freetext", detector=TextDetector())
    first = buyer.seen[0].history[0]
    assert first.move.meta == {} and first.move.price is None
    own = seller.seen[1].history[0].move.meta
    assert own["secret"] == "hold at 160" and own["intent"]["price"] == 170   # own history keeps meta + intent
    assert all(m.reading is None for o in seller.seen + buyer.seen for m in o.history)   # referee's, not theirs
    assert [m.reading.kind for m in r.transcript.messages] == ["offer", "offer", "offer", "accept"]
    assert r.outcome.price == 165


async def test_messages_persisted(tmp_path):
    store = await Store.open(tmp_path / "db")
    s = scen()
    from regateo.core.agent import AgentRef
    mid = await store.start_match(scenario=s, seller=AgentRef(name="a"), buyer=AgentRef(name="b"),
                                  protocol="structured")
    await play(s, Script([offer(170)]), Script([Move(text="ok", action=A.ACCEPT)]), store=store, match_id=mid)
    assert [m.text for m in await store.match_messages(mid)] == ["$170", "ok"]
    await store.close()
