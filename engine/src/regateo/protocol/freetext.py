"""Platform where only text is exchanged. Deals must be judged from the text itself."""
from __future__ import annotations

from regateo.protocol.base import TurnProtocol


class FreeTextProtocol(TurnProtocol):
    name = "freetext"
    structured = False

    def describe(self) -> str:
        return ("Messages are plain text. A deal closes when one side clearly accepts the other's "
                "most recent price in writing.")
