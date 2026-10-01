"""Agents as packages: `agents/<architecture>/<version>/`, plus code shared by the architecture's
versions in `agents/<architecture>/lib/`.

A version is a Python package that defines

    def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> Agent

and keeps its prompts in `prompts/`, its variants in `configs/<name>.yaml` and its tests in `tests/`.
It is imported as `regateo_agents.<architecture>.<version>`, so it can reach its architecture's shared
code with a relative import (`from ..lib import common`).

A version's identity is the hash of its files and its architecture's `lib/`, leaving out configs,
tests and caches: any code or prompt change makes a different agent, and a copy of a version under
another number is the same one.
"""
from __future__ import annotations

import hashlib
import importlib
import re
import sys
from pathlib import Path
from types import ModuleType

NAMESPACE = "regateo_agents"
KIND = re.compile(r"^(?P<arch>[a-z][a-z0-9_]*)/(?P<version>v\d+)$")
_SKIP_DIRS = {"configs", "tests", "__pycache__"}


def split(kind: str) -> tuple[str, str]:
    """`single_call/v1` -> ("single_call", "v1")."""
    m = KIND.match(kind)
    if not m:
        raise ValueError(f"{kind!r} is not an agent version: expected <architecture>/v<N>, e.g. single_call/v1")
    return m["arch"], m["version"]


def is_version(kind: str) -> bool:
    return bool(KIND.match(kind))


def mount(root: str | Path) -> None:
    """Make the agent packages under `root` importable as `regateo_agents.*`."""
    root = str(Path(root).resolve())
    ns = sys.modules.get(NAMESPACE)
    if ns is not None and list(getattr(ns, "__path__", [])) == [root]:
        return
    for name in [n for n in sys.modules if n == NAMESPACE or n.startswith(NAMESPACE + ".")]:
        del sys.modules[name]                  # a different root: forget what was loaded from the old one
    ns = ModuleType(NAMESPACE)
    ns.__path__ = [root]
    sys.modules[NAMESPACE] = ns
    importlib.invalidate_caches()


def root() -> Path:
    ns = sys.modules.get(NAMESPACE)
    if ns is None:
        raise RuntimeError("no agents folder mounted; call agent_sdk.packages.mount(<agents folder>) first")
    return Path(ns.__path__[0])


def load(kind: str) -> ModuleType:
    """The package of version `kind`. It must define `build`."""
    arch, version = split(kind)
    if not (root() / arch / version).is_dir():
        raise ValueError(f"no agent version {kind!r} under {root()}")
    module = importlib.import_module(f"{NAMESPACE}.{arch}.{version}")
    if not callable(getattr(module, "build", None)):
        raise ValueError(f"agent version {kind!r} defines no build(config, view, ctx)")
    return module


def folder(kind: str) -> Path:
    arch, version = split(kind)
    return root() / arch / version


def code_hash(kind: str, skip: tuple[str, ...] = ()) -> str:
    """Hash of everything that makes up version `kind`'s behaviour: its files and its architecture's
    `lib/`, by path relative to the version (or `lib/...`), but not configs, tests or caches.
    `skip` leaves out more folders of the version, e.g. ("prompts",)."""
    arch, version = split(kind)
    skip_dirs = _SKIP_DIRS | set(skip)
    h = hashlib.sha256()
    for base, prefix in ((root() / arch / version, ""), (root() / arch / "lib", "lib/")):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base)
            if p.is_dir() or skip_dirs & set(rel.parts) or p.suffix == ".pyc":
                continue
            h.update(f"{prefix}{rel.as_posix()}\0".encode())
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()[:16]
