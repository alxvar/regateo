"""Plain-text rendering of reports and transcripts for the terminal."""
from __future__ import annotations

from regateo.arena.report import ArenaReport
from regateo.core.messages import Message
from regateo.core.outcome import Outcome
from regateo.gym.report import Breakdown, GymReport
from regateo.stats import Estimate, PairedResult


def est(e: Estimate, pct: bool = False) -> str:
    if e.mean is None or e.lo is None or e.hi is None:
        return "-"
    f = (lambda x: f"{100 * x:5.1f}%") if pct else (lambda x: f"{x:6.3f}")
    return f"{f(e.mean)} [{f(e.lo).strip()}, {f(e.hi).strip()}]"


def diff(d: PairedResult) -> str:
    if d.n == 0 or d.p_value is None:
        return "no complete pairs yet"
    verdict = "significant" if d.p_value < 0.05 else "not significant"
    return (f"{d.mean_diff:+.3f} [{d.lo:+.3f}, {d.hi:+.3f}]  p={d.p_value:.4f} ({verdict}, n={d.n}); "
            f"A ahead in {100 * d.a_better:.0f}% of pairs, B in {100 * d.b_better:.0f}%")


def _table(title: str, rows: list[Breakdown]) -> list[str]:
    if not rows:
        return []
    out = [f"\n{title}", f"  {'':24} {'A share':>24} {'B share':>24}  {'A-B':>7}  {'p':>7}  {'n':>4}"]
    for r in rows:
        d = r.diff
        cols = f"{d.mean_diff:+7.3f}  {d.p_value:7.4f}" if d.p_value is not None else f"{'-':>7}  {'-':>7}"
        out.append(f"  {r.key[:24]:24} {est(r.a):>24} {est(r.b):>24}  {cols}  {d.n:4d}")
    return out


def gym_report(r: GymReport) -> str:
    lines = [
        f"Gym {r.name} ({r.mode})  run {r.run_id}  [{r.status}]  {r.done}/{r.total or '?'} matches",
        f"  A = {r.a.label}: share {est(r.a.mean_share)}  deals {est(r.a.deal_rate, True)}  "
        f"past-reservation {r.a.past_reservation}  errors {r.a.errors}",
        f"  B = {r.b.label}: share {est(r.b.mean_share)}  deals {est(r.b.deal_rate, True)}  "
        f"past-reservation {r.b.past_reservation}  errors {r.b.errors}",
        f"  A - B: {diff(r.diff)}",
    ]
    lines += _table("By opponent", r.by_opponent) + _table("By role", r.by_role) + _table("By cell", r.by_cell)
    lines.append(f"\nCost ${r.cost_usd:.4f}  tokens in {r.input_tokens:,} / out {r.output_tokens:,}")
    return "\n".join(lines)


def arena_report(r: ArenaReport) -> str:
    lines = [f"Arena {r.name}  run {r.run_id}  [{r.status}]  {r.done}/{r.total or '?'} matches", "",
             f"  {'#':>2}  {'agent':28} {'rating':>7}  {'mean share':>24}  {'deal rate':>24}  {'n':>5}"]
    for s in r.leaderboard:
        lines.append(f"  {s.rank:2d}  {s.label[:28]:28} {s.rating:7.0f}  {est(s.mean_share):>24}  "
                     f"{est(s.deal_rate, True):>24}  {s.matches:5d}")
    lines.append(f"\nCost ${r.cost_usd:.4f}")
    return "\n".join(lines)


def transcript(messages: list[Message], outcome: Outcome | None) -> str:
    lines = []
    for m in messages:
        tag = ""
        if m.move.action:
            price = f" {m.move.price:g}" if m.move.price is not None else ""
            tag = f" [{m.move.action.value}{price}]"
        lines.append(f"{m.idx:>2} {m.sender.value:>6}{tag}: {m.text}")
    if outcome:
        res = f"deal at {outcome.price:g}" if outcome.deal else "no deal"
        lines.append(f"\n{outcome.end_reason.value}: {res}  seller share {outcome.seller_share:.3f}  "
                     f"buyer share {outcome.buyer_share:.3f}{'  ' + outcome.detail if outcome.detail else ''}")
    return "\n".join(lines)
