"""What agents send (moves) and what the match records (messages, transcripts)."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from regateo.core.roles import Role


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
    idx: int                                   # 0-based position in the transcript
    sender: Role
    text: str                                  # as delivered to the other side
    move: Move                                 # as produced by the sender
    t: float = 0.0                             # seconds since match start when delivered
    latency_s: float = 0.0                     # time the sender took to produce it

    @property
    def round(self) -> int:
        return self.idx // 2


class Transcript(BaseModel):
    messages: list[Message] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.messages)

    def append(self, message: Message) -> None:
        self.messages.append(message)

    def last(self, sender: Role | None = None) -> Message | None:
        for m in reversed(self.messages):
            if sender is None or m.sender is sender:
                return m
        return None

    def by(self, sender: Role) -> list[Message]:
        return [m for m in self.messages if m.sender is sender]
