"""The agent interface. Implementations live in regateo.agents; the match only knows this."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from regateo.core.messages import Message, Move
from regateo.core.scenario import PrivateView


class Abort(Exception):  # noqa: N818
    """Raised from inside an agent to stop the whole match for a reason that isn't the agent's
    fault (e.g. the run's budget is spent). The match engine re-raises it instead of scoring."""


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


class AgentRef(BaseModel):
    """Stable identity of an agent configuration, stored with every match."""

    name: str
    version: str = "0"
    config: dict[str, Any] = Field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        blob = json.dumps(self.config, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:12]

    @property
    def key(self) -> str:
        """Identity for comparisons: two refs with the same key are the same agent."""
        return f"{self.name}@{self.version}#{self.config_hash}"
