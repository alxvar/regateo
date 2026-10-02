"""Plain-text rendering of reports and transcripts for the terminal."""
from __future__ import annotations

from regateo.arena.report import ArenaReport
from regateo.core.messages import Message, Reading
from regateo.core.outcome import Outcome
from regateo.gym.report import Breakdown, GymReport
from regateo.gym.signals import Signals
from regateo.referee.audit import Group, ReadingAudit
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


def _table(title: str, rows: list[Breakdown], a: str = "A", b: str = "B", width: int = 24) -> list[str]:
    if not rows:
        return []
    out = [f"\n{title}", f"  {'':{width}} {a + ' share':>24} {b + ' share':>24}  {a + '-' + b:>7}  {'p':>7}  {'n':>4}"]
    for r in rows:
        d = r.diff
        cols = f"{d.mean_diff:+7.3f}  {d.p_value:7.4f}" if d.p_value is not None else f"{'-':>7}  {'-':>7}"
        out.append(f"  {r.key[:width]:{width}} {est(r.a):>24} {est(r.b):>24}  {cols}  {d.n:4d}")
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
    if len(r.challengers) > 1:
        lines += [f"\nChallengers vs reference B = {r.b.label} (paired on the same matches)",
                  f"  {'':4} {'agent':28} {'share':>24} {'deals':>24}  {'vs B':>7}  {'p':>7}  {'n':>4}"]
        for c in sorted(r.challengers, key=lambda c: -(c.diff.mean_diff or 0)):
            d = c.diff
            cols = f"{d.mean_diff:+7.3f}  {d.p_value:7.4f}" if d.p_value is not None else f"{'-':>7}  {'-':>7}"
            lines.append(f"  {c.subject:4} {c.side.label[:28]:28} {est(c.side.mean_share):>24} "
                         f"{est(c.side.deal_rate, True):>24}  {cols}  {d.n:4d}")
    lines += _table("By opponent", r.by_opponent) + _table("By role", r.by_role) + _table("By cell", r.by_cell)
    if r.by_gate:
        lines += _table("Gates (not scored)", r.by_gate)
    lines += _table("What each attack costs: share against it minus against its plain twin (paired)", r.twins,
                    a="att", b="plain", width=48)
    lines.append(f"\nCost ${r.cost_usd:.4f}  tokens in {r.input_tokens:,} / out {r.output_tokens:,}")
    lines += _checks(r)
    return "\n".join(lines)


_MARK = {"pass": "ok  ", "fail": "FAIL", "warn": "warn", "n/a": "-   "}


def _checks(r: GymReport) -> list[str]:
    if not r.challengers:
        return []
    where = f"{r.purpose} bench" + (f", tier {r.tier}" if r.tier else ", full")
    out = [f"\nPromotion checks ({where}; docs/04-hill-climbing.md §3.1; also run `regateo readings {r.run_id}`"
           f" and `regateo signals {r.run_id}`)"]
    for c in sorted(r.challengers, key=lambda c: -(c.diff.mean_diff or 0)):
        verdict = "candidate" if all(k.status in ("pass", "warn") for k in c.checks) else "no"
        out.append(f"  {c.subject:4} {c.side.label[:40]:40} {verdict}")
        out += [f"         {_MARK[k.status]} {k.name:10} {k.detail}" for k in c.checks]
    return out


def _share(k: int, n: int) -> str:
    return f"{100 * k / n:3.0f}% {f'({n})':>6}" if n else f"{'-':>4} {'(0)':>6}"


def signals(run_id: str, rows: list[Signals]) -> str:
    """Rates per agent; the count each rate is out of in brackets (regateo.gym.signals says what each one means)."""
    out = [f"Exploit signals for {run_id} (rate, out of how many)",
           "  repeats, rewritten  of its messages: repeated word for word; rewritten by its own checks",
           "  unrecip.            of its concessions: made with no move from them since its previous offer",
           "  dominated           of its matches: it offered worse for itself than their standing offer",
           "  missed              of its no-deals: they had offered a price within its limit",
           "  broken              of offers it called final: it conceded from them later",
           "  near limit          of its matches: it named its own walk-away price (within 1% of the market range)\n",
           f"  {'agent':30} {'matches':>7}  {'repeats':>11}  {'rewritten':>11}  {'unrecip.':>11}  {'dominated':>11}"
           f"  {'missed':>11}  {'broken':>11}  {'near limit':>11}"]
    for s in rows:
        name = s.agent if s.opponent == "all" else f"  vs {s.opponent}"
        out.append(f"  {name[:30]:30} {s.matches:7d}  {_share(s.repeats, s.turns)}  {_share(s.rewritten, s.turns)}"
                   f"  {_share(s.unreciprocated, s.concessions)}  {_share(s.dominated, s.matches)}"
                   f"  {_share(s.missed, s.no_deals)}  {_share(s.broken_finals, s.finals)}"
                   f"  {_share(s.near_limit, s.matches)}")
    return "\n".join(out)


def proposals(written: list, rejected: list) -> str:
    out = []
    for w in written:
        p = w.proposal
        out.append(f"  + {w.agent}" + (f" (prompt {w.prompt_file})" if w.prompt_file else ""))
        out.append(f"      targets: {' '.join(p.failure.split())[:200]}")
        out.append(f"      hypothesis: {' '.join(p.hypothesis.split())[:200]}")
    for r in rejected:
        out.append(f"  - {r.proposal.name}: rejected, {'; '.join(r.reasons)}")
    return "\n".join(out) or "  no proposals"


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


def _rate(g: Group, which: str) -> str:
    r = getattr(g, which).rate
    return "-" if r is None else f"{100 * r:5.1f}%"


def _reading(r: Reading) -> str:
    price = "?" if r.price is None else f"{r.price:g}"
    return f"{r.kind.value} {price if r.kind.value in ('offer', 'accept') else ''}".strip() + f" ({r.source})"


def reading_audit(a: ReadingAudit) -> str:
    out = [f"Readings for {a.run_id}: {a.messages} messages, {a.labelled} scored against recorded intent"
           f" ({a.unstated} more meant a price they didn't write)\n",
           f"  {'':10} {'n':>6} {'rules':>8} {'rules+model':>12} {'model calls':>12}"]
    for name, g in (("clear", a.clear), ("ambiguous", a.ambiguous)):
        out.append(f"  {name:10} {g.rules.n:>6} {_rate(g, 'rules'):>8} {_rate(g, 'with_model'):>12}"
                   f" {g.model_calls:>12}")
    if a.mismatches:
        out.append(f"\nMismatches ({a.mismatches_total}; showing {len(a.mismatches)}):")
        for m in a.mismatches:
            intent = f"{m.intent.kind.value} {'' if m.intent.price is None else f'{m.intent.price:g}'}".strip()
            note = f"  [{m.rules.note}]" if m.rules.note else ""
            out.append(f"  {m.match_id} #{m.idx} {m.sender} ({m.agent}): {m.text[:160]!r}")
            out.append(f"      meant {intent} | rules: {_reading(m.rules)}{note}"
                       f" | with model: {_reading(m.with_model)}")
    return "\n".join(out)
