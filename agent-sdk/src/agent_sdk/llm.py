"""Model access for agents: requests, responses, errors, and the client an agent is handed.

Agents never build clients themselves: they ask their context (`ctx.llm(profile, stage)`), which
returns one that meters cost, enforces the run's budget, caches and couples paired matches.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

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
    temperature: float | None = None               # overrides the profile's (OpenAI-API providers; Claude ignores it)
    seed: int | None = None                        # sampling seed (OpenAI-API providers; Claude ignores it)
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


@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, req: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    """Any failed model call. Catch it and fall back to a safe move: an exception from an agent
    ends the match as an error."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LLMTimeout(LLMError):
    def __init__(self, message: str = "model call timed out"):
        super().__init__(message, retryable=True)


class LLMRateLimited(LLMError):
    def __init__(self, message: str = "rate limited", *, retry_after_s: float | None = None):
        super().__init__(message, retryable=True, status=429)
        self.retry_after_s = retry_after_s


class LLMRefusal(LLMError):
    def __init__(self, message: str = "model refused", *, category: str | None = None):
        super().__init__(message)
        self.category = category


class LLMBadOutput(LLMError):
    """The model answered, but not in the requested shape (schema mismatch, truncated JSON)."""

    def __init__(self, message: str, *, text: str = ""):
        super().__init__(message)
        self.text = text
