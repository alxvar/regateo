"""Platform with an explicit action and price field next to the message text."""
from __future__ import annotations

from regateo.protocol.base import TurnProtocol


class StructuredProtocol(TurnProtocol):
    name = "structured"
    structured = True

    def describe(self) -> str:
        return ("Each message carries an action (offer, accept, reject, message, walk_away) and, "
                "for offers, a price. A deal closes when one side accepts the other's standing offer.")
