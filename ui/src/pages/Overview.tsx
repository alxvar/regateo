import { useNavigate } from "react-router-dom";

import { useApi, type Overview as OverviewData, type Run } from "../api";
import { ProgressBar, StatTile } from "../components/charts";
import { ago, compact, pct, usd } from "../format";

export function Overview() {
  const { data: o } = useApi<OverviewData>("/overview");
  const { data: runs, error } = useApi<Run[]>("/runs?limit=100");
  const nav = useNavigate();

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <div className="sub">Gym experiments, arena tournaments and single matches recorded in this database.</div>
        </div>
      </div>
      {o && (
        <div className="tiles">
          <StatTile label="Matches played" value={compact(o.matches)} foot={`${pct(o.matches ? o.deals / o.matches : null)} closed a deal`} />
          <StatTile label="Runs" value={Object.values(o.runs).reduce((a, b) => a + b, 0)}
                    foot={Object.entries(o.runs).map(([k, v]) => `${v} ${k}`).join(" · ") || "none yet"} />
          <StatTile label="Running now" value={o.running_runs} foot="runs in progress" />
          <StatTile label="Model spend" value={usd(o.cost_usd)} foot={`${compact(o.llm_calls)} calls`} />
          <StatTile label="Tokens" value={compact(o.input_tokens + o.output_tokens)}
                    foot={`${compact(o.input_tokens)} in · ${compact(o.output_tokens)} out`} />
        </div>
      )}
      <div className="card">
        <h2>Runs</h2>
        {error && <p className="error">{error}. Is `regateo serve` running?</p>}
        {runs && !runs.length && (
          <p className="muted">No runs yet. Try <span className="mono">uv run regateo gym smoke-offline</span>.</p>
        )}
        {runs && runs.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Name</th><th>Kind</th><th>Status</th><th style={{ width: "22%" }}>Progress</th>
                  <th className="r">Deals</th><th className="r">Cost</th><th>Started</th></tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="link" onClick={() => nav(`/runs/${r.id}`)}>
                    <td><strong>{r.name}</strong><div className="muted mono">{r.id}</div></td>
                    <td><span className="chip">{r.kind}</span></td>
                    <td><span className={`status ${r.status}`}>{r.status.replace("_", " ")}</span></td>
                    <td>
                      <ProgressBar done={r.progress.done} total={r.progress.total} />
                      <div className="muted num" style={{ fontSize: 12 }}>{r.progress.done} / {r.progress.total ?? "?"}</div>
                    </td>
                    <td className="r">{pct(r.progress.done ? r.progress.deals / r.progress.done : null)}</td>
                    <td className="r">{usd(r.progress.cost_usd)}</td>
                    <td className="muted">{ago(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
