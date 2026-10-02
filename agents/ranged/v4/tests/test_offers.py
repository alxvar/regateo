from agent_sdk import ActionKind, Message, Move, Observation, PrivateView, Role
from regateo_agents.ranged.v4.offers import our_offers

VIEW = PrivateView(role=Role.SELLER, item="bike", currency="USD", reservation=100, market_low=80, market_high=180,
                   max_rounds=4, time_limit_s=None)


def test_our_offers_in_free_text():
    """Free text drops our action and price from the history; what we meant is in the move's meta."""
    history = [
        Message(idx=0, sender=Role.SELLER, text="$170.", move=Move(text="$170.", meta={
            "intent": {"action": ActionKind.OFFER, "price": 170.0}})),
        Message(idx=1, sender=Role.BUYER, text="$110.", move=Move(text="$110.")),
        Message(idx=2, sender=Role.SELLER, text="$160.", move=Move(text="$160.", meta={
            "decision": {"action": "offer", "price": 160.0, "message": "$160."}})),
        Message(idx=3, sender=Role.BUYER, text="$115.", move=Move(text="$115.")),
        Message(idx=4, sender=Role.SELLER, text="Why?", move=Move(text="Why?", meta={
            "intent": {"action": "message", "price": None}})),
        Message(idx=5, sender=Role.BUYER, text="$120.", move=Move(text="$120.", action=ActionKind.OFFER, price=120)),
        Message(idx=6, sender=Role.SELLER, text="$150.", move=Move(text="$150.", action=ActionKind.OFFER, price=150)),
    ]
    obs = Observation(view=VIEW, history=history, message_idx=7, incoming=None)
    assert our_offers(obs) == [170.0, 160.0, 150.0]
