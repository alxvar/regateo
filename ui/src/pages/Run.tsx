import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useApi, useEventStream, type ArenaReport, type Breakdown, type ChallengerStats, type Check, type GymReport,
  type MatchSummary, type Progress, type Run as RunData, type RunReport, type SideStats,
} from "../api";
import { ForestPlot, Heatmap, ProgressBar, StatTile } from "../components/charts";
import { ci, duration, interval, money, num, pValue, pct, signed, usd } from "../format";

export function Run() {
  const { id } = useParams();
  const [version, setVersion] = useState(0);
  const [progress, setProgress] = useState<Progress | null>(null);
  const { data: run, error } = useApi<RunData>(`/runs/${id}`, version);
  const { data: report } = useApi<RunReport>(`/runs/${id}/report`, version);
  const { data: matches } = useApi<MatchSummary[]>(`/runs/${id}/matches`, version);

  // While running: stream progress, and refresh the report every few finished matches.
  useEventStream(run?.status === "running" ? `/runs/${id}/stream` : null, {
    progress: (p) => {
      const next = p as Progress;
      setProgress((prev) => {
        if (!prev || next.done - prev.done >= 10 || next.status !== "running") setVersion((v) => v + 1);
        return next;
      });
    },
    end: () => setVersion((v) => v + 1),
  });

  if (error) return <p className="error">{error}</p>;
  if (!run) return <p className="muted">Loading…</p>;
  const p = progress ?? run.progress;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="muted"><Link to="/">Runs</Link> / {run.kind}</div>
          <h1>{run.name}</h1>
          <div className="sub row">
            <span className={`status ${p.status ?? run.status}`}>{(p.status ?? run.status).replace("_", " ")}</span>
            <span className="mono muted">{run.id}</span>
            <span className="muted">{duration(run.created_at, run.ended_at)}</span>
          </div>
        </div>
        <div style={{ minWidth: 260 }}>
          <div className="row"><span className="muted">Matches</span><span className="spacer" />
            <span className="num">{p.done} / {p.total ?? "?"}</span></div>
          <ProgressBar done={p.done} total={p.total} />
          <div className="row muted" style={{ fontSize: 12, marginTop: 4 }}>
            <span>{usd(p.cost_usd)}</span><span>·</span><span>{p.llm_calls} model calls</span>
            {p.by_status.failed ? <><span>·</span><span className="error">{p.by_status.failed} failed</span></> : null}
          </div>
        </div>
      </div>
      {!report && run.kind !== "match" && <div className="card muted">Computing report…</div>}
      {report?.kind === "gym" && <GymView r={report.report} />}
      {report?.kind === "arena" && <ArenaView r={report.report} />}
      <MatchTable matches={matches ?? []} kind={run.kind} />
    </>
  );
}

/** Fill fields an older API doesn't send yet, so a server that wasn't restarted degrades instead of crashing. */
function withDefaults(r: GymReport): GymReport {
  return {
    ...r, purpose: r.purpose ?? "dev", tier: r.tier ?? null, source_run: r.source_run ?? null,
    follow_ups: r.follow_ups ?? [],
    challengers: (r.challengers ?? []).map((c) => ({
      ...c, by_opponent: c.by_opponent ?? [], by_role: c.by_role ?? [], by_cell: c.by_cell ?? [],
      stopped_at: c.stopped_at ?? null, checks: c.checks ?? [],
    })),
  };
}

function GymView({ r: raw }: { r: GymReport }) {
  const r = withDefaults(raw);
  return r.mode === "benchmark" && r.challengers.length ? <BenchmarkView r={r} /> : <DuelView r={r} />;
}

