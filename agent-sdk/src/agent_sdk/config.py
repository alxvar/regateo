"""The settings one agent is built with: one config file of its version."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    name: str                                              # label in reports, e.g. single_call-v1-baseline
    model: str | None = None                               # model profile for ctx.llm, e.g. qwen-local
    params: dict[str, Any] = Field(default_factory=dict)   # everything else that changes behaviour
