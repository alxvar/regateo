"""Concurrency cap and per-call timeout, shared by every caller of one profile."""
from __future__ import annotations

import asyncio

from regateo.llm.client import LLMClient
from regateo.llm.errors import LLMTimeout
from regateo.llm.types import LLMRequest, LLMResponse


class LimitedClient:
    """Caps in-flight calls with a semaphore. The timeout starts once a slot is acquired,
    so queueing behind other matches doesn't count against a call."""

    def __init__(self, inner: LLMClient, max_concurrency: int, timeout_s: float | None = None):
        self.inner = inner
        self.profile_name = inner.profile_name
        self.provider = inner.provider
        self.max_concurrency = max_concurrency
        self.timeout_s = timeout_s
        self._sem = asyncio.Semaphore(max_concurrency)
        self.in_flight = 0

    async def complete(self, req: LLMRequest) -> LLMResponse:
        async with self._sem:
            self.in_flight += 1
            try:
                async with asyncio.timeout(self.timeout_s):
                    return await self.inner.complete(req)
            except TimeoutError as e:
                raise LLMTimeout(f"{self.profile_name}: no response within {self.timeout_s}s") from e
            finally:
                self.in_flight -= 1
