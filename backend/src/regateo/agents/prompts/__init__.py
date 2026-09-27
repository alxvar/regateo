"""Versioned prompt templates. Files are `<name>.v<N>.md`; `$placeholders` are filled with string.Template."""
from __future__ import annotations

from functools import cache
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


@cache
def _load(name: str, version: int) -> Template:
    return Template((_DIR / f"{name}.v{version}.md").read_text())


def render(name: str, version: int = 1, **values: object) -> str:
    """Fill a template. Missing placeholders raise, so a prompt never ships with `$gaps`."""
    return _load(name, version).substitute({k: str(v) for k, v in values.items()}).strip()
