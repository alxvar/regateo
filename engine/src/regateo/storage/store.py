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
from regateo.core.messages import Message, Move, Reading
from regateo.core.outcome import Outcome
from regateo.core.scenario import Scenario
from regateo.llm.types import LLMCallRecord

SCHEMA_VERSION = 2
# Added on open rather than by a version bump: processes still running older code (a resumed gym, the dashboard)
# refuse a newer schema version, and an extra table doesn't affect them.
REASONING_DDL = ("CREATE TABLE IF NOT EXISTS llm_reasoning (call_id INTEGER PRIMARY KEY REFERENCES llm_calls(id), "
                 "text TEXT NOT NULL)")


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
    async def open(cls, path: str | Path | None = None, *, readonly: bool = False) -> Store:
        """`readonly` is for reader processes (the API) while a run writes from another process."""
        path = Path(path) if path else data_dir() / "regateo.db"
        conn = await asyncio.to_thread(_connect, path, readonly)
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
            c.execute("INSERT INTO messages (match_id, idx, sender, text, move, t, latency_s, reading)"
                      " VALUES (?,?,?,?,?,?,?,?)",
                      (match_id, m.idx, m.sender.value, m.text, m.move.model_dump_json(), m.t, m.latency_s,
                       m.reading.model_dump_json() if m.reading else None))
            c.commit()
        await self._run(q)

    async def finish_match(self, match_id: str, outcome: Outcome, *, cost_usd: float = 0.0,
                           status: str = "done", meta: dict[str, Any] | None = None) -> None:
        """`meta` is merged into the match's meta (e.g. referee disagreements)."""
        def q(c: sqlite3.Connection) -> None:
            if meta:
                (raw,) = c.execute("SELECT meta FROM matches WHERE id = ?", (match_id,)).fetchone()
                c.execute("UPDATE matches SET meta = ? WHERE id = ?",
                          (json.dumps({**json.loads(raw or "{}"), **meta}, default=str), match_id))
            c.execute(
                "UPDATE matches SET status=?, outcome=?, deal=?, price=?, seller_share=?, buyer_share=?,"
                " end_reason=?, cost_usd=?, ended_at=? WHERE id=?",
                (status, outcome.model_dump_json(), int(outcome.deal), outcome.price, outcome.seller_share,
                 outcome.buyer_share, outcome.end_reason.value, cost_usd, time.time(), match_id))
            c.commit()
        await self._run(q)

    async def reset_match(self, match_id: str) -> None:
        """Forget a partially played match so it can be replayed (resume after a crash)."""
        def q(c: sqlite3.Connection) -> None:
            c.execute("DELETE FROM messages WHERE match_id = ?", (match_id,))
            c.execute("DELETE FROM llm_reasoning WHERE call_id IN (SELECT id FROM llm_calls WHERE match_id = ?)",
                      (match_id,))
            c.execute("DELETE FROM llm_calls WHERE match_id = ?", (match_id,))
            c.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            c.commit()
        await self._run(q)

    async def delete_run(self, run_id: str) -> int:
        """Remove a run with its matches, messages, model calls and thinking traces. Returns the number of
        matches removed. The response cache is separate, so replays of its requests stay free."""
        def q(c: sqlite3.Connection) -> int:
            if c.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
                raise KeyError(run_id)
            matches = "SELECT id FROM matches WHERE run_id = ?"
            c.execute(f"DELETE FROM llm_reasoning WHERE call_id IN (SELECT id FROM llm_calls WHERE match_id IN "
                      f"({matches}))", (run_id,))
            c.execute(f"DELETE FROM llm_calls WHERE match_id IN ({matches})", (run_id,))
            c.execute(f"DELETE FROM messages WHERE match_id IN ({matches})", (run_id,))
            n = c.execute("DELETE FROM matches WHERE run_id = ?", (run_id,)).rowcount
            c.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            c.commit()
            return n
        return await self._run(q)

    async def update_run_config(self, run_id: str, patch: dict[str, Any]) -> None:
        def q(c: sqlite3.Connection) -> None:
            (raw,) = c.execute("SELECT config FROM runs WHERE id = ?", (run_id,)).fetchone()
            c.execute("UPDATE runs SET config = ? WHERE id = ?",
                      (json.dumps({**json.loads(raw), **patch}, default=str), run_id))
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
            if rec.reasoning:
                c.execute("INSERT INTO llm_reasoning (call_id, text) VALUES (last_insert_rowid(), ?)",
                          (rec.reasoning,))
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
                        move=Move.model_validate_json(r["move"]), t=r["t"], latency_s=r["latency_s"],
                        reading=Reading.model_validate_json(r["reading"])
                        if "reading" in r.keys() and r["reading"] else None)   # absent in v1 files opened read-only
                for r in rows]

    async def match_statuses(self, run_id: str) -> dict[str, str]:
        rows = await self._run(lambda c: c.execute(
            "SELECT id, status FROM matches WHERE run_id = ?", (run_id,)).fetchall())
        return {r["id"]: r["status"] for r in rows}

    async def messages_since(self, match_id: str, after_idx: int) -> list[Message]:
        return [m for m in await self.match_messages(match_id) if m.idx > after_idx]

    async def run_progress(self, run_id: str) -> dict[str, Any]:
        def q(c: sqlite3.Connection) -> dict[str, Any]:
            by_status = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM matches WHERE run_id = ? GROUP BY status", (run_id,))}
            agg = c.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS cost, COALESCE(SUM(deal), 0) AS deals,"
                " MAX(COALESCE(ended_at, started_at)) AS last FROM matches WHERE run_id = ?", (run_id,)).fetchone()
            tokens = c.execute(
                "SELECT COALESCE(SUM(l.input_tokens + l.cache_read_tokens + l.cache_write_tokens), 0) AS inp,"
                " COALESCE(SUM(l.output_tokens), 0) AS out, COUNT(l.id) AS calls"
                " FROM llm_calls l JOIN matches m ON m.id = l.match_id WHERE m.run_id = ?", (run_id,)).fetchone()
            run = c.execute("SELECT status, config FROM runs WHERE id = ?", (run_id,)).fetchone()
            total = json.loads(run["config"]).get("total_matches") if run else None
            return {"status": run["status"] if run else None, "total": total, "by_status": by_status,
                    "done": by_status.get("done", 0), "cost_usd": agg["cost"], "deals": agg["deals"],
                    "last_update": agg["last"], "input_tokens": tokens["inp"], "output_tokens": tokens["out"],
                    "llm_calls": tokens["calls"]}
        return await self._run(q)

    async def overview(self) -> dict[str, Any]:
        def q(c: sqlite3.Connection) -> dict[str, Any]:
            runs = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) AS n FROM runs GROUP BY kind")}
            m = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(deal), 0) AS deals, COALESCE(SUM(cost_usd), 0)"
                          " AS cost FROM matches WHERE status = 'done'").fetchone()
            t = c.execute("SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens + cache_read_tokens"
                          " + cache_write_tokens), 0) AS inp, COALESCE(SUM(output_tokens), 0) AS out"
                          " FROM llm_calls").fetchone()
            running = c.execute("SELECT COUNT(*) FROM runs WHERE status = 'running'").fetchone()[0]
            return {"runs": runs, "running_runs": running, "matches": m["n"], "deals": m["deals"],
                    "cost_usd": m["cost"], "llm_calls": t["calls"], "input_tokens": t["inp"],
                    "output_tokens": t["out"]}
        return await self._run(q)

    async def match_llm_calls(self, match_id: str) -> list[LLMCallRecord]:
        rows = await self._run(lambda c: c.execute(
            "SELECT l.*, COALESCE(r.text, '') AS reasoning FROM llm_calls l LEFT JOIN llm_reasoning r"
            " ON r.call_id = l.id WHERE l.match_id = ? ORDER BY l.id", (match_id,)).fetchall())
        return [LLMCallRecord(
            profile=r["profile"], provider=r["provider"], model=r["model"], tags=json.loads(r["tags"]),
            usage={"input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
                   "cache_read_tokens": r["cache_read_tokens"], "cache_write_tokens": r["cache_write_tokens"]},
            cost_usd=r["cost_usd"], latency_s=r["latency_s"], cached=bool(r["cached"]), error=r["error"],
            reasoning=r["reasoning"],
        ) for r in rows]

    async def run_reasoning(self, run_id: str) -> list[dict[str, Any]]:
        """Every stored thinking trace of a run's matches, oldest first: the call's match, tags, profile, tokens,
        error and the trace."""
        def q(c: sqlite3.Connection) -> list[sqlite3.Row]:
            return c.execute(
                "SELECT l.id, l.match_id, l.profile, l.tags, l.input_tokens, l.output_tokens, l.latency_s, l.cached,"
                " l.error, l.created_at, r.text FROM llm_reasoning r JOIN llm_calls l ON l.id = r.call_id"
                " JOIN matches m ON m.id = l.match_id WHERE m.run_id = ? ORDER BY l.id", (run_id,)).fetchall()
        return [{"call_id": r["id"], "match_id": r["match_id"], "profile": r["profile"], "tags": json.loads(r["tags"]),
                 "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "latency_s": r["latency_s"],
                 "cached": bool(r["cached"]), "error": r["error"], "created_at": r["created_at"],
                 "reasoning": r["text"]} for r in await self._run(q)]


def _connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
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
    elif version == 1:
        conn.execute("ALTER TABLE messages ADD COLUMN reading TEXT")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    elif version != SCHEMA_VERSION:
        raise RuntimeError(f"{path}: schema version {version}, expected {SCHEMA_VERSION}")
    conn.execute(REASONING_DDL)
    conn.commit()
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
