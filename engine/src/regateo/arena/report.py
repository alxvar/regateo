"""Arena report: leaderboard with ratings, and the pairwise results matrix."""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from regateo.core.roles import Role
from regateo.stats import Estimate, bradley_terry, match_score, mean_ci, wilson
from regateo.storage.store import Store


class Standing(BaseModel):
    rank: int
    label: str
    rating: float
    mean_share: Estimate
    deal_rate: Estimate
    matches: int
    past_reservation: int
    errors: int


class Cell(BaseModel):
    row: str
    col: str
    mean_share: float                  # row agent's mean share against col agent
    n: int


class ArenaReport(BaseModel):
    run_id: str
    name: str
    status: str
    total: int | None
    done: int
    leaderboard: list[Standing]
    matrix: list[Cell]
    cost_usd: float


async def build_arena_report(store: Store, run_id: str) -> ArenaReport:
    run = await store.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    rows = [r for r in await store.list_matches(run_id) if r.status == "done" and r.outcome]
    progress = await store.run_progress(run_id)

    shares: dict[str, list[float]] = defaultdict(list)
    deals: dict[str, int] = defaultdict(int)
    past: dict[str, int] = defaultdict(int)
    errors: dict[str, int] = defaultdict(int)
    vs: dict[tuple[str, str], list[float]] = defaultdict(list)
    results = []
    for r in rows:
        o = r.outcome
        assert o is not None
        s_label, b_label = r.meta["seller"], r.meta["buyer"]
        for label, role, opp in ((s_label, Role.SELLER, b_label), (b_label, Role.BUYER, s_label)):
            shares[label].append(o.share(role))
            vs[(label, opp)].append(o.share(role))
            deals[label] += o.deal
            past[label] += o.past_reservation is role
            errors[label] += o.error_by is role
        results.append((s_label, b_label, match_score(o.seller_share, o.buyer_share, o.deal)))

    ratings = bradley_terry(results)
    labels = sorted(shares, key=lambda k: -ratings.get(k, 0))
    board = [Standing(rank=n + 1, label=k, rating=ratings.get(k, 1500), mean_share=mean_ci(shares[k]),
                      deal_rate=wilson(deals[k], len(shares[k])), matches=len(shares[k]),
                      past_reservation=past[k], errors=errors[k]) for n, k in enumerate(labels)]
    matrix = [Cell(row=a, col=b, mean_share=sum(v) / len(v), n=len(v)) for (a, b), v in sorted(vs.items())]
    return ArenaReport(run_id=run_id, name=run.name, status=run.status, total=progress["total"],
                       done=progress["done"], leaderboard=board, matrix=matrix, cost_usd=progress["cost_usd"])
