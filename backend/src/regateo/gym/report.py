"""Gym report, rebuilt from stored matches so the CLI, API and UI agree."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel

from regateo.core.outcome import EndReason
from regateo.core.roles import Role, other
from regateo.stats import Estimate, PairedResult, mean_ci, paired_test, wilson
from regateo.storage.store import MatchRow, Store


class SideStats(BaseModel):
    label: str
    matches: int
    mean_share: Estimate
    deal_rate: Estimate
    past_reservation: int            # deals that broke this side's walk-away price
    errors: int                      # matches this side's agent crashed


class Breakdown(BaseModel):
    key: str
    a: Estimate
    b: Estimate
    diff: PairedResult


class GymReport(BaseModel):
    run_id: str
    name: str
    mode: str
    status: str
    total: int | None
    done: int
    a: SideStats
    b: SideStats
    diff: PairedResult               # paired A - B
    by_opponent: list[Breakdown]
    by_role: list[Breakdown]
    by_cell: list[Breakdown]
    cost_usd: float
    input_tokens: int
    output_tokens: int


class _Obs(BaseModel):
    """One side's result in one match."""
    share: float
    deal: bool
    past: bool
    error: bool


def _obs(row: MatchRow, role: Role) -> _Obs:
    o = row.outcome
    assert o is not None
    return _Obs(share=o.share(role), deal=o.deal, past=o.past_reservation is role,
                error=o.end_reason is EndReason.ERROR and o.error_by is role)


def _side(label: str, xs: list[_Obs]) -> SideStats:
    return SideStats(label=label, matches=len(xs), mean_share=mean_ci([x.share for x in xs]),
                     deal_rate=wilson(sum(x.deal for x in xs), len(xs)),
                     past_reservation=sum(x.past for x in xs), errors=sum(x.error for x in xs))


def _breakdown(groups: dict[str, list[tuple[float, float]]]) -> list[Breakdown]:
    out = []
    for key in sorted(groups):
        pairs = groups[key]
        out.append(Breakdown(key=key, a=mean_ci([a for a, _ in pairs]), b=mean_ci([b for _, b in pairs]),
                             diff=paired_test([a - b for a, b in pairs])))
    return out


def gym_pairs(rows: Iterable[MatchRow], mode: str) -> tuple[list[_Obs], list[_Obs], list[dict]]:
    """Per-side observations, and one record per complete pair: {a, b, opponent, role, cell}."""
    by_pair: dict[str, list[MatchRow]] = defaultdict(list)
    for r in rows:
        if r.status == "done" and r.outcome:
            by_pair[r.meta["pair"]].append(r)
    a_obs, b_obs, pairs = [], [], []
    for group in by_pair.values():
        if len(group) != 2:
            continue                                  # incomplete pair: excluded from paired stats
        if mode == "duel":
            a_side, b_side = [], []
            for r in group:
                a_role = Role(r.meta["a_role"])
                a_side.append(_obs(r, a_role))
                b_side.append(_obs(r, other(a_role)))
            a_obs += a_side
            b_obs += b_side
            pairs.append({"a": sum(x.share for x in a_side) / 2, "b": sum(x.share for x in b_side) / 2,
                          "opponent": "-", "role": "both", "cell": group[0].meta["cell"]})
        else:
            by_subject = {r.meta["subject"]: r for r in group}
            role = Role(group[0].meta["role"])
            oa, ob = _obs(by_subject["a"], role), _obs(by_subject["b"], role)
            a_obs.append(oa)
            b_obs.append(ob)
            pairs.append({"a": oa.share, "b": ob.share, "opponent": group[0].meta["opponent"],
                          "role": role.value, "cell": group[0].meta["cell"]})
    return a_obs, b_obs, pairs


async def build_gym_report(store: Store, run_id: str) -> GymReport:
    run = await store.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    rows = await store.list_matches(run_id)
    progress = await store.run_progress(run_id)
    mode = run.config.get("mode", "duel")
    a_label = run.config.get("a", {}).get("name") or _label(run.config.get("a", {}))
    b_label = run.config.get("b", {}).get("name") or _label(run.config.get("b", {}))
    a_obs, b_obs, pairs = gym_pairs(rows, mode)

    def group(key: str) -> dict[str, list[tuple[float, float]]]:
        g: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for p in pairs:
            g[p[key]].append((p["a"], p["b"]))
        return g

    return GymReport(
        run_id=run_id, name=run.name, mode=mode, status=run.status,
        total=progress["total"], done=progress["done"],
        a=_side(a_label, a_obs), b=_side(b_label, b_obs),
        diff=paired_test([p["a"] - p["b"] for p in pairs]),
        by_opponent=_breakdown(group("opponent")) if mode == "benchmark" else [],
        by_role=_breakdown(group("role")) if mode == "benchmark" else [],
        by_cell=_breakdown(group("cell")),
        cost_usd=progress["cost_usd"], input_tokens=progress["input_tokens"],
        output_tokens=progress["output_tokens"],
    )


def _label(spec: dict) -> str:
    kind, model = spec.get("kind", "?"), spec.get("model")
    return f"{kind}@{model}" if model else kind
