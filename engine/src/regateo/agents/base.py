"""Agent specs, per-match context, and the registry that builds agents from specs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from agent_sdk import AgentContext
from pydantic import BaseModel, Field

from regateo.agents import prompts
from regateo.core.agent import Agent, AgentRef
from regateo.core.config import configs_dir, load_yaml_dict
from regateo.core.scenario import PrivateView, Rules
from regateo.llm.profiles import profile_fingerprint


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


@dataclass(kw_only=True)
class TrustedContext(AgentContext):
    """The context the runner builds. Only kinds registered as trusted (the engine's own scripted
    sparring partners) receive it whole; every other agent gets `public()`, the agent SDK's context."""
    true_rules: Rules                      # the real rules, even when the deadline is hidden from agents

    def public(self) -> AgentContext:
        return AgentContext(**{f.name: getattr(self, f.name) for f in fields(AgentContext)})


Builder = Callable[[AgentSpec, PrivateView, AgentContext], Agent]
PromptRefs = Callable[[AgentSpec], list[str]]
_REGISTRY: dict[str, Builder] = {}
_PROMPTS: dict[str, PromptRefs] = {}
_TRUSTED: set[str] = set()


def register(kind: str, prompts: PromptRefs | None = None, trusted: bool = False) -> Callable[[Builder], Builder]:
    """Register a builder for `kind`. A kind ending in ':' handles every `kind<variant>`.
    `prompts` lists the prompt files a spec of this kind will use, for its identity.
    `trusted` gives its agents the whole `TrustedContext`; only the engine's scripted opponents need it."""
    def deco(fn: Builder) -> Builder:
        _REGISTRY[kind] = fn
        if prompts:
            _PROMPTS[kind] = prompts
        if trusted:
            _TRUSTED.add(kind)
        return fn
    return deco


def _lookup(table: dict[str, Any], kind: str) -> Any:
    if kind in table:
        return table[kind]
    return table.get(kind.split(":", 1)[0] + ":") if ":" in kind else None


def prompt_refs(spec: AgentSpec) -> list[str]:
    fn = _lookup(_PROMPTS, spec.kind)
    return fn(spec) if fn else []


def build_agent(spec: AgentSpec, view: PrivateView, ctx: TrustedContext) -> Agent:
    builder = _lookup(_REGISTRY, spec.kind)
    if builder is None:
        raise ValueError(f"unknown agent kind {spec.kind!r}; known: {sorted(_REGISTRY)}")
    kind = spec.kind if spec.kind in _REGISTRY else spec.kind.split(":", 1)[0] + ":"
    return builder(spec, view, ctx if kind in _TRUSTED else ctx.public())


def known_kinds() -> list[str]:
    return sorted(_REGISTRY)
