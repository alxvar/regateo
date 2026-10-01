"""Select a protocol by name from config."""
from __future__ import annotations

from regateo.protocol.base import TurnProtocol
from regateo.protocol.freetext import FreeTextProtocol
from regateo.protocol.structured import StructuredProtocol

PROTOCOLS: dict[str, type[TurnProtocol]] = {
    StructuredProtocol.name: StructuredProtocol,
    FreeTextProtocol.name: FreeTextProtocol,
}


def get_protocol(name: str) -> TurnProtocol:
    try:
        return PROTOCOLS[name]()
    except KeyError:
        raise ValueError(f"unknown protocol {name!r}; known: {sorted(PROTOCOLS)}") from None
