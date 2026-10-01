"""Frozen files: prompts, profiles, agents and benches that have benchmark results.

Editing one would silently change what a stored result means, so configs/frozen.json keeps
their hashes and a unit test fails on any change. Change behaviour by adding a new version
(`negotiator_system.v2.md`, `qwen-local-think.yaml`, `standard-v2.yaml`) instead.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from regateo.core.config import ENGINE_DIR, configs_dir


def manifest_path() -> Path:
    return configs_dir() / "frozen.json"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load() -> dict[str, str]:
    """{path relative to engine/: sha256}."""
    p = manifest_path()
    return json.loads(p.read_text()) if p.exists() else {}


def changed() -> list[str]:
    """Frozen files that were edited or deleted."""
    return [rel for rel, digest in load().items()
            if not (ENGINE_DIR / rel).exists() or _hash(ENGINE_DIR / rel) != digest]


def freeze(paths: list[Path]) -> list[str]:
    """Add files to the manifest (or re-freeze them). Returns their manifest keys."""
    entries = load()
    keys = []
    for p in paths:
        rel = p.resolve().relative_to(ENGINE_DIR).as_posix()
        entries[rel] = _hash(ENGINE_DIR / rel)
        keys.append(rel)
    manifest_path().write_text(json.dumps(dict(sorted(entries.items())), indent=2) + "\n")
    return keys
