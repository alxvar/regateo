import pytest

from regateo.referee.prices import find_prices, stated_prices


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
