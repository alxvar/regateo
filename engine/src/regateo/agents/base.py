"""Agent specs, per-match context, and how agents are built from specs.

Two kinds of agent:
- **Agent versions** under `agents/<architecture>/<version>/` (e.g. `single_call/v1`), written against the
  agent SDK. A spec names one by its version and one of its configs: `single_call/v1/baseline` is
  `agents/single_call/v1/configs/baseline.yaml`. They are built with the SDK's `AgentContext` only.
- **The engine's own kinds** (`scripted:<name>`, `persona:<name>`, `o1`, `boulware`), registered in code
  by `regateo.opponents`. Their configs, if any, are in `configs/agents/`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from agent_sdk import AgentConfig, AgentContext, packages
from agent_sdk.prompts import PromptDir
from pydantic import BaseModel, Field

from regateo.core.agent import Agent, AgentRef
from regateo.core.config import agents_dir, configs_dir, load_yaml_dict
from regateo.core.scenario import PrivateView, Rules
from regateo.llm.profiles import profile_fingerprint


class AgentSpec(BaseModel):
    """What to build: an agent version or a registered kind, plus its settings. Stored with every match via `ref()`."""

    kind: str                              # single_call/v1 | boulware | o1 | scripted:<name> | persona:<name>
    model: str | None = None               # model profile, for LLM agents
    params: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    version: str = "1"

    @property
    def label(self) -> str:
        return self.name or (f"{self.kind}@{self.model}" if self.model else self.kind)

    def ref(self) -> AgentRef:
        """Identity stored with every match. Besides the settings, it fingerprints what they point
        to, so editing either makes a different agent: an agent version's code and prompts (one hash
        of its package), a registered kind's prompt files, and the model profile."""
        config: dict[str, Any] = {"kind": self.kind, "model": self.model, "params": self.params}
        if self.model:
            config["profile"] = profile_fingerprint(self.model)
        if packages.is_version(self.kind):
            _mount()
            config["code"] = packages.code_hash(self.kind)
        elif refs := prompt_refs(self):
            folder = _lookup(_PROMPT_DIRS, self.kind)
            config["prompts"] = {r: folder.fingerprint(r) for r in refs}
        return AgentRef(name=self.label, version=self.version, config=config)

    @classmethod
    def resolve(cls, value: str | dict[str, Any] | AgentSpec) -> AgentSpec:
        """A spec; a dict; a config name (`single_call/v1/baseline`, or `boulware` for
        configs/agents/boulware.yaml); or a bare kind (`single_call/v1`, `scripted:liar`). Configs and
        dicts may say `extends: <config>` to start from another config's settings: its params are
        merged, everything else is replaced. Inside a version's configs, a bare name means a config of
        the same version."""
        if isinstance(value, AgentSpec):
            return value
        if isinstance(value, dict):
            return cls.model_validate(_expand(value, (), None))
        path, version = _config_path(value, None)
        if path is not None:
            data = _expand(load_yaml_dict(path), (value,), version)
            if version:
                data["kind"] = version     # a version's config is always an agent of that version
            return cls.model_validate({"name": value.replace("/", "-"), **data})
        return cls(kind=value)


def _mount() -> None:
    packages.mount(agents_dir())


def _config_path(name: str, version: str | None) -> tuple[Path | None, str | None]:
    """Where config `name` lives, and the agent version it belongs to (None for an engine config).
    `version` is the version of the config that refers to it: a bare name means a config of it."""
    parts = name.split("/")
    if len(parts) == 3 and packages.is_version("/".join(parts[:2])):
        kind = "/".join(parts[:2])
        path = agents_dir() / parts[0] / parts[1] / "configs" / f"{parts[2]}.yaml"
        return (path if path.exists() else None), kind
    if version and len(parts) == 1:
        path = agents_dir() / version / "configs" / f"{name}.yaml"
        if path.exists():
            return path, version
    path = configs_dir() / "agents" / f"{name}.yaml"
    return (path if path.exists() else None), None


