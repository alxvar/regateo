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
    clean_deal_rate: Estimate | None = None    # deals within this side's own walk-away price
    past_reservation: int            # deals that broke this side's walk-away price
    errors: int                      # matches this side's agent crashed


class Breakdown(BaseModel):
    key: str
    a: Estimate
    b: Estimate
    diff: PairedResult


class Check(BaseModel):
    """One promotion check (docs/04-hill-climbing.md §3.1)."""
    name: str                        # gain | limit | deals | opponents | gates
    status: str                      # pass | fail | warn | n/a
    detail: str


class ChallengerStats(BaseModel):
    """One challenger against the reference (B), on the pairs where both finished."""
    subject: str                     # a, a2, a3...
    side: SideStats
    reference: SideStats             # B on the same pairs
    diff: PairedResult               # paired challenger - B
    by_opponent: list[Breakdown] = []
    by_role: list[Breakdown] = []
    by_cell: list[Breakdown] = []
    gates: list[Breakdown] = []      # against each gate opponent: not scored, checked (promotion_checks)
    gate_past_reservation: int = 0   # its deals past its own limit against gate opponents
    stopped_at: int | None = None    # early stopping dropped it after this many pairs
    halved_at: int | None = None     # successive halving cut it after this many pairs
    checks: list[Check] = []


class FollowUp(BaseModel):
    """A later gym that took some of this run's challengers further, e.g. a climb round's full bench."""
    run_id: str
    name: str
    agents: list[str]                # challenger labels it ran


class GymReport(BaseModel):
    run_id: str
    name: str
    mode: str
    purpose: str = "dev"             # dev | holdout: which promotion checks apply
    tier: str | None = None
    source_run: str | None = None    # the run this one continues (a climb round's screen)
    follow_ups: list[FollowUp] = []
    status: str
    total: int | None
    done: int
    a: SideStats
    b: SideStats
    diff: PairedResult               # paired A - B
    by_opponent: list[Breakdown]
    by_role: list[Breakdown]
    by_cell: list[Breakdown]
    by_gate: list[Breakdown] = []               # benchmark mode: A - B against each gate opponent, not scored
    challengers: list[ChallengerStats] = []    # benchmark mode: A and every extra challenger vs B
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
                     clean_deal_rate=wilson(sum(x.deal and not x.past for x in xs), len(xs)),
                     past_reservation=sum(x.past for x in xs), errors=sum(x.error for x in xs))


def _breakdown(groups: dict[str, list[tuple[float, float]]]) -> list[Breakdown]:
    out = []
    for key in sorted(groups):
        pairs = groups[key]
        out.append(Breakdown(key=key, a=mean_ci([a for a, _ in pairs]), b=mean_ci([b for _, b in pairs]),
                             diff=paired_test([a - b for a, b in pairs])))
    return out


def _groups(rows: Iterable[MatchRow], gate: bool = False) -> dict[str, list[MatchRow]]:
    """Finished matches by pair: the scored ones, or with `gate` those against gate opponents."""
    by_pair: dict[str, list[MatchRow]] = defaultdict(list)
    for r in rows:
        if r.status == "done" and r.outcome and bool(r.meta.get("gate")) == gate:
            by_pair[r.meta["pair"]].append(r)
    return by_pair


def gym_pairs(rows: Iterable[MatchRow], mode: str, gate: bool = False) -> tuple[list[_Obs], list[_Obs], list[dict]]:
    """Per-side observations, and one record per complete pair: {a, b, opponent, role, cell}. Scored pairs
    only, or with `gate` the pairs against gate opponents."""
    a_obs, b_obs, pairs = [], [], []
    for group in _groups(rows, gate).values():
        if mode == "duel":
            if len(group) != 2:
                continue                              # incomplete pair: excluded from paired stats
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
            if "a" not in by_subject or "b" not in by_subject:
                continue
            role = Role(group[0].meta["role"])
            oa, ob = _obs(by_subject["a"], role), _obs(by_subject["b"], role)
            a_obs.append(oa)
            b_obs.append(ob)
            pairs.append({"a": oa.share, "b": ob.share, "opponent": group[0].meta["opponent"],
                          "role": role.value, "cell": group[0].meta["cell"]})
    return a_obs, b_obs, pairs


