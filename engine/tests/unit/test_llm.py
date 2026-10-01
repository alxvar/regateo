import asyncio

import pytest
from pydantic import BaseModel

from regateo.llm import (
    BudgetExceeded,
    CachedClient,
    CacheMode,
    LLMBadOutput,
    LLMRequest,
    LLMTimeout,
    Meter,
    load_profile,
)
from regateo.llm.limits import LimitedClient
from regateo.llm.profiles import Price
from regateo.llm.providers.fake import FakeProvider
from regateo.llm.providers.openai import strip_thinking
from regateo.llm.registry import get_client
from regateo.llm.types import LLMResponse, Usage


class Offer(BaseModel):
    price: float
    note: str = ""


async def test_fake_scripted_and_structured():
    fake = FakeProvider(["hello", Offer(price=150)])
    assert (await fake.complete(LLMRequest.of("hi"))).text == "hello"
    r = await fake.complete(LLMRequest.of("offer?", output_schema=Offer))
    assert r.parsed == Offer(price=150)
    with pytest.raises(LLMBadOutput):
        await FakeProvider(["not json"]).complete(LLMRequest.of("x", output_schema=Offer))


async def test_limiter_caps_in_flight_and_times_out():
    peak = 0
    inner = FakeProvider(lambda req: "ok", delay_s=0.02)
    limited = LimitedClient(inner, max_concurrency=3)

    async def call():
        nonlocal peak
        task = asyncio.create_task(limited.complete(LLMRequest.of("x")))
        await asyncio.sleep(0.005)
        peak = max(peak, limited.in_flight)
        await task

    await asyncio.gather(*(call() for _ in range(10)))
    assert peak == 3 and len(inner.requests) == 10
    with pytest.raises(LLMTimeout):
        await LimitedClient(FakeProvider(["x"], delay_s=0.2), 1, timeout_s=0.01).complete(LLMRequest.of("x"))


class Priced(FakeProvider):
    async def complete(self, req):
        r = await super().complete(req)
        return r.model_copy(update={"cost_usd": 0.4})


async def test_meter_budget_tags_and_sink():
    seen = []

    async def sink(rec):
        seen.append(rec)

    meter = Meter(budget_usd=1.0, sink=sink)
    client = meter.wrap(Priced(lambda req: "ok"), match="m1")
    for _ in range(3):
        await client.complete(LLMRequest.of("x", tags={"stage": "writer"}))
    assert meter.cost_usd == pytest.approx(1.2) and meter.calls == 3
    assert meter.by_tag["match=m1"] == pytest.approx(1.2) and meter.by_tag["stage=writer"] == pytest.approx(1.2)
    assert seen[0].tags == {"match": "m1", "stage": "writer"}
    with pytest.raises(BudgetExceeded):
        await client.complete(LLMRequest.of("x"))


async def test_meter_records_errors():
    meter = Meter()
    with pytest.raises(LLMTimeout):
        await meter.wrap(FakeProvider([LLMTimeout()])).complete(LLMRequest.of("x"))
    assert meter.errors == 1


async def test_cache_replays(tmp_path):
    inner = Priced(lambda req: Offer(price=len(req.messages[0].content)))
    cached = CachedClient(inner, tmp_path / "c.db", CacheMode.READWRITE)
    first = await cached.complete(LLMRequest.of("abc", output_schema=Offer))
    again = await cached.complete(LLMRequest.of("abc", output_schema=Offer, tags={"other": "tag"}))
    assert len(inner.requests) == 1 and again.cached and again.parsed == first.parsed == Offer(price=3)
    meter = Meter()
    await meter.wrap(cached).complete(LLMRequest.of("abc", output_schema=Offer))
    assert meter.cost_usd == 0                                    # replays are free
    salted = CachedClient(inner, tmp_path / "c.db", CacheMode.READWRITE, salt="sample-2")
    await salted.complete(LLMRequest.of("abc", output_schema=Offer))
    assert len(inner.requests) == 2


def test_price_cost():
    p = Price(input=5, output=25, cache_read=0.5)
    assert p.cost(Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=2_000_000)) == 8.5


def test_profiles_load(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://gpu-box:9000/v1")
    qwen = load_profile("qwen-local")
    assert qwen.provider == "openai" and qwen.base_url == "http://gpu-box:9000/v1"
    claude = load_profile("claude-opus-5")
    assert claude.provider == "anthropic" and claude.thinking == {"type": "adaptive"}


async def test_registry_shares_one_client_per_profile():
    a, b = get_client("fake"), get_client("fake")
    assert a is b
    assert isinstance(await a.complete(LLMRequest.of("x")), LLMResponse)


def test_strip_thinking():
    assert strip_thinking("<think>hmm</think>\n{\"a\": 1}") == '{"a": 1}'
    assert strip_thinking("reasoning...</think>answer") == "answer"
    assert strip_thinking("plain") == "plain"