def _expand(data: dict[str, Any], seen: tuple[str, ...], version: str | None) -> dict[str, Any]:
    """Resolve `extends:` chains into one flat dict. The parent's name is not inherited."""
    data = dict(data)
    parent_name = data.pop("extends", None)
    if parent_name is None:
        return data
    if parent_name in seen:
        raise ValueError(f"agent configs extend each other in a loop: {' -> '.join((*seen, parent_name))}")
    path, parent_version = _config_path(parent_name, version)
    if path is None:
        raise ValueError(f"`extends: {parent_name}`: no such config")
    parent = _expand(load_yaml_dict(path), (*seen, parent_name), parent_version)
    if parent_version:
        parent["kind"] = parent_version
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
_PROMPT_DIRS: dict[str, PromptDir] = {}
_TRUSTED: set[str] = set()
_INFORMED: dict[str, tuple[str, ...]] = {}


def register(kind: str, prompts: PromptRefs | None = None, prompt_dir: PromptDir | None = None,
             trusted: bool = False, informed_by: tuple[str, ...] = ()) -> Callable[[Builder], Builder]:
    """Register one of the engine's own kinds. A kind ending in ':' handles every `kind<variant>`.
    `prompts` lists the prompt files (in `prompt_dir`) a spec of this kind will use, for its identity.
    `trusted` gives its agents the whole `TrustedContext`; only the scripted opponents need it.
    `informed_by`: for an opponent a person wrote after reading some of our agents, which ones (e.g.
    ("single_call/v1",)). Such an opponent may only play on an adversarial bench (gym.spec.check_opponents)."""
    if packages.is_version(kind):
        raise ValueError(f"{kind!r} looks like an agent version; those live under agents/, not in the registry")
    if prompts and prompt_dir is None:
        raise ValueError("a kind with prompts needs their prompt_dir")

    def deco(fn: Builder) -> Builder:
        _REGISTRY[kind] = fn
        if prompts:
            _PROMPTS[kind] = prompts
            _PROMPT_DIRS[kind] = prompt_dir
        if trusted:
            _TRUSTED.add(kind)
        if informed_by:
            _INFORMED[kind] = tuple(informed_by)
        return fn
    return deco


def _lookup(table: dict[str, Any], kind: str) -> Any:
    if kind in table:
        return table[kind]
    return table.get(kind.split(":", 1)[0] + ":") if ":" in kind else None


def informed_by(kind: str) -> tuple[str, ...]:
    """The agents whose code a registered opponent was written against; empty for blind ones."""
    return _lookup(_INFORMED, kind) or ()


def prompt_refs(spec: AgentSpec) -> list[str]:
    fn = _lookup(_PROMPTS, spec.kind)
    return fn(spec) if fn else []


def build_agent(spec: AgentSpec, view: PrivateView, ctx: TrustedContext) -> Agent:
    if packages.is_version(spec.kind):
        _mount()
        module = packages.load(spec.kind)
        return module.build(AgentConfig(name=spec.label, model=spec.model, params=spec.params), view, ctx.public())
    builder = _lookup(_REGISTRY, spec.kind)
    if builder is None:
        raise ValueError(f"unknown agent kind {spec.kind!r}; known: {sorted(_REGISTRY)}")
    kind = spec.kind if spec.kind in _REGISTRY else spec.kind.split(":", 1)[0] + ":"
    return builder(spec, view, ctx if kind in _TRUSTED else ctx.public())


def known_kinds() -> list[str]:
    """The engine's registered kinds and every agent version under agents/."""
    versions = sorted(f"{a.name}/{v.name}" for a in agents_dir().iterdir() if a.is_dir()
                      for v in a.iterdir() if packages.is_version(f"{a.name}/{v.name}"))
    return sorted(_REGISTRY) + versions