function DuelView({ r }: { r: GymReport }) {
  const d = r.diff;
  const sig = d.p_value != null && d.p_value < 0.05;
  const leader = d.mean_diff == null ? null : d.mean_diff > 0 ? r.a.label : r.b.label;
  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Head to head</h2>
          <span className="chip">{r.mode === "duel" ? "duel: A plays B, roles swapped" : "benchmark: A and B vs the same opponents"}</span>
        </div>
        <div className="verdict">
          <div className={`big num ${sig ? "good-text" : ""}`}>{signed(d.mean_diff)}</div>
          <div>
            <div>
              {d.n === 0 ? "No complete pairs yet." : sig
                ? <><strong>{leader}</strong> captures more surplus, and the difference is significant.</>
                : <>No significant difference between <strong>{r.a.label}</strong> and <strong>{r.b.label}</strong> yet.</>}
            </div>
            <div className="secondary">
              A − B mean surplus share, 95% CI [{signed(d.lo)}, {signed(d.hi)}] · {pValue(d.p_value)} · {d.n} pairs ·
              A ahead in {pct(d.a_better)}, B in {pct(d.b_better)}
            </div>
          </div>
        </div>
      </div>
      <SideCards a={r.a} b={r.b} />
      <WhereFrom groups={r.mode === "benchmark" ? { opponent: r.by_opponent, role: r.by_role, cell: r.by_cell }
                                                : { cell: r.by_cell }} />
    </>
  );
}

const CHECK_ICON = { pass: "✓", fail: "✗", warn: "!", "n/a": "–" } as const;
const CHECK_TEXT = { pass: "passes", fail: "fails", warn: "warning", "n/a": "not judged" } as const;

function Checks({ checks }: { checks: Check[] }) {
  return (
    <span className="checks">
      {checks.map((k) => (
        <span key={k.name} className={`check ${k.status === "n/a" ? "na" : k.status}`}
              title={`${k.name} ${CHECK_TEXT[k.status]}: ${k.detail}`}>
          <i aria-hidden>{CHECK_ICON[k.status]}</i>{k.name}
        </span>
      ))}
    </span>
  );
}

const isCandidate = (c: ChallengerStats) => c.checks.every((k) => k.status === "pass" || k.status === "warn");

