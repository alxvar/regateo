"""Run many matches concurrently, with a budget, a shared LLM cache, and resume after a crash."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from regateo.agents import AgentContext, AgentSpec, build_agent
from regateo.core.agent import Abort
from regateo.core.config import data_dir
from regateo.core.ids import derive_seed
from regateo.core.outcome import EndReason, Outcome
from regateo.core.roles import Role
from regateo.core.scenario import Scenario
from regateo.llm.cache import CachedClient, CacheMode
from regateo.llm.client import LLMClient
from regateo.llm.metering import Meter
from regateo.llm.registry import get_client
from regateo.match.clock import RealClock, SimClock
from regateo.match.engine import run_match
from regateo.protocol.registry import get_protocol
from regateo.referee.detect import ShadowDetector
from regateo.referee.registry import build_detector, build_reader
from regateo.storage.store import Store

log = logging.getLogger(__name__)


class MatchJob(BaseModel):
    key: str                                   # unique within a run; the match id is <run_id>-<key>
    scenario: Scenario
    seller: AgentSpec
    buyer: AgentSpec
    protocol: str = "structured"
    detector: str = "structured"
    reader: str = "rules"                      # how messages are read (referee.registry.build_reader)
    seed: int = 0
    sim_clock: bool = False                    # simulated latency instead of wall-clock time
    meta: dict[str, Any] = Field(default_factory=dict)


class RunSettings(BaseModel):
    concurrency: int = 16                      # matches in flight; LLM calls are capped per profile too
    budget_usd: float | None = None
    cache: CacheMode = CacheMode.OFF


class RunSummary(BaseModel):
    total: int
    done: int = 0
    failed: int = 0
    skipped: int = 0                           # already done (resume) or not started (budget)
    cost_usd: float = 0.0
    budget_exhausted: bool = False


Progress = Callable[[RunSummary], None]


def match_id(run_id: str, job: MatchJob) -> str:
    return f"{run_id}-{job.key}"


class _Clients:
    """One cached-or-plain client per profile for the whole run, wrapped per match by the meter."""

    def __init__(self, meter: Meter, cache: CacheMode):
        self.meter = meter
        self.cache = cache
        self._base: dict[str, LLMClient] = {}

    def base(self, profile: str) -> LLMClient:
        if profile not in self._base:
            client: LLMClient = get_client(profile)
            if self.cache is not CacheMode.OFF:
                client = CachedClient(client, data_dir() / "llm_cache.db", self.cache, salt_tags=("match", "role"))
            self._base[profile] = client
        return self._base[profile]

    def for_match(self, mid: str, role: str, agent: str) -> Callable[[str, str], LLMClient]:
        def factory(profile: str, stage: str) -> LLMClient:
            return self.meter.wrap(self.base(profile), match=mid, role=role, agent=agent, stage=stage)
        return factory


async def run_jobs(jobs: list[MatchJob], *, store: Store, run_id: str, settings: RunSettings | None = None,
                   on_progress: Progress | None = None) -> RunSummary:
    settings = settings or RunSettings()
    if len({j.key for j in jobs}) != len(jobs):
        raise ValueError("job keys must be unique within a run")
    summary = RunSummary(total=len(jobs))
    await store.update_run_config(run_id, {"total_matches": len(jobs)})

    statuses = await store.match_statuses(run_id)
    todo = []
    for job in jobs:
        mid = match_id(run_id, job)
        if statuses.get(mid) == "done":
            summary.skipped += 1
            continue
        if mid in statuses:
            await store.reset_match(mid)          # half-played before a crash: replay from scratch
        todo.append(job)

    meter = Meter(budget_usd=settings.budget_usd, sink=store.record_llm_call)
    clients = _Clients(meter, settings.cache)
    sem = asyncio.Semaphore(settings.concurrency)
    stop = asyncio.Event()

    async def one(job: MatchJob) -> None:
        async with sem:
            if stop.is_set():
                summary.skipped += 1
                return
            try:
                status = await _play(job, store, run_id, clients, meter)
            except Abort:
                stop.set()
                summary.budget_exhausted = True
                status = "failed"
            except Exception:
                log.exception("match %s crashed", match_id(run_id, job))
                status = "failed"
            if status == "done":
                summary.done += 1
            else:
                summary.failed += 1
            summary.cost_usd = meter.cost_usd
            if on_progress:
                on_progress(summary)

    await asyncio.gather(*(one(j) for j in todo))
    return summary


async def _play(job: MatchJob, store: Store, run_id: str, clients: _Clients, meter: Meter) -> str:
    mid = match_id(run_id, job)
    scenario = job.scenario
    protocol = get_protocol(job.protocol)
    specs = {Role.SELLER: job.seller, Role.BUYER: job.buyer}
    agents = {}
    for role, spec in specs.items():
        ctx = AgentContext(
            role=role,
            rng=random.Random(derive_seed(job.seed, role.value)),
            protocol=protocol,
            true_rules=scenario.rules,
            llm_factory=clients.for_match(mid, role.value, spec.label),
        )
        agents[role] = build_agent(spec, scenario.view_for(role), ctx)
    referee_llm = clients.for_match(mid, "referee", "referee")
    detector = build_detector(job.detector, lambda profile: referee_llm(profile, "referee"))
    reader = build_reader(job.reader, lambda profile: referee_llm(profile, "reader"))

    await store.start_match(scenario=scenario, seller=job.seller.ref(), buyer=job.buyer.ref(),
                            protocol=job.protocol, run_id=run_id, seed=job.seed, meta=job.meta, match_id=mid)
    try:
        result = await run_match(
            scenario, agents[Role.SELLER], agents[Role.BUYER],
            protocol=protocol, detector=detector, rng=random.Random(derive_seed(job.seed, "match")),
            clock=SimClock(seed=derive_seed(job.seed, "clock")) if job.sim_clock else RealClock(),
            store=store, match_id=mid, reader=reader,
        )
    except Abort as e:
        await store.finish_match(mid, Outcome(deal=False, end_reason=EndReason.ERROR, detail=f"aborted: {e}"),
                                 cost_usd=meter.by_tag.get(f"match={mid}", 0.0), status="failed")
        raise
    extra = None
    if isinstance(detector, ShadowDetector) and detector.disagreements:
        extra = {"referee_disagreements": [
            {"idx": idx, "shadow": name, "primary": a.model_dump() if a else None, "alt": b.model_dump() if b else None}
            for idx, name, a, b in detector.disagreements]}
    await store.finish_match(mid, result.outcome, cost_usd=meter.by_tag.get(f"match={mid}", 0.0), meta=extra)
    return "done"
