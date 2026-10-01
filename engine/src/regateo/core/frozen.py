"""Frozen files: prompts, profiles, agent versions, agent configs and benches that have benchmark results.

Editing one would silently change what a stored result means, so configs/frozen.json keeps their
hashes and a unit test fails on any change. Change behaviour by adding a new version instead
(`agents/single_call/v2/`, `qwen-local-think.yaml`, `standard-v2.yaml`). An agent version is frozen as
a whole (its code and prompts, agent_sdk.packages.code_hash); new configs may still be added to it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_sdk import packages

from regateo.core.config import REPO_DIR, agents_dir, configs_dir


def manifest_path() -> Path:
    return configs_dir() / "frozen.json"


def _version(path: Path) -> str | None:
    """`single_call/v1` when `path` is an agent version's folder."""
    try:
        rel = path.resolve().relative_to(agents_dir().resolve()).as_posix()
    except ValueError:
        return None
    return rel if packages.is_version(rel) else None


def _hash(path: Path) -> str | None:
    if (kind := _version(path)) is not None:
        packages.mount(agents_dir())
        return packages.code_hash(kind) if path.is_dir() else None
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def load() -> dict[str, str]:
    """{path relative to the repo: hash}."""
    p = manifest_path()
    return json.loads(p.read_text()) if p.exists() else {}


def changed() -> list[str]:
    """Frozen files and agent versions that were edited or deleted."""
    return [rel for rel, digest in load().items() if _hash(REPO_DIR / rel) != digest]


def freeze(paths: list[Path]) -> list[str]:
    """Add files or agent version folders to the manifest (or re-freeze them). Returns their manifest keys."""
    entries = load()
    keys = []
    for p in paths:
        rel = p.resolve().relative_to(REPO_DIR).as_posix()
        digest = _hash(REPO_DIR / rel)
        if digest is None:
            raise ValueError(f"{rel}: not a file or an agent version folder")
        entries[rel] = digest
        keys.append(rel)
    manifest_path().write_text(json.dumps(dict(sorted(entries.items())), indent=2) + "\n")
    return keys
