"""The agent interface: what the match calls each turn, and what it passes in."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from agent_sdk.messages import Message, Move
from agent_sdk.view import PrivateView


class Abort(Exception):  # noqa: N818
    """Raised from inside an agent to stop the whole match for a reason that isn't the agent's
    fault (e.g. the run's budget is spent). The match re-raises it instead of scoring. Let it
    propagate; never catch it."""


class Observation(BaseModel):
    """What an agent is given each turn."""

    view: PrivateView
    history: list[Message] = Field(default_factory=list)   # as delivered (protocol-filtered)
    incoming: str | None = None                            # the opponent's latest text, None on an opening move
    message_idx: int = 0                                   # idx the reply will get
    elapsed_s: float = 0.0
    remaining_s: float | None = None                       # None: no clock, or clock hidden


@runtime_checkable
class Agent(Protocol):
    name: str

    async def respond(self, obs: Observation) -> Move: ...
