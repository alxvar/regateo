"""Agent specs, per-match context, and the registry that builds agents from specs."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from regateo.core.agent import Agent, AgentRef
from regateo.core.config import configs_dir, load_yaml
from regateo.core.roles import Role
from regateo.core.scenario import PrivateView, Rules
from regateo.llm.client import LLMClient
from regateo.protocol.base import TurnProtocol


class AgentSpec(BaseModel):
    """What to build: a registry kind plus its settings. Stored with every match via `ref()`."""

    kind: str                              # o1 | o2 | boulware | scripted:<name> | persona:<name>
    model: str | None = None               # model profile, for LLM agents
    params: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    version: str = "1"

    @property
    def label(self) -> str:
        return self.name or (f"{self.kind}@{self.model}" if self.model else self.kind)

    def ref(self) -> AgentRef:
        return AgentRef(name=self.label, version=self.version,
                        config={"kind": self.kind, "model": self.model, "params": self.params})

    @classmethod
    def resolve(cls, value: str | dict[str, Any] | AgentSpec) -> AgentSpec:
        """A spec, a dict, the name of configs/agents/<name>.yaml, or a bare kind like `scripted:liar`."""
        if isinstance(value, AgentSpec):
            return value
        if isinstance(value, dict):
            return cls.model_validate(value)
        path = configs_dir() / "agents" / f"{value}.yaml"
        if Path(path).exists():
            spec = load_yaml(path, cls)
            return spec if spec.name else spec.model_copy(update={"name": value})
        return cls(kind=value)


LLMFactory = Callable[[str, str], LLMClient]   # (profile, stage) -> client tagged for this match


@dataclass
class AgentContext:
    role: Role
    rng: random.Random
    protocol: TurnProtocol
    true_rules: Rules                      # the real rules; only scripted sparring partners may peek
    llm_factory: LLMFactory | None = None

    def llm(self, profile: str | None, stage: str) -> LLMClient:
        if not profile:
            raise ValueError("this agent needs a model profile (spec.model)")
        if self.llm_factory is None:
            raise RuntimeError("no LLM factory in this context")
        return self.llm_factory(profile, stage)


Builder = Callable[[AgentSpec, PrivateView, AgentContext], Agent]
_REGISTRY: dict[str, Builder] = {}


def register(kind: str) -> Callable[[Builder], Builder]:
    """Register a builder for `kind`. A kind ending in ':' handles every `kind<variant>`."""
    def deco(fn: Builder) -> Builder:
        _REGISTRY[kind] = fn
        return fn
    return deco


def build_agent(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> Agent:
    builder = _REGISTRY.get(spec.kind)
    if builder is None and ":" in spec.kind:
        builder = _REGISTRY.get(spec.kind.split(":", 1)[0] + ":")
    if builder is None:
        raise ValueError(f"unknown agent kind {spec.kind!r}; known: {sorted(_REGISTRY)}")
    return builder(spec, view, ctx)


def known_kinds() -> list[str]:
    return sorted(_REGISTRY)
