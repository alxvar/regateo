"""The agent interface, defined in the agent SDK, and the identity the engine stores with every match."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_sdk.agent import Abort, Agent, Observation
from pydantic import BaseModel, Field

__all__ = ["Abort", "Agent", "AgentRef", "Observation"]


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