Paired = list[tuple[_Obs, _Obs, dict[str, str]]]


def challenger_pairs(rows: Iterable[MatchRow], gate: bool = False) -> dict[str, Paired]:
    """Benchmark mode: for each subject other than B, its result and B's on every pair both finished,
    with the pair's opponent, role and cell. Scored pairs only, or with `gate` those against gates."""
    out: dict[str, Paired] = defaultdict(list)
    for group in _groups(rows, gate).values():
        by_subject = {r.meta["subject"]: r for r in group}
        if "b" not in by_subject:
            continue
        role = Role(group[0].meta["role"])
        ob = _obs(by_subject["b"], role)
        keys = {"opponent": group[0].meta["opponent"], "role": role.value, "cell": group[0].meta["cell"]}
        for subject, r in by_subject.items():
            if subject != "b":
                out[subject].append((_obs(r, role), ob, keys))
    return out


DEAL_RATE_SLACK = 0.02       # a challenger may close this much less often than the reference
OPPONENT_DROP = 0.10         # a drop against one opponent this large is flagged even if not significant
GATE_DROP = 0.10             # a drop against one gate opponent this large fails the gate


def promotion_checks(c: ChallengerStats, *, purpose: str, tier: str | None) -> list[Check]:
    """The automatic part of the promotion rule in docs/04-hill-climbing.md §3.1. The reading audit
    (`regateo readings RUN`) and the holdout run stay with a human."""
    d = c.diff
    out = []
    if d.mean_diff is None or d.p_value is None:
        out.append(Check(name="gain", status="n/a", detail="no complete pairs"))
    elif c.stopped_at is not None:
        out.append(Check(name="gain", status="fail", detail=f"stopped early after {c.stopped_at} pairs: behind"))
    elif c.halved_at is not None:
        out.append(Check(name="gain", status="fail",
                         detail=f"{d.mean_diff:+.3f}; cut by successive halving after {c.halved_at} pairs"))
    elif tier is not None:
        out.append(Check(name="gain", status="n/a", detail=f"{d.mean_diff:+.3f}; tier {tier} doesn't promote"))
    elif purpose == "holdout":
        out.append(Check(name="gain", status="pass" if d.mean_diff > 0 else "fail",
                         detail=f"{d.mean_diff:+.3f}; holdout needs the same direction"))
    else:
        ok = d.mean_diff > 0 and d.p_value < 0.05
        out.append(Check(name="gain", status="pass" if ok else "fail", detail=f"{d.mean_diff:+.3f}, p={d.p_value:.4f}"))
    past = c.side.past_reservation + c.gate_past_reservation
    out.append(Check(name="limit", status="pass" if past == 0 else "fail",
                     detail="no deals past own limit" if past == 0 else f"{past} deals past own limit"
                     + (f" ({c.gate_past_reservation} against gates)" if c.gate_past_reservation else "")))
    # Deals within the agent's own limit: a past-limit deal already fails "limit", and counting it here would
    # reward it. Screens only drop losers, so the check waits for the promotion run.
    mine, ref = _clean(c.side), _clean(c.reference)
    if tier is not None:
        out.append(Check(name="deals", status="n/a", detail=f"tier {tier} doesn't promote"))
    elif mine is not None and ref is not None:
        out.append(Check(name="deals", status="pass" if mine >= ref - DEAL_RATE_SLACK else "fail",
                         detail=f"{100 * mine:.0f}% vs {100 * ref:.0f}% within own limit"))
    flagged = [b for b in c.by_opponent if b.diff.mean_diff is not None and b.diff.p_value is not None
               and b.diff.mean_diff < 0 and (b.diff.p_value < 0.05 or b.diff.mean_diff < -OPPONENT_DROP)]
    out.append(Check(name="opponents", status="warn" if flagged else "pass",
                     detail=", ".join(f"{b.key} {b.diff.mean_diff:+.3f} (p={b.diff.p_value:.2f})" for b in flagged)
                     or "no opponent drops significantly or by more than 0.10"))
    if c.gates:
        # Gate opponents test one weakness each (a hardliner, a liar, an injector): not scored, since gains
        # against fixed scripts don't carry over (docs/05 L5), but a candidate may not get worse at them.
        dropped = [b for b in c.gates if b.diff.mean_diff is not None and b.diff.mean_diff < -GATE_DROP]
        out.append(Check(name="gates", status="fail" if dropped else "pass",
                         detail=", ".join(f"{b.key} {b.diff.mean_diff:+.3f}" for b in dropped)
                         or f"no drop over {GATE_DROP:.2f} against {', '.join(b.key for b in c.gates)}"))
    return out


