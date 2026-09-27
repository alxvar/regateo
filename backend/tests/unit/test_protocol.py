import random

from regateo.core import ActionKind, FirstMover, Move, Role, Rules, Scenario
from regateo.protocol import get_protocol
from tests.conftest import msg


def test_freetext_drops_structure_and_meta():
    p = get_protocol("freetext")
    move = Move(text="  $150 please  ", action=ActionKind.OFFER, price=150, meta={"rationale": "secret"})
    n = p.normalise(move, Rules())
    assert n.text == "$150 please" and n.action is None and n.price is None and n.meta
    assert p.delivered(n) == Move(text="$150 please")


def test_structured_keeps_fields_but_not_meta():
    p = get_protocol("structured")
    d = p.delivered(Move(text="x", action=ActionKind.OFFER, price=150, meta={"reservation": 100}))
    assert d.price == 150 and d.meta == {}


def test_length_cap_and_view():
    p = get_protocol("freetext")
    assert len(p.normalise(Move(text="a" * 5000), Rules(max_message_chars=100)).text) == 100
    h = [msg(0, Role.SELLER, "hi"), msg(1, Role.BUYER, "yo")]
    h[0].move.meta["plan"] = "hold at 170"
    seen_by_buyer = p.view_of(h, Role.BUYER)
    assert seen_by_buyer[0].move.meta == {} and p.view_of(h, Role.SELLER)[0].move.meta


def test_first_mover():
    s = Scenario(id="x", item="i", seller_reservation=1, buyer_reservation=2, market_low=0, market_high=3,
                 rules=Rules(first_mover=FirstMover.BUYER))
    assert get_protocol("structured").first_mover(s, random.Random(0)) is Role.BUYER
