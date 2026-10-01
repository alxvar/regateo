"""What an agent sends each turn (a move), and the conversation it is shown (messages)."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent_sdk.roles import Role


class ActionKind(StrEnum):
    OFFER = "offer"
    ACCEPT = "accept"
    REJECT = "reject"
    MESSAGE = "message"          # talk without a new price (questions, arguments)
    WALK_AWAY = "walk_away"


class Move(BaseModel):
    """One agent's output for one turn.

    `text` is what the opponent may see. `action` and `price` are our structured intent:
    the platform may accept them (structured protocol) or ignore them (free text), but the
    match always records them. `meta` holds agent internals for logs only (strategy object,
    rationale, stage traces) and never reaches the opponent.
    """

    text: str
    action: ActionKind | None = None
    price: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """One message in the conversation, as the agent is shown it: its own messages in full,
    the opponent's as the platform delivered them."""

    idx: int                                   # 0-based position in the conversation
    sender: Role
    text: str                                  # as delivered to the other side
    move: Move                                 # as produced by the sender (opponent's: only what was delivered)
    t: float = 0.0                             # seconds since match start when delivered
    latency_s: float = 0.0                     # time the sender took to produce it

    @property
    def round(self) -> int:
        return self.idx // 2
