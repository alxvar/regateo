import pytest

from regateo.core import EndReason, Role
from regateo.referee import DealEvent, score


def test_deal(scenario):
    o = score(scenario, DealEvent(price=140, accepted_by=Role.BUYER, idx=5, detector="t"), EndReason.DEAL,
              messages=6)
    assert o.deal and o.price == 140 and o.closed_at == 5
    assert o.seller_share == pytest.approx(0.8) and o.buyer_share == pytest.approx(0.2)
    assert o.past_reservation is None


def test_no_deal(scenario):
    o = score(scenario, None, EndReason.ROUND_LIMIT, messages=8)
    assert not o.deal and o.share(Role.SELLER) == 0 and o.share(Role.BUYER) == 0


def test_deal_past_reservation(scenario):
    o = score(scenario, DealEvent(price=90, accepted_by=Role.SELLER, idx=1, detector="t"), EndReason.DEAL,
              messages=2)
    assert o.past_reservation is Role.SELLER and o.seller_share < 0


def test_deal_reason_requires_event(scenario):
    with pytest.raises(ValueError):
        score(scenario, None, EndReason.DEAL, messages=1)
