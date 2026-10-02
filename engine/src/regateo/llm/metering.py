"""Usage and cost accounting, budget caps, and a hook for persisting every call."""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from regateo.llm.client import LLMClient
from regateo.llm.errors import BudgetExceeded, LLMError
from regateo.llm.types import LLMCallRecord, LLMRequest, LLMResponse, Usage

CallSink = Callable[[LLMCallRecord], Awaitable[None]]


class Meter:
    """Accumulates usage and cost. One meter per scope you want to cap (a match, a run).

    Cached responses count as zero cost: they were paid for when first recorded.
    """

    def __init__(self, budget_usd: float | None = None, sink: CallSink | None = None):
        self.budget_usd = budget_usd
        self.sink = sink
        self.cost_usd = 0.0
        self.calls = 0
        self.errors = 0
        self.usage = Usage()
        self.by_tag: dict[str, float] = defaultdict(float)   # "key=value" -> cost

    def wrap(self, client: LLMClient, **tags: str) -> MeteredClient:
        return MeteredClient(client, self, tags)

    async def record(self, rec: LLMCallRecord) -> None:
        self.calls += 1
        if rec.error:
            self.errors += 1
        cost = 0.0 if rec.cached else rec.cost_usd
        self.cost_usd += cost
        self.usage = self.usage + rec.usage
        for k, v in rec.tags.items():
            self.by_tag[f"{k}={v}"] += cost
        if self.sink:
            await self.sink(rec)

    def check(self) -> None:
        if self.budget_usd is not None and self.cost_usd >= self.budget_usd:
            raise BudgetExceeded(f"budget ${self.budget_usd:.2f} spent (${self.cost_usd:.4f})")


class MeteredClient:
    def __init__(self, inner: LLMClient, meter: Meter, tags: dict[str, str]):
        self.inner = inner
        self.meter = meter
        self.tags = tags
        self.profile_name = inner.profile_name
        self.provider = inner.provider

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.meter.check()
        tags = {**self.tags, **req.tags}
        req = req.model_copy(update={"tags": tags})
        start = time.perf_counter()
        try:
            resp = await self.inner.complete(req)
        except LLMError as e:
            await self.meter.record(LLMCallRecord(
                profile=self.profile_name, provider=self.provider, model="", tags=tags,
                latency_s=time.perf_counter() - start, error=f"{type(e).__name__}: {e}",
                reasoning=getattr(e, "reasoning", ""),
            ))
            raise
        await self.meter.record(LLMCallRecord(
            profile=self.profile_name, provider=self.provider, model=resp.model, tags=tags,
            usage=resp.usage, cost_usd=resp.cost_usd, latency_s=resp.latency_s, cached=resp.cached,
            reasoning=resp.reasoning,
        ))
        return resp
