"""Ids and seeds."""
from __future__ import annotations

import hashlib
import os
import time


def new_id(prefix: str = "") -> str:
    """Time-sortable id: 12 hex digits of milliseconds, then 8 random hex digits."""
    ms = int(time.time() * 1000)
    return f"{prefix}{ms:012x}{os.urandom(4).hex()}"


def derive_seed(root: int, *keys: object) -> int:
    """Deterministic child seed, so paired runs can share scenarios and randomness.
    63 bits, so it fits a signed SQLite INTEGER."""
    blob = ":".join([str(root), *map(str, keys)]).encode()
    return int.from_bytes(hashlib.sha256(blob).digest()[:8], "big") >> 1
