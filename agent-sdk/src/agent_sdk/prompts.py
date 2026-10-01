"""Versioned prompt templates kept next to the code that uses them.

A folder holds `<name>.v<N>.md` files; `$placeholders` are filled with string.Template. A prompt is
referred to as `<name>.v<N>`, or `<name>` for v1. Each agent version keeps its own folder:

    PROMPTS = PromptDir(Path(__file__).parent / "prompts")
    system = PROMPTS.render("negotiator_system.v2", role="seller", ...)
"""
from __future__ import annotations

import hashlib
import re
from functools import cache
from pathlib import Path
from string import Template


class PromptDir:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        _check_inside_caller_architecture(self.folder)

    def path(self, ref: str) -> Path:
        """File for `name.vN` (or `name`, meaning v1)."""
        name = ref if re.search(r"\.v\d+$", ref) else f"{ref}.v1"
        p = self.folder / f"{name}.md"
        if not p.exists():
            raise FileNotFoundError(f"no prompt {ref!r} ({p.name}) in {self.folder}")
        return p

    def text(self, ref: str) -> str:
        # Keyed by the file's state, not only its name: a prompt rewritten within one process must
        # not render (or fingerprint) its old text.
        p = self.path(ref)
        st = p.stat()
        return _read(p, st.st_mtime_ns, st.st_size)

    def render(self, ref: str, **values: object) -> str:
        """Fill a template. Missing placeholders raise, so a prompt never ships with `$gaps`."""
        return Template(self.text(ref)).substitute({k: str(v) for k, v in values.items()}).strip()

    def fingerprint(self, ref: str) -> str:
        """Hash of the template text."""
        return hashlib.sha256(self.text(ref).encode()).hexdigest()[:12]


def _check_inside_caller_architecture(folder: Path) -> None:
    """An agent version may read only its own architecture's prompts. When the caller is an agent package
    (under the mounted agents folder, agent_sdk.packages), the folder must be inside the caller's architecture."""
    import sys

    ns = sys.modules.get("regateo_agents")
    if ns is None:
        return
    root = Path(ns.__path__[0]).resolve()
    caller = Path(sys._getframe(2).f_globals.get("__file__") or "").resolve()
    try:
        arch = caller.relative_to(root).parts[0]
    except (ValueError, IndexError):
        return                                   # not called from an agent package
    try:
        folder.resolve().relative_to(root / arch)
    except ValueError:
        raise PermissionError(f"an agent of {arch!r} may only read prompts inside agents/{arch}/") from None


@cache
def _read(p: Path, mtime_ns: int, size: int) -> str:
    return p.read_text()
