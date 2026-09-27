import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useApi, useEventStream, type ArenaReport, type Breakdown, type GymReport, type MatchSummary, type Progress,
  type Run as RunData, type RunReport,
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

function GymView({ r }: { r: GymReport }) {
  const d = r.diff;
  const sig = d.p_value != null && d.p_value < 0.05;
  const leader = d.mean_diff == null ? null : d.mean_diff > 0 ? r.a.label : r.b.label;
  const [group, setGroup] = useState<"opponent" | "role" | "cell">(r.mode === "benchmark" ? "opponent" : "cell");
  const rows: Breakdown[] = group === "opponent" ? r.by_opponent : group === "role" ? r.by_role : r.by_cell;

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
      <div className="grid-2">
        {([["A", r.a, "var(--series-1)"], ["B", r.b, "var(--series-2)"]] as const).map(([k, s, color]) => (
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
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Where the difference comes from</h2>
          <span className="spacer" />
          <div className="seg" role="tablist">
            {(r.mode === "benchmark" ? ["opponent", "role", "cell"] as const : ["cell"] as const).map((g) => (
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
    </>
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
