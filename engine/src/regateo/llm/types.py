"""Provider-neutral request and response types. Those agents use are defined in the agent SDK."""
from __future__ import annotations

from agent_sdk.llm import ChatMessage, LLMRequest, LLMResponse, Usage
from pydantic import BaseModel, Field

__all__ = ["ChatMessage", "LLMCallRecord", "LLMRequest", "LLMResponse", "Usage"]


class LLMCallRecord(BaseModel):
    """One call as seen by the meter; what storage writes to llm_calls."""

    profile: str
    provider: str
    model: str
    tags: dict[str, str] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None
    reasoning: str = ""              # the model's thinking (stored apart, in llm_reasoning)
