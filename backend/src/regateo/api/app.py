"""Read-only HTTP API over the store, for the UI. Runs are started from the CLI.

Live views poll the SQLite WAL database, so they work while another process (the CLI)
is writing a run.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from regateo.arena.report import build_arena_report
from regateo.core.config import REPO_DIR
from regateo.core.messages import Message
from regateo.gym.report import build_gym_report
from regateo.referee.prices import offer_path
from regateo.storage.store import Store

POLL_S = 1.0


def create_app(db_path: str | Path, *, ui_dir: Path | None = None, poll_s: float = POLL_S) -> FastAPI:
    db_path = Path(db_path)
    ui_dir = ui_dir or REPO_DIR / "ui" / "dist"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not db_path.exists():                     # create the schema once, then read only
            await (await Store.open(db_path)).close()
        app.state.store = await Store.open(db_path, readonly=True)
        yield
        await app.state.store.close()

    app = FastAPI(title="regateo", lifespan=lifespan)

    def store(request: Request) -> Store:
        return request.app.state.store

    @app.get("/api/overview")
    async def overview(request: Request) -> dict[str, Any]:
        return await store(request).overview()

    @app.get("/api/runs")
    async def runs(request: Request, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        s = store(request)
        return [{**r.model_dump(), "progress": await s.run_progress(r.id)} for r in await s.list_runs(kind, limit)]

    @app.get("/api/runs/{run_id}")
    async def run(request: Request, run_id: str) -> dict[str, Any]:
        s = store(request)
        r = await s.get_run(run_id)
        if r is None:
            raise HTTPException(404, f"no run {run_id}")
        return {**r.model_dump(), "progress": await s.run_progress(run_id)}

    @app.get("/api/runs/{run_id}/matches")
    async def run_matches(request: Request, run_id: str) -> list[dict[str, Any]]:
        rows = await store(request).list_matches(run_id)
        return [_match_summary(r) for r in rows]

    @app.get("/api/runs/{run_id}/report")
    async def run_report(request: Request, run_id: str) -> dict[str, Any]:
        s = store(request)
        r = await s.get_run(run_id)
        if r is None:
            raise HTTPException(404, f"no run {run_id}")
        if r.kind == "gym":
            return {"kind": "gym", "report": (await build_gym_report(s, run_id)).model_dump()}
        if r.kind == "arena":
            return {"kind": "arena", "report": (await build_arena_report(s, run_id)).model_dump()}
        return {"kind": r.kind, "report": None}

    @app.get("/api/matches/{match_id}")
    async def match(request: Request, match_id: str) -> dict[str, Any]:
        s = store(request)
        row = await s.get_match(match_id)
        if row is None:
            raise HTTPException(404, f"no match {match_id}")
        return {"match": row.model_dump(), "messages": _with_offers(await s.match_messages(match_id)),
                "llm_calls": [c.model_dump() for c in await s.match_llm_calls(match_id)]}

    @app.get("/api/matches/{match_id}/stream")
    async def match_stream(request: Request, match_id: str, after: int = -1) -> StreamingResponse:
        s = store(request)

        async def events() -> AsyncIterator[str]:
            last = after
            while not await request.is_disconnected():
                if await s.messages_since(match_id, last):
                    # Offers are read against earlier messages, so annotate the whole transcript.
                    for m in _with_offers(await s.match_messages(match_id)):
                        if m["idx"] > last:
                            last = m["idx"]
                            yield _sse("message", json.dumps(m))
                row = await s.get_match(match_id)
                if row is None or row.status != "running":
                    yield _sse("end", row.model_dump_json() if row else "null")
                    return
                await asyncio.sleep(poll_s)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/runs/{run_id}/stream")
    async def run_stream(request: Request, run_id: str) -> StreamingResponse:
        s = store(request)

        async def events() -> AsyncIterator[str]:
            while not await request.is_disconnected():
                progress = await s.run_progress(run_id)
                yield _sse("progress", json.dumps(progress))
                if progress["status"] != "running":
                    yield _sse("end", json.dumps(progress))
                    return
                await asyncio.sleep(poll_s)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    if ui_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=ui_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            file = ui_dir / path
            return FileResponse(file if path and file.is_file() else ui_dir / "index.html")

    return app


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _match_summary(r: Any) -> dict[str, Any]:
    o = r.outcome
    return {
        "id": r.id, "status": r.status, "scenario_id": r.scenario.id, "item": r.scenario.item,
        "seller": r.seller.name, "buyer": r.buyer.name, "protocol": r.protocol, "meta": r.meta,
        "deal": o.deal if o else None, "price": o.price if o else None,
        "end_reason": o.end_reason.value if o else None, "messages": o.messages if o else None,
        "seller_share": o.seller_share if o else None, "buyer_share": o.buyer_share if o else None,
        "past_reservation": o.past_reservation.value if o and o.past_reservation else None,
        "cost_usd": r.cost_usd, "started_at": r.started_at, "ended_at": r.ended_at,
    }


def _with_offers(messages: list[Message]) -> list[dict[str, Any]]:
    """Messages as JSON, each with `offer`: the price it puts forward, as the referee reads it."""
    return [m.model_dump(mode="json") | {"offer": p} for m, p in zip(messages, offer_path(messages), strict=True)]
