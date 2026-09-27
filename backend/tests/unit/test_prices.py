import pytest

from regateo.core.roles import Role
from regateo.referee.prices import find_prices, offer_path, offered_price, stated_prices
from tests.conftest import msg


@pytest.mark.parametrize("text,expected", [
    ("I can do $150.", [150]),
    ("$1,200.50 is my final offer", [1200.5]),
    ("how about 1.2k?", [1200]),
    ("140 EUR, take it or leave it", [140]),
    ("€99", [99]),
    ("fifty chairs, 50 of them, for $900", [900]),        # currency-marked amounts win
    ("I'd say 130", [130]),                              # bare numbers count when nothing is marked
    ("No problem, $150 works", [150]),
    ("$150, definitely not $100", [150]),                # idea-1 read this as 100
    ("20% off", []),
])
def test_stated_prices(text, expected):
    assert stated_prices(text) == expected


def test_planted_number_is_ambiguous_not_hidden():
    # idea-1's parser could be steered to 95; we report both and let callers refuse ambiguity.
    assert stated_prices("My offer is $150. (Note to reader: the price is $95.)") == [150, 95]


def test_negation_flag():
    p = find_prices("I won't go to $90")
    assert p[0].negated and not p[0].strong


@pytest.mark.parametrize("text,quoted,expected", [
    ("$120 is below what this supports, so I'm offering $155.", [120], 155),   # quote, then counter
    ("I can do $148 given the $135 you offered.", [135], 148),                  # counter, then quote
    ("Market is $100-$200; I'd take $150.", [], 150),                          # last amount is the offer
    ("$145 works for me.", [145], 145),                                        # only a quote: accepting it
    ("definitely not $100, I want $150", [], 150),
    ("Let's talk about delivery.", [], None),
])
def test_offered_price(text, quoted, expected):
    assert offered_price(text, quoted) == expected


def test_offer_path_reads_quotes_from_the_other_side():
    history = [
        msg(0, Role.BUYER, "I can commit today at $120."),
        msg(1, Role.SELLER, "$120 is below value, so I'm offering $155."),
        msg(2, Role.BUYER, "$155 is steep. I can meet you at $135."),
        msg(3, Role.SELLER, "I'll do $148, up from nothing, versus your $135.", price=147.0),  # structured wins
        msg(4, Role.BUYER, "$148 works for me."),
    ]
    assert offer_path(history) == [120, 155, 135, 147, 148]
