"""Record/replay cache: identical requests return the recorded response.

Makes reruns free and reproducible, e.g. re-scoring a gym run with a new referee,
or re-running a match where only our agent changed while a cached opponent replays.
"""
from __future__ import annotations

import asyncio
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


def request_key(profile_key: str, req: LLMRequest, salt: str = "", salt_tags: tuple[str, ...] = ()) -> str:
    """`profile_key` is the profile's fingerprint (or its name, for callers without one)."""
    body = {
        "profile": profile_key,
        "system": req.system,
        "messages": [m.model_dump() for m in req.messages],
        "max_tokens": req.max_tokens,
        "effort": req.effort,
        "schema": req.output_schema.model_json_schema() if req.output_schema else None,
        "salt": salt,
        "salt_tags": {t: req.tags.get(t) for t in salt_tags},
    }
    if req.temperature is not None:        # only when set, so older cache entries keep their keys
        body["temperature"] = req.temperature
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class CachedClient:
    """`salt` separates otherwise identical requests that should sample independently, e.g. the
    sample index. `salt_tags` does the same per request from its tags: with ("replay", "role"), two
    matches with the same prompt get independent samples, while replaying the same match hits.
    `profile_key` (a `ModelProfile.fingerprint()`) makes a changed profile setting a cache miss;
    without it the key falls back to the profile name, and editing the profile would replay stale answers."""

    def __init__(self, inner: LLMClient, path: str | Path, mode: CacheMode = CacheMode.READWRITE,
                 salt: str = "", salt_tags: tuple[str, ...] = (), profile_key: str | None = None):
        self.inner = inner
        self.profile_name = inner.profile_name
        self.profile_key = profile_key or inner.profile_name
        self.provider = inner.provider
        self.mode = mode
        self.salt = salt
        self.salt_tags = salt_tags
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
        self.hits = 0
        self.misses = 0
        # Requests being answered right now, by key: an identical request arriving meanwhile waits for that
        # answer instead of sampling its own. Coupled pairs start their matches together, so without this
        # the challenger and the reference would both miss and sample independently.
        self._inflight: dict[str, asyncio.Future[str | None]] = {}

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
        key = request_key(self.profile_key, req, self.salt, self.salt_tags)
        reads = self.mode in (CacheMode.READ, CacheMode.READWRITE)
        if reads and (hit := self._get(key)):
            return self._replay(hit, req)
        if reads and (pending := self._inflight.get(key)) is not None:
            if (answer := await asyncio.shield(pending)) is not None:
                return self._replay(answer, req)
        self.misses += 1
        fut: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._inflight.setdefault(key, fut)
        answer = None
        try:
            resp = await self.inner.complete(req)
            answer = json.dumps(resp.model_dump(mode="json", exclude={"parsed"}))
        finally:
            if self._inflight.get(key) is fut:
                del self._inflight[key]
            fut.set_result(answer)              # None on failure: whoever waited samples on its own
        if self.mode in (CacheMode.WRITE, CacheMode.READWRITE):
            self._put(key, resp)
        return resp

    def _replay(self, data: str, req: LLMRequest) -> LLMResponse:
        self.hits += 1
        resp = LLMResponse.model_validate({**json.loads(data), "cached": True})
        if req.output_schema:
            resp.parsed = req.output_schema.model_validate_json(resp.text)
        return resp

    def close(self) -> None:
        self._db.close()
