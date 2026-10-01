"""What agents send (moves) and what the match records (messages, transcripts).

`ActionKind` and `Move` are defined in the agent SDK; the referee's readings exist only here."""
from __future__ import annotations

from enum import StrEnum

from agent_sdk.messages import ActionKind, Move
from agent_sdk.messages import Message as AgentMessage
from agent_sdk.roles import Role
from pydantic import BaseModel, Field


class ReadKind(StrEnum):
    OFFER = "offer"              # puts a price forward
    ACCEPT = "accept"            # accepts the other side's price
    REJECT = "reject"            # refuses or walks away
    NONE = "none"                # no price move (talk, questions, restating a price)


class Reading(BaseModel):
    """What the referee reads a delivered message as. Computed once, when the message arrives
    (referee.reader), and stored, so the detector, reports and UI all agree.

    `price` is None when the message names no price, or names several and the reader could
    not tell which one is the offer.
    """

    kind: ReadKind
    price: float | None = None
    source: str = "rules"                      # structured | rules | llm
    ambiguous: bool = False                    # the rules alone could not decide
    candidates: list[float] = Field(default_factory=list)   # amounts the message names
    note: str = ""
    shadow: Reading | None = None              # a second reader's view, log-only


class Message(AgentMessage):
    """A message as the match records it: what agents are shown, plus the referee's reading."""

    reading: Reading | None = None             # referee's reading; never shown to agents


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

__all__ = ["ActionKind", "Message", "Move", "ReadKind", "Reading", "Transcript"]
