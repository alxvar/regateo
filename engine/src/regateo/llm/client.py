"""The one interface every model backend and wrapper implements. Agents see only its `complete`
(agent_sdk.LLMClient)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from regateo.llm.types import LLMRequest, LLMResponse


@runtime_checkable
class LLMClient(Protocol):
    profile_name: str
    provider: str

    async def complete(self, req: LLMRequest) -> LLMResponse: ...
