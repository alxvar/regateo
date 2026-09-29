"""Agent specs, per-match context, and the registry that builds agents from specs."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from regateo.agents import prompts
from regateo.core.agent import Agent, AgentRef
from regateo.core.config import configs_dir, load_yaml_dict
from regateo.core.roles import Role
from regateo.core.scenario import PrivateView, Rules
from regateo.llm.client import LLMClient
from regateo.llm.profiles import profile_fingerprint
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
        """Identity stored with every match. Besides the settings, it fingerprints what they point
        to (prompt files, the model profile), so editing either makes a different agent."""
        config: dict[str, Any] = {"kind": self.kind, "model": self.model, "params": self.params}
        if self.model:
            config["profile"] = profile_fingerprint(self.model)
        if refs := prompt_refs(self):
            config["prompts"] = {r: prompts.fingerprint(r) for r in refs}
        return AgentRef(name=self.label, version=self.version, config=config)

    @classmethod
    def resolve(cls, value: str | dict[str, Any] | AgentSpec) -> AgentSpec:
        """A spec, a dict, the name of configs/agents/<name>.yaml (subfolders allowed, e.g. `o1/think`),
        or a bare kind like `scripted:liar`. Files and dicts may say `extends: <agent>` to start from
        another agent's settings: its params are merged, everything else is replaced."""
        if isinstance(value, AgentSpec):
            return value
        if isinstance(value, dict):
            return cls.model_validate(_expand(value, ()))
        path = configs_dir() / "agents" / f"{value}.yaml"
        if Path(path).exists():
            data = _expand(load_yaml_dict(path), (value,))
            return cls.model_validate({"name": value.replace("/", "-"), **data})
        return cls(kind=value)


def _expand(data: dict[str, Any], seen: tuple[str, ...]) -> dict[str, Any]:
    """Resolve `extends:` chains into one flat dict. The parent's name is not inherited."""
    data = dict(data)
    parent_name = data.pop("extends", None)
    if parent_name is None:
        return data
    if parent_name in seen:
        raise ValueError(f"agent configs extend each other in a loop: {' -> '.join((*seen, parent_name))}")
    path = configs_dir() / "agents" / f"{parent_name}.yaml"
    if not path.exists():
        raise ValueError(f"`extends: {parent_name}`: no configs/agents/{parent_name}.yaml")
    parent = _expand(load_yaml_dict(path), (*seen, parent_name))
    parent.pop("name", None)
    params = {**parent.get("params", {}), **data.get("params", {})}
    return {**parent, **data, "params": params}


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
PromptRefs = Callable[[AgentSpec], list[str]]
_REGISTRY: dict[str, Builder] = {}
_PROMPTS: dict[str, PromptRefs] = {}


def register(kind: str, prompts: PromptRefs | None = None) -> Callable[[Builder], Builder]:
    """Register a builder for `kind`. A kind ending in ':' handles every `kind<variant>`.
    `prompts` lists the prompt files a spec of this kind will use, for its identity."""
    def deco(fn: Builder) -> Builder:
        _REGISTRY[kind] = fn
        if prompts:
            _PROMPTS[kind] = prompts
        return fn
    return deco


def _lookup(table: dict[str, Any], kind: str) -> Any:
    if kind in table:
        return table[kind]
    return table.get(kind.split(":", 1)[0] + ":") if ":" in kind else None


def prompt_refs(spec: AgentSpec) -> list[str]:
    fn = _lookup(_PROMPTS, spec.kind)
    return fn(spec) if fn else []


def build_agent(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> Agent:
    builder = _lookup(_REGISTRY, spec.kind)
    if builder is None:
        raise ValueError(f"unknown agent kind {spec.kind!r}; known: {sorted(_REGISTRY)}")
    return builder(spec, view, ctx)


def known_kinds() -> list[str]:
    return sorted(_REGISTRY)
