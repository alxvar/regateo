"""Real model calls. Cost a fraction of a cent each; skipped without credentials/endpoint.

    uv run pytest -m live tests/integration
"""
import os

import pytest
from pydantic import BaseModel

from regateo.core.config import load_env
from regateo.llm import LLMRequest, get_client

load_env()
pytestmark = pytest.mark.live


class Verdict(BaseModel):
    deal: bool
    price: float | None


PROMPT = "Seller: 'I can do $170.' Buyer: 'Deal, $170 it is.' Did they agree, and at what price?"


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
async def test_claude_structured():
    r = await get_client("claude-opus-5").complete(LLMRequest.of(PROMPT, output_schema=Verdict, effort="low"))
    assert r.parsed == Verdict(deal=True, price=170) and r.cost_usd > 0


@pytest.mark.skipif(not os.environ.get("VLLM_BASE_URL"), reason="VLLM_BASE_URL not set")
async def test_local_qwen_structured():
    r = await get_client("qwen-local").complete(LLMRequest.of(PROMPT, output_schema=Verdict))
    assert r.parsed == Verdict(deal=True, price=170)
