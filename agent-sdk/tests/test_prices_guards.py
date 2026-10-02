from agent_sdk import ActionKind, PrivateView, Role
from agent_sdk.guards import limit_problems, past_limit, reads_as_agreement, standing_problems
from agent_sdk.prices import find_prices, fmt_price, stated_prices

SELLER = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80, market_high=180,
                     max_rounds=4, time_limit_s=None)


def test_prices():
    assert stated_prices("$150, definitely not $100") == [150]
    assert stated_prices("50 chairs for $900") == [900]
    assert stated_prices("$130 per unit, $6,500 total") == [130]
    assert [p.value for p in find_prices("1.2k or 2 million dollars")] == [1200, 2_000_000]
    assert fmt_price(1250) == "$1,250" and fmt_price(99.5, "EUR") == "€99.50" and fmt_price(7, "CHF") == "7 CHF"


def test_limit_problems():
    assert limit_problems(SELLER, "offer", 120, "I can do $120.", None) == []
    assert "past your walk-away" in limit_problems(SELLER, ActionKind.OFFER, 95, "$95", None)[0]
    assert limit_problems(SELLER, "offer", None, "Lower it is.", None) == ["an offer needs a price."]
    # an acceptance is checked at the price it names and at their standing offer as we read it
    assert limit_problems(SELLER, "accept", 120, "Deal.", 95)
    assert limit_problems(SELLER, "accept", None, "Deal.", None) == ["there is no offer from the other side to accept."]
    no = "$95 is far too low. $170 is fair."
    assert limit_problems(SELLER, "reject", None, no, 95, mentions=False) == []
    assert "$95" in limit_problems(SELLER, "reject", None, no, 95)[0]
    assert limit_problems(SELLER, "offer", 160, "$160 if you pick up within 2 days.", None) == []
    assert past_limit(SELLER, 99) and not past_limit(SELLER, 100)


def test_reads_as_agreement():
    assert reads_as_agreement("Ready to ship the moment we agree. $150.")
    assert reads_as_agreement("I can't accept that.")
    assert not reads_as_agreement("I can do $150.")


def test_standing_problems():
    buyer = SELLER.model_copy(update={"role": Role.BUYER, "reservation": 150})
    assert "already better for you" in standing_problems(SELLER, "offer", 120, 130)[0]   # seller below their bid
    assert standing_problems(SELLER, "offer", 140, 130) == []
    assert standing_problems(SELLER, "offer", 130, 130) == []
    assert "$91" in standing_problems(buyer, ActionKind.OFFER, 135, 91)[0]               # buyer above their ask
    assert standing_problems(buyer, "offer", 85, 91) == []
    assert standing_problems(SELLER, "accept", 120, 130) == []
    assert standing_problems(SELLER, "offer", 120, None) == []
