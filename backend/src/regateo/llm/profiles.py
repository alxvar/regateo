"""Model profiles: named, config-file descriptions of a model endpoint and its settings."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from regateo.core.config import configs_dir, load_yaml
from regateo.llm.types import Usage


class Price(BaseModel):
    """USD per million tokens."""

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0

    def cost(self, usage: Usage) -> float:
        return (usage.input_tokens * self.input
                + usage.output_tokens * self.output
                + usage.cache_read_tokens * self.cache_read
                + usage.cache_write_tokens * self.cache_write) / 1_000_000


class ModelProfile(BaseModel):
    name: str
    provider: Literal["anthropic", "openai", "fake"]
    model: str
    base_url: str | None = None
    api_key_env: str | None = None      # None: the SDK resolves credentials itself
    max_tokens: int = 4096
    effort: str | None = None
    thinking: dict[str, Any] | None = None   # anthropic, e.g. {"type": "adaptive"}
    max_concurrency: int = 8                 # in-flight calls across all matches sharing this profile
    timeout_s: float = 120.0                 # per attempt
    max_retries: int = 2                     # SDK-level retries on 408/409/429/5xx and connection errors
    price: Price = Field(default_factory=Price)
    extra: dict[str, Any] = Field(default_factory=dict)   # passed through to the SDK call


def load_profile(name_or_path: str | Path) -> ModelProfile:
    path = Path(name_or_path)
    if path.suffix not in (".yaml", ".yml"):
        path = configs_dir() / "models" / f"{name_or_path}.yaml"
    return load_yaml(path, ModelProfile)
