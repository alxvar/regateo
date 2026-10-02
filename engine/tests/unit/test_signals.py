from regateo.cli import format as fmt
from regateo.core import Message, Move, Role, Rules, Scenario
from regateo.core.messages import Reading, ReadKind
from regateo.core.outcome import EndReason, Outcome
from regateo.gym.signals import SidePlay, match_signals, run_signals

S = Scenario(id="s", item="bike", seller_reservation=100, buyer_reservation=150, market_low=80, market_high=180,
             rules=Rules(max_rounds=6))
NO_DEAL = Outcome(deal=False, end_reason=EndReason.ROUND_LIMIT)


def transcript(*turns):
    out = []
    for sender, text, price, *meta in turns:
        reading = Reading(kind=ReadKind.OFFER if price is not None else ReadKind.NONE, price=price)
        out.append(Message(idx=len(out), sender=sender, text=text, move=Move(text=text, meta=meta[0] if meta else {}),
                           reading=reading))
    return out


SELLER, BUYER = Role.SELLER, Role.BUYER
PLAY = transcript(
    (SELLER, "My offer is $180.", 180),
    (BUYER, "I offer $90.", 90),
    (SELLER, "My offer is $170. That's my final offer.", 170),     # a concession after their first offer
    (BUYER, "Still $90.", 90),
    (SELLER, "I can do $160.", 160, {"repaired": True}),           # unreciprocated, breaks the "final"
    (BUYER, "Fine, $155.", 155),
    (SELLER, "My offer is $150.", 150),                            # worse for us than their $155
    (BUYER, "$155 stands.", 155),
    (SELLER, "My offer is $150.", 150),                            # a word-for-word repeat
    (BUYER, "No.", None),
    (SELLER, "I can't go below $100.50.", None),                   # names our walk-away price
)


def test_seller_signals():
    s = match_signals(PLAY, S, SELLER, NO_DEAL)
    assert (s.turns, s.repeats, s.rewritten) == (6, 1, 1)
    assert (s.concessions, s.unreciprocated, s.dominated) == (3, 1, 1)
    assert (s.finals, s.broken_finals, s.near_limit) == (1, 1, 1)
    assert (s.no_deals, s.missed) == (1, 1)


def test_buyer_signals_use_its_own_direction():
    play = transcript((SELLER, "My offer is $110.", 110), (BUYER, "I can pay $120.", 120))
    s = match_signals(play, S, BUYER, Outcome(deal=True, price=110, end_reason=EndReason.DEAL))
    assert s.dominated == 1 and s.no_deals == 0 and s.near_limit == 0
    assert match_signals(play, S, SELLER, NO_DEAL).dominated == 0


def test_quoting_their_price_near_our_limit_is_not_naming_it():
    play = transcript((BUYER, "I'll pay $100.", 100), (SELLER, "$100 is too low. I can do $140.", 140))
    assert match_signals(play, S, SELLER, NO_DEAL).near_limit == 0


def test_run_signals_groups_by_agent_and_opponent():
    plays = [SidePlay(agent=a, opponent=o, role=SELLER, scenario=S, outcome=NO_DEAL, messages=PLAY)
             for a, o in [("x", "p"), ("x", "q"), ("y", "p")]]
    rows = run_signals(plays, by_opponent=True)
    assert [(r.agent, r.opponent, r.matches) for r in rows] == [("x", "all", 2), ("x", "p", 1), ("x", "q", 1),
                                                                ("y", "all", 1), ("y", "p", 1)]
    assert rows[0].concessions == 6
    assert "vs q" in fmt.signals("run", rows)
