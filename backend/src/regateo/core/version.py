"""Which code a run used: the git commit, and a hash of any uncommitted changes on top of it."""
from __future__ import annotations

import hashlib
import subprocess
from typing import Any

from regateo.core.config import REPO_DIR


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout


def code_version() -> dict[str, Any]:
    """{"commit", "dirty", "changes"}: `changes` hashes the uncommitted diff and untracked files, so two
    runs from the same dirty tree can still be told apart. Empty when git isn't available."""
    try:
        commit = _git("rev-parse", "HEAD").strip()
        diff = _git("diff", "HEAD", "--binary")
        untracked = _git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    except (OSError, subprocess.CalledProcessError):
        return {}
    h = hashlib.sha256(diff.encode())
    for name in sorted(u for u in untracked if u):
        h.update(name.encode())
        try:
            h.update((REPO_DIR / name).read_bytes())
        except OSError:
            pass
    dirty = bool(diff) or any(untracked)
    return {"commit": commit, "dirty": dirty, "changes": h.hexdigest()[:12] if dirty else None}