function BenchmarkView({ r }: { r: GymReport }) {
  const cs = [...r.challengers].sort((x, y) => (y.diff.mean_diff ?? -Infinity) - (x.diff.mean_diff ?? -Infinity));
  const [picked, setPicked] = useState<string | null>(null);
  const current = cs.find((c) => c.side.label === picked) ?? cs[0];
  const rows: Breakdown[] = cs.map((c) => ({ key: c.side.label, a: c.side.mean_share, b: c.reference.mean_share, diff: c.diff }));
  const next = (c: ChallengerStats) => {
    if (c.stopped_at != null) return <span className="secondary">stopped early after {c.stopped_at} pairs</span>;
    const f = r.follow_ups.find((f) => f.agents.includes(c.side.label));
    if (f) return <Link to={`/runs/${f.run_id}`} onClick={(e) => e.stopPropagation()}>full bench →</Link>;
    return <span className="muted">{r.tier ? "stopped at the screen" : "–"}</span>;
  };

  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 6 }}>
          <h2 style={{ margin: 0 }}>{cs.length > 1 ? `${cs.length} challengers` : "Challenger"} vs the reference</h2>
          <span className="chip">{r.purpose} bench</span>
          <span className="chip">{r.tier ? `tier ${r.tier}: drops losers, never promotes` : "full bench"}</span>
          {r.source_run && <Link className="chip" to={`/runs/${r.source_run}`}>← from screen {r.source_run.slice(-8)}</Link>}
        </div>
        <div className="secondary" style={{ marginBottom: 12 }}>
          Reference <strong>{r.b.label}</strong>: share {num(r.b.mean_share.mean)}, deals {pct(r.b.deal_rate.mean)},
          {" "}{r.b.past_reservation} past its limit. Each row: challenger − reference surplus share on the same pairs.
          Select one for the detail below.
        </div>
        <ForestPlot rows={rows} aLabel="challenger" bLabel="reference" selected={current.side.label}
                    onSelect={setPicked} />
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>Challenger</th><th className="r">vs reference</th><th className="r">p</th>
              <th className="r">Share</th><th className="r">Deals</th><th className="r">Past limit</th>
              <th>Promotion checks</th><th>Next</th></tr></thead>
            <tbody>
              {cs.map((c) => (
                <tr key={c.subject} className={`link ${c === current ? "selected" : ""}`}
                    onClick={() => setPicked(c.side.label)}>
                  <td><strong>{c.side.label}</strong>
                    {isCandidate(c) && <span className="chip" style={{ marginLeft: 6 }}>candidate</span>}</td>
                  <td className="r">{signed(c.diff.mean_diff)} <span className="muted">[{signed(c.diff.lo)}, {signed(c.diff.hi)}]</span></td>
                  <td className="r">{pValue(c.diff.p_value).replace("p = ", "")}</td>
                  <td className="r">{num(c.side.mean_share.mean)}</td>
                  <td className="r">{pct(c.side.deal_rate.mean)}</td>
                  <td className="r">{c.side.past_reservation}</td>
                  <td><Checks checks={c.checks} /></td>
                  <td>{next(c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
          Checks (docs/04-hill-climbing.md §3.1): gain significant on a full dev bench, same direction on the holdout;
          no deals past its own limit; deal rate at most 2 points below the reference; no opponent significantly
          worse. Hover a check for its numbers. The reading audit and holdout run stay with a person.
        </p>
      </div>
      <h2 style={{ margin: "8px 0 0" }}>{current.side.label} <span className="muted">vs</span> {current.reference.label}</h2>
      <SideCards a={current.side} b={current.reference} />
      <WhereFrom key={current.subject}
                 groups={{ opponent: current.by_opponent, role: current.by_role, cell: current.by_cell }} />
    </>
  );
}

function SideCards({ a, b }: { a: SideStats; b: SideStats }) {
  return (
    <div className="grid-2">
      {([["A", a, "var(--series-1)"], ["B", b, "var(--series-2)"]] as const).map(([k, s, color]) => (
        <div key={k} className="card">
          <div className="row" style={{ marginBottom: 10 }}>
            <i className="swatch" style={{ background: color }} />
            <h2 style={{ margin: 0 }}>{k} · {s.label}</h2>
          </div>
          <div className="tiles">
            <StatTile label="Mean surplus share" value={num(s.mean_share.mean)} foot={`95% CI ${interval(s.mean_share)}`} />
            <StatTile label="Deal rate" value={pct(s.deal_rate.mean, 1)}
                      foot={`${interval(s.deal_rate, true)} · ${s.matches} matches`} />
            <StatTile label="Past walk-away" value={s.past_reservation}
                      foot={s.errors ? `${s.errors} agent errors` : "deals that broke its limit"} />
          </div>
        </div>
      ))}
    </div>
  );
}

function WhereFrom({ groups }: { groups: Partial<Record<"opponent" | "role" | "cell", Breakdown[]>> }) {
  const keys = (Object.keys(groups) as ("opponent" | "role" | "cell")[]).filter((k) => groups[k]?.length);
  if (!keys.length) keys.push("cell");
  const [group, setGroup] = useState(keys[0]);
  const rows = groups[group] ?? [];
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Where the difference comes from</h2>
        <span className="spacer" />
        <div className="seg" role="tablist">
          {keys.map((g) => (
            <button key={g} className={group === g ? "on" : ""} onClick={() => setGroup(g)}>by {g}</button>
          ))}
        </div>
      </div>
      <ForestPlot rows={rows} aLabel="A" bLabel="B" />
      <details style={{ marginTop: 12 }}>
        <summary className="secondary">Table</summary>
        <div className="table-wrap">
          <table>
            <thead><tr><th>{group}</th><th className="r">A share</th><th className="r">B share</th>
              <th className="r">A − B</th><th className="r">p</th><th className="r">pairs</th></tr></thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.key}><td>{b.key}</td><td className="r">{ci(b.a)}</td><td className="r">{ci(b.b)}</td>
                  <td className="r">{signed(b.diff.mean_diff)}</td><td className="r">{pValue(b.diff.p_value)}</td>
                  <td className="r">{b.diff.n}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function ArenaView({ r }: { r: ArenaReport }) {
  const labels = r.leaderboard.map((s) => s.label);
  return (
    <div className="grid-2">
      <div className="card">
        <h2>Leaderboard</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Agent</th><th className="r">Rating</th><th className="r">Mean share</th>
              <th className="r">Deals</th><th className="r">n</th></tr></thead>
            <tbody>
              {r.leaderboard.map((s) => (
                <tr key={s.label}>
                  <td className="muted">{s.rank}</td>
                  <td><strong>{s.label}</strong>{s.past_reservation > 0 &&
                    <span className="chip" style={{ marginLeft: 6 }}>{s.past_reservation} past walk-away</span>}</td>
                  <td className="r">{Math.round(s.rating)}</td>
                  <td className="r">{ci(s.mean_share)}</td>
                  <td className="r">{pct(s.deal_rate.mean)}</td>
                  <td className="r">{s.matches}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
          Rating: Bradley-Terry on who captured more surplus per match (no deal = draw), Elo scale.
        </p>
      </div>
      <div className="card">
        <h2>Pairwise results</h2>
        <Heatmap labels={labels} cells={r.matrix} />
      </div>
    </div>
  );
}

function MatchTable({ matches, kind }: { matches: MatchSummary[]; kind: string }) {
  const nav = useNavigate();
  const [deal, setDeal] = useState<"all" | "deal" | "no deal">("all");
  const [reason, setReason] = useState("all");
  const [agent, setAgent] = useState("all");
  const reasons = useMemo(() => [...new Set(matches.map((m) => m.end_reason).filter(Boolean))] as string[], [matches]);
  const agents = useMemo(() => [...new Set(matches.flatMap((m) => [m.seller, m.buyer]))].sort(), [matches]);
  const shown = matches.filter((m) =>
    (deal === "all" || (deal === "deal") === !!m.deal) &&
    (reason === "all" || m.end_reason === reason) &&
    (agent === "all" || m.seller === agent || m.buyer === agent));
  const [page, setPage] = useState(0);
  const pageSize = 50;
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const current = Math.min(page, pages - 1);

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Matches</h2>
        <span className="muted">{shown.length} of {matches.length}</span>
        <span className="spacer" />
        <select value={deal} onChange={(e) => { setDeal(e.target.value as typeof deal); setPage(0); }} aria-label="Deal">
          <option value="all">deal or not</option><option value="deal">deal</option><option value="no deal">no deal</option>
        </select>
        <select value={reason} onChange={(e) => { setReason(e.target.value); setPage(0); }} aria-label="End reason">
          <option value="all">any ending</option>{reasons.map((r) => <option key={r}>{r}</option>)}
        </select>
        <select value={agent} onChange={(e) => { setAgent(e.target.value); setPage(0); }} aria-label="Agent">
          <option value="all">any agent</option>{agents.map((a) => <option key={a}>{a}</option>)}
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Seller</th><th>Buyer</th>{kind === "gym" && <th>Pair</th>}<th>Ending</th>
            <th className="r">Price</th><th className="r">Seller share</th><th className="r">Msgs</th><th className="r">Cost</th></tr></thead>
          <tbody>
            {shown.slice(current * pageSize, (current + 1) * pageSize).map((m) => (
              <tr key={m.id} className="link" onClick={() => nav(`/matches/${m.id}`)}>
                <td>{m.seller}</td><td>{m.buyer}</td>
                {kind === "gym" && <td className="muted">{String(m.meta.pair ?? "")}{m.meta.subject ? ` · ${m.meta.subject}` : ""}</td>}
                <td>{m.status === "running" ? <span className="status running">running</span>
                  : <span className="chip">{m.end_reason?.replace("_", " ")}</span>}
                  {m.past_reservation && <span className="chip error" style={{ marginLeft: 4 }}>past {m.past_reservation} limit</span>}</td>
                <td className="r">{money(m.price)}</td>
                <td className="r">{num(m.seller_share)}</td>
                <td className="r">{m.messages ?? "–"}</td>
                <td className="r">{usd(m.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pager">
          <span className="muted num">page {current + 1} of {pages}</span>
          <button disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
          <button disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
