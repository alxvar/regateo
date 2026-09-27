import pytest

from regateo.core import ActionKind, Message, Move, Role, Rules, Scenario


def msg(idx: int, sender: Role, text: str, action: ActionKind | None = None, price: float | None = None) -> Message:
    return Message(idx=idx, sender=sender, text=text, move=Move(text=text, action=action, price=price))


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(id="s1", item="a used road bike", seller_reservation=100, buyer_reservation=150,
                    market_low=80, market_high=180, rules=Rules(max_rounds=4, deadline_known=False))
