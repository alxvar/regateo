"""Provider-neutral request and response types."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """One model call. Anything not set here falls back to the model profile."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: list[ChatMessage]
    system: str | None = None
    max_tokens: int | None = None
    output_schema: type[BaseModel] | None = None   # set: the response is parsed into this model
    effort: str | None = None                      # low | medium | high | xhigh | max (providers that support it)
    tags: dict[str, str] = Field(default_factory=dict)   # attribution (match id, stage); not sent to the model

    @classmethod
    def of(cls, prompt: str, *, system: str | None = None, **kw: Any) -> LLMRequest:
        return cls(messages=[ChatMessage(role="user", content=prompt)], system=system, **kw)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


class LLMResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str
    parsed: BaseModel | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    provider: str = ""
    profile: str = ""
    model: str = ""                  # the model that actually answered (may differ after a fallback)
    stop_reason: str | None = None
    cached: bool = False             # served from the record/replay cache


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
