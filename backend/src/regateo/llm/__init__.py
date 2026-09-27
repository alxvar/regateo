"""Model-facing layer: the only code that talks to models.

Typical stack for one match, innermost first:

    get_client("qwen-local")          provider + shared concurrency cap and timeout
    CachedClient(..., mode)           optional record/replay
    meter.wrap(..., match=match_id)   cost, budget cap, call log

Callers see `LLMClient.complete(LLMRequest) -> LLMResponse` and `LLMError` subclasses only.
"""
from regateo.llm.cache import CachedClient, CacheMode
from regateo.llm.client import LLMClient
from regateo.llm.errors import (
    BudgetExceeded,
    LLMBadOutput,
    LLMError,
    LLMRateLimited,
    LLMRefusal,
    LLMTimeout,
)
from regateo.llm.metering import Meter
from regateo.llm.profiles import ModelProfile, load_profile
from regateo.llm.registry import get_client
from regateo.llm.types import ChatMessage, LLMCallRecord, LLMRequest, LLMResponse, Usage

__all__ = [
    "BudgetExceeded", "CacheMode", "CachedClient", "ChatMessage", "LLMBadOutput", "LLMCallRecord",
    "LLMClient", "LLMError", "LLMRateLimited", "LLMRefusal", "LLMRequest", "LLMResponse",
    "LLMTimeout", "Meter", "ModelProfile", "Usage", "get_client", "load_profile",
]
