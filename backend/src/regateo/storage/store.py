"""SQLite store for runs, matches, transcripts and model calls.

One connection per Store, all access serialised through a lock and run in a worker thread,
so hundreds of concurrent matches can write without blocking the event loop. WAL mode lets
the API process read while a run is writing.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from regateo.core.agent import AgentRef
from regateo.core.config import data_dir
from regateo.core.ids import new_id
from regateo.core.messages import Message, Move
from regateo.core.outcome import Outcome
from regateo.core.scenario import Scenario
from regateo.llm.types import LLMCallRecord

SCHEMA_VERSION = 1


class RunRow(BaseModel):
    id: str
    kind: str
    name: str
    config: dict[str, Any]
    status: str
    created_at: float
    ended_at: float | None


class MatchRow(BaseModel):
    id: str
    run_id: str | None
    scenario: Scenario
    seed: int | None
    seller: AgentRef
    buyer: AgentRef
    protocol: str
    status: str
    outcome: Outcome | None
    cost_usd: float
    meta: dict[str, Any]
    started_at: float
    ended_at: float | None


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: str | Path | None = None) -> Store:
        path = Path(path) if path else data_dir() / "regateo.db"
        conn = await asyncio.to_thread(_connect, path)
        return cls(conn)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.close)

    async def _run(self, fn, *args):  # type: ignore[no-untyped-def]
        async with self._lock:
            return await asyncio.to_thread(fn, self._conn, *args)

    # ---- writes -------------------------------------------------------------------------

    async def create_run(self, kind: str, name: str, config: dict[str, Any] | None = None,
                         run_id: str | None = None) -> str:
        run_id = run_id or new_id("run_")

        def q(c: sqlite3.Connection) -> None:
            c.execute("INSERT INTO runs (id, kind, name, config, status, created_at) VALUES (?,?,?,?,?,?)",
                      (run_id, kind, name, json.dumps(config or {}, default=str), "running", time.time()))
            c.commit()
        await self._run(q)
        return run_id

    async def finish_run(self, run_id: str, status: str = "done") -> None:
        def q(c: sqlite3.Connection) -> None:
            c.execute("UPDATE runs SET status = ?, ended_at = ? WHERE id = ?", (status, time.time(), run_id))
            c.commit()
        await self._run(q)

    async def start_match(self, *, scenario: Scenario, seller: AgentRef, buyer: AgentRef, protocol: str,
                          run_id: str | None = None, seed: int | None = None,
                          meta: dict[str, Any] | None = None, match_id: str | None = None) -> str:
        match_id = match_id or new_id("m_")

        def q(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO matches (id, run_id, scenario_id, scenario, seed, seller, buyer, seller_key,"
                " buyer_key, protocol, status, meta, started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, run_id, scenario.id, scenario.model_dump_json(), seed,
                 seller.model_dump_json(), buyer.model_dump_json(), seller.key, buyer.key, protocol,
                 "running", json.dumps(meta or {}, default=str), time.time()))
            c.commit()
        await self._run(q)
        return match_id

    async def append_message(self, match_id: str, m: Message) -> None:
        def q(c: sqlite3.Connection) -> None:
            c.execute("INSERT INTO messages (match_id, idx, sender, text, move, t, latency_s)"
                      " VALUES (?,?,?,?,?,?,?)",
                      (match_id, m.idx, m.sender.value, m.text, m.move.model_dump_json(), m.t, m.latency_s))
            c.commit()
        await self._run(q)

    async def finish_match(self, match_id: str, outcome: Outcome, *, cost_usd: float = 0.0,
                           status: str = "done") -> None:
        def q(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE matches SET status=?, outcome=?, deal=?, price=?, seller_share=?, buyer_share=?,"
                " end_reason=?, cost_usd=?, ended_at=? WHERE id=?",
                (status, outcome.model_dump_json(), int(outcome.deal), outcome.price, outcome.seller_share,
                 outcome.buyer_share, outcome.end_reason.value, cost_usd, time.time(), match_id))
            c.commit()
        await self._run(q)

    async def record_llm_call(self, rec: LLMCallRecord) -> None:
        """Meter sink. The match id is taken from the `match` tag, if set."""
        def q(c: sqlite3.Connection) -> None:
            u = rec.usage
            c.execute(
                "INSERT INTO llm_calls (match_id, profile, provider, model, tags, input_tokens, output_tokens,"
                " cache_read_tokens, cache_write_tokens, cost_usd, latency_s, cached, error, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec.tags.get("match"), rec.profile, rec.provider, rec.model, json.dumps(rec.tags),
                 u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens, rec.cost_usd,
                 rec.latency_s, int(rec.cached), rec.error, time.time()))
            c.commit()
        await self._run(q)

    # ---- reads --------------------------------------------------------------------------

    async def list_runs(self, kind: str | None = None, limit: int = 100) -> list[RunRow]:
        def q(c: sqlite3.Connection) -> list[sqlite3.Row]:
            if kind:
                return c.execute("SELECT * FROM runs WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                                 (kind, limit)).fetchall()
            return c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_run_row(r) for r in await self._run(q)]

    async def get_run(self, run_id: str) -> RunRow | None:
        rows = await self._run(lambda c: c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchall())
        return _run_row(rows[0]) if rows else None

    async def list_matches(self, run_id: str) -> list[MatchRow]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM matches WHERE run_id = ? ORDER BY started_at", (run_id,)).fetchall())
        return [_match_row(r) for r in rows]

    async def get_match(self, match_id: str) -> MatchRow | None:
        rows = await self._run(lambda c: c.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchall())
        return _match_row(rows[0]) if rows else None

    async def match_messages(self, match_id: str) -> list[Message]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM messages WHERE match_id = ? ORDER BY idx", (match_id,)).fetchall())
        return [Message(idx=r["idx"], sender=r["sender"], text=r["text"],
                        move=Move.model_validate_json(r["move"]), t=r["t"], latency_s=r["latency_s"])
                for r in rows]

    async def match_llm_calls(self, match_id: str) -> list[LLMCallRecord]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM llm_calls WHERE match_id = ? ORDER BY id", (match_id,)).fetchall())
        return [LLMCallRecord(
            profile=r["profile"], provider=r["provider"], model=r["model"], tags=json.loads(r["tags"]),
            usage={"input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
                   "cache_read_tokens": r["cache_read_tokens"], "cache_write_tokens": r["cache_write_tokens"]},
            cost_usd=r["cost_usd"], latency_s=r["latency_s"], cached=bool(r["cached"]), error=r["error"],
        ) for r in rows]


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(Path(__file__).with_name("schema.sql").read_text())
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    elif version != SCHEMA_VERSION:
        raise RuntimeError(f"{path}: schema version {version}, expected {SCHEMA_VERSION}")
    return conn


def _run_row(r: sqlite3.Row) -> RunRow:
    return RunRow(id=r["id"], kind=r["kind"], name=r["name"], config=json.loads(r["config"]),
                  status=r["status"], created_at=r["created_at"], ended_at=r["ended_at"])


def _match_row(r: sqlite3.Row) -> MatchRow:
    return MatchRow(
        id=r["id"], run_id=r["run_id"],
        scenario=Scenario.model_validate_json(r["scenario"]), seed=r["seed"],
        seller=AgentRef.model_validate_json(r["seller"]), buyer=AgentRef.model_validate_json(r["buyer"]),
        protocol=r["protocol"], status=r["status"],
        outcome=Outcome.model_validate_json(r["outcome"]) if r["outcome"] else None,
        cost_usd=r["cost_usd"], meta=json.loads(r["meta"] or "{}"),
        started_at=r["started_at"], ended_at=r["ended_at"],
    )
