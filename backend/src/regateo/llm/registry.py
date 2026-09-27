"""Build clients from profile names. One shared, rate-limited client per profile per event loop."""
from __future__ import annotations

import asyncio

from regateo.core.config import load_env
from regateo.llm.client import LLMClient
from regateo.llm.limits import LimitedClient
from regateo.llm.profiles import ModelProfile, load_profile

_clients: dict[tuple[int, str], LimitedClient] = {}


def build_provider(profile: ModelProfile) -> LLMClient:
    if profile.provider == "anthropic":
        from regateo.llm.providers.anthropic import AnthropicProvider
        return AnthropicProvider(profile)
    if profile.provider == "openai":
        from regateo.llm.providers.openai import OpenAIProvider
        return OpenAIProvider(profile)
    if profile.provider == "fake":
        from regateo.llm.providers.fake import FakeProvider
        return FakeProvider.from_profile(profile)
    raise ValueError(f"unknown provider {profile.provider!r}")


def get_client(profile: str | ModelProfile) -> LimitedClient:
    """Shared client for a profile, so every match using it shares one concurrency cap.

    Wrap the result per use: `CachedClient` for record/replay, then `Meter.wrap` for cost.
    Clients are keyed by event loop because asyncio primitives are loop-bound.
    """
    load_env()
    if isinstance(profile, str):
        profile = load_profile(profile)
    key = (id(asyncio.get_running_loop()), profile.name)
    if key not in _clients:
        # Overall cap covers the SDK's own retries; each attempt is capped by profile.timeout_s.
        overall = profile.timeout_s * (profile.max_retries + 1)
        _clients[key] = LimitedClient(build_provider(profile), profile.max_concurrency, overall)
    return _clients[key]
