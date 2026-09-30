"""Versioned prompt templates. Files are `<name>.v<N>.md`; `$placeholders` are filled with string.Template.

A prompt is referred to as `<name>.v<N>`, or `<name>` for v1. Once a version has benchmark
results, it is frozen (configs/frozen.json): change it by adding the next version.
"""
from __future__ import annotations

import hashlib
import re
from functools import cache
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


def path(ref: str) -> Path:
    """File for `name.vN` (or `name`, meaning v1)."""
    name = ref if re.search(r"\.v\d+$", ref) else f"{ref}.v1"
    p = _DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"no prompt {ref!r} ({p.name})")
    return p


def _load(ref: str) -> str:
    # Keyed by the file's state, not only its name: the climb loop writes, removes and rewrites prompt
    # versions within one process, and a stale text would render (and fingerprint) the wrong prompt.
    p = path(ref)
    st = p.stat()
    return _read(p, st.st_mtime_ns, st.st_size)


@cache
def _read(p: Path, mtime_ns: int, size: int) -> str:
    return p.read_text()


def render(ref: str, **values: object) -> str:
    """Fill a template. Missing placeholders raise, so a prompt never ships with `$gaps`."""
    return Template(_load(ref)).substitute({k: str(v) for k, v in values.items()}).strip()


def fingerprint(ref: str) -> str:
    """Hash of the template text, so an edited prompt is a different agent."""
    return hashlib.sha256(_load(ref).encode()).hexdigest()[:12]
