"""Record/replay cache: identical requests return the recorded response.

Makes reruns free and reproducible, e.g. re-scoring a gym run with a new referee,
or re-running a match where only our agent changed while a cached opponent replays.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from enum import StrEnum
from pathlib import Path

from regateo.llm.client import LLMClient
from regateo.llm.types import LLMRequest, LLMResponse


class CacheMode(StrEnum):
    OFF = "off"
    READ = "read"            # replay hits, call the model on a miss, don't store
    WRITE = "write"          # always call the model, store the result
    READWRITE = "readwrite"  # replay hits, call and store on a miss


def request_key(profile_name: str, req: LLMRequest, salt: str = "") -> str:
    body = {
        "profile": profile_name,
        "system": req.system,
        "messages": [m.model_dump() for m in req.messages],
        "max_tokens": req.max_tokens,
        "effort": req.effort,
        "schema": req.output_schema.model_json_schema() if req.output_schema else None,
        "salt": salt,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class CachedClient:
    """`salt` separates otherwise identical requests that should sample independently,
    e.g. the sample index when drawing several completions for one prompt."""

    def __init__(self, inner: LLMClient, path: str | Path, mode: CacheMode = CacheMode.READWRITE,
                 salt: str = ""):
        self.inner = inner
        self.profile_name = inner.profile_name
        self.provider = inner.provider
        self.mode = mode
        self.salt = salt
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
        self.hits = 0
        self.misses = 0

    def _get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _put(self, key: str, resp: LLMResponse) -> None:
        data = resp.model_dump(mode="json", exclude={"parsed"})
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?)", (key, json.dumps(data)))
            self._db.commit()

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if self.mode is CacheMode.OFF:
            return await self.inner.complete(req)
        key = request_key(self.profile_name, req, self.salt)
        if self.mode in (CacheMode.READ, CacheMode.READWRITE) and (hit := self._get(key)):
            self.hits += 1
            resp = LLMResponse.model_validate({**json.loads(hit), "cached": True})
            if req.output_schema:
                resp.parsed = req.output_schema.model_validate_json(resp.text)
            return resp
        self.misses += 1
        resp = await self.inner.complete(req)
        if self.mode in (CacheMode.WRITE, CacheMode.READWRITE):
            self._put(key, resp)
        return resp

    def close(self) -> None:
        self._db.close()
