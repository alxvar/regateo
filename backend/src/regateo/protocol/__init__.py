"""Platform adapter: message format, turn order, delivery. Changes when the organisers publish the rules."""
from regateo.protocol.base import TurnProtocol
from regateo.protocol.freetext import FreeTextProtocol
from regateo.protocol.registry import get_protocol
from regateo.protocol.structured import StructuredProtocol

__all__ = ["FreeTextProtocol", "StructuredProtocol", "TurnProtocol", "get_protocol"]