def _clean(s: SideStats) -> float | None:
    return (s.clean_deal_rate or s.deal_rate).mean


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
    labels = {"a": a_label, **{f"a{n}": spec.get("name") or _label(spec)
                               for n, spec in enumerate(run.config.get("extra", []), start=2)}}
    purpose, tier = run.config.get("purpose", "dev"), run.config.get("tier")
    stopped, halved = run.config.get("stopped", {}), run.config.get("halved") or {}
    challengers = []
    gate_obs = challenger_pairs(rows, gate=True) if mode == "benchmark" else {}
    if mode == "benchmark":
        for subject, obs in sorted(challenger_pairs(rows).items(), key=lambda kv: _subject_order(kv[0])):
            per: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
            for c, r, keys in obs:
                for dim, key in keys.items():
                    per[dim][key].append((c.share, r.share))
            stats = ChallengerStats(
                subject=subject, side=_side(labels.get(subject, subject), [c for c, _, _ in obs]),
                reference=_side(b_label, [r for _, r, _ in obs]),
                diff=paired_test([c.share - r.share for c, r, _ in obs]),
                by_opponent=_breakdown(per["opponent"]), by_role=_breakdown(per["role"]),
                by_cell=_breakdown(per["cell"]), stopped_at=stopped.get(subject),
                halved_at=halved.get(subject))
            if gated := gate_obs.get(subject):
                by_gate: dict[str, list[tuple[float, float]]] = defaultdict(list)
                for c, r, keys in gated:
                    by_gate[keys["opponent"]].append((c.share, r.share))
                stats.gates = _breakdown(by_gate)
                stats.gate_past_reservation = sum(c.past for c, _, _ in gated)
            stats.checks = promotion_checks(stats, purpose=purpose, tier=tier)
            challengers.append(stats)

    def group(key: str) -> dict[str, list[tuple[float, float]]]:
        g: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for p in pairs:
            g[p[key]].append((p["a"], p["b"]))
        return g

    follow_ups = [FollowUp(run_id=r.id, name=r.name, agents=[s.get("name") or _label(s)
                                                            for s in [r.config["a"], *r.config.get("extra", [])]])
                  for r in await store.list_runs("gym", limit=1000) if r.config.get("source_run") == run_id]

    return GymReport(
        run_id=run_id, name=run.name, mode=mode, purpose=purpose, tier=tier, status=run.status,
        source_run=run.config.get("source_run"), follow_ups=follow_ups,
        total=progress["total"], done=progress["done"],
        a=_side(a_label, a_obs), b=_side(b_label, b_obs),
        diff=paired_test([p["a"] - p["b"] for p in pairs]),
        by_opponent=_breakdown(group("opponent")) if mode == "benchmark" else [],
        by_role=_breakdown(group("role")) if mode == "benchmark" else [],
        by_cell=_breakdown(group("cell")),
        by_gate=_breakdown(_by_opponent(gym_pairs(rows, mode, gate=True)[2])) if mode == "benchmark" else [],
        challengers=challengers,
        cost_usd=progress["cost_usd"], input_tokens=progress["input_tokens"],
        output_tokens=progress["output_tokens"],
    )


def _by_opponent(pairs: list[dict]) -> dict[str, list[tuple[float, float]]]:
    g: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in pairs:
        g[p["opponent"]].append((p["a"], p["b"]))
    return g


def _label(spec: dict) -> str:
    kind, model = spec.get("kind", "?"), spec.get("model")
    return f"{kind}@{model}" if model else kind


def _subject_order(subject: str) -> int:
    return 1 if subject == "a" else int(subject[1:])
