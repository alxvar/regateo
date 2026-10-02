import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useApi, type Overview as OverviewData, type Run, type RunReport } from "../api";
import { ProgressBar, StatTile } from "../components/charts";
import { Leaderboard } from "../components/Leaderboard";
import { ago, compact, eta, pct, usd } from "../format";

/** The league is the arena run from engine/configs/arena/league.yaml; other arenas are one-off tournaments. */
const isLeague = (r: Run) => r.kind === "arena" && r.name.startsWith("league");
/** Gym runs on an adversarial bench (engine/configs/benches/adversarial-v1.yaml): read, not scored. */
const isRedTeam = (r: Run) => r.kind === "gym" && r.config.purpose === "adversarial";

type Group = "gym" | "league" | "redteam" | "arena" | "match";
const GROUPS: { key: Group; title: string; blurb: string }[] = [
  { key: "league", title: "League", blurb: "Round robins among every champion and the strongest opponents." },
  { key: "gym", title: "Gym", blurb: "Paired experiments: a challenger against the reference." },
  { key: "redteam", title: "Red-team", blurb: "Challengers against opponents written to attack our agents." },
  { key: "arena", title: "Arena", blurb: "Other tournaments." },
  { key: "match", title: "Matches", blurb: "Single matches." },
];
const group = (r: Run): Group => (isLeague(r) ? "league" : isRedTeam(r) ? "redteam" : r.kind);

export function Overview() {
  // While anything runs, refetch every few seconds so progress and ETAs stay current.
  const [tick, setTick] = useState(0);
  const { data: o } = useApi<OverviewData>("/overview", tick);
  const { data: runs, error } = useApi<Run[]>("/runs?limit=500", tick);
  const live = !!runs?.some((r) => r.status === "running");
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setTick((v) => v + 1), REFRESH_MS);
    return () => clearInterval(t);
  }, [live]);

  const byGroup = new Map<Group, Run[]>(GROUPS.map((g) => [g.key, []]));
  for (const r of runs ?? []) byGroup.get(group(r))!.push(r);
  const leagues = byGroup.get("league")!;
  const league = leagues.find((r) => r.status === "done") ?? leagues[0];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <div className="sub">Gym experiments, league and arena tournaments, and single matches recorded in this database.</div>
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
      {league && <LeagueStandings run={league} />}
      {error && <div className="card"><p className="error">{error}. Is `regateo serve` running?</p></div>}
      {runs && !runs.length && (
        <div className="card">
          <p className="muted">No runs yet. Try <span className="mono">uv run regateo gym smoke-offline</span>.</p>
        </div>
      )}
      {runs && runs.length > 0 && GROUPS.map((g) => {
        const rows = byGroup.get(g.key)!;
        return rows.length > 0 && <RunGroup key={g.key} title={g.title} blurb={g.blurb} runs={rows} compact={g.key === "match"} />;
      })}
    </>
  );
}

function LeagueStandings({ run }: { run: Run }) {
  const { data } = useApi<RunReport>(`/runs/${run.id}/report`);
  const report = data?.kind === "arena" ? data.report : null;
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Leaderboard</h2>
        <span className="muted">
          latest league, <Link to={`/runs/${run.id}`} className="mono">{run.id}</Link> · {ago(run.created_at)}
          {run.status !== "done" && <> · <span className={`status ${run.status}`}>{run.status.replace("_", " ")}</span></>}
        </span>
      </div>
      {report ? <Leaderboard standings={report.leaderboard} /> : <p className="muted">Loading…</p>}
    </div>
  );
}

const FOLD = 10;
const REFRESH_MS = 5000;

/** One kind of run. Single matches have no progress worth a bar, so they show the outcome instead. */
function RunGroup({ title, blurb, runs, compact }: { title: string; blurb: string; runs: Run[]; compact: boolean }) {
  const nav = useNavigate();
  const [all, setAll] = useState(false);
  const shown = all ? runs : runs.slice(0, FOLD);
  const running = runs.filter((r) => r.status === "running").length;
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{title}</h2>
        <span className="chip">{runs.length}</span>
        {running > 0 && <span className="status running">{running} running</span>}
        <span className="muted">{blurb}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            {compact
              ? <tr><th>Name</th><th>Status</th><th>Outcome</th><th className="r">Cost</th><th>Started</th></tr>
              : <tr><th>Name</th><th>Status</th><th style={{ width: "22%" }}>Progress</th>
                  <th className="r">Deals</th><th className="r">Cost</th><th>Started</th></tr>}
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="link" onClick={() => nav(`/runs/${r.id}`)}>
                <td><strong>{r.name}</strong><div className="muted mono">{r.id}</div></td>
                <td><span className={`status ${r.status}`}>{r.status.replace("_", " ")}</span></td>
                {compact
                  ? <td className="secondary">{r.progress.done ? (r.progress.deals ? "deal" : "no deal") : "–"}</td>
                  : <>
                      <td>
                        <ProgressBar done={r.progress.done} total={r.progress.total} />
                        <div className="row muted num" style={{ fontSize: 12 }}>
                          <span>{r.progress.done} / {r.progress.total ?? "?"}</span>
                          {eta(r.created_at, r.progress) && <><span className="spacer" /><span>{eta(r.created_at, r.progress)}</span></>}
                        </div>
                      </td>
                      <td className="r">{pct(r.progress.done ? r.progress.deals / r.progress.done : null)}</td>
                    </>}
                <td className="r">{usd(r.progress.cost_usd)}</td>
                <td className="muted">{ago(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {runs.length > FOLD && (
        <div className="pager">
          <button onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${runs.length}`}</button>
        </div>
      )}
    </div>
  );
}
