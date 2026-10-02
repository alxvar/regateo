import type { Standing } from "../api";
import { ci, pct } from "../format";

/** An arena's standings: Bradley-Terry rating, mean share with its CI, deal rate. */
export function Leaderboard({ standings }: { standings: Standing[] }) {
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Agent</th><th className="r">Rating</th><th className="r">Mean share</th>
            <th className="r" title="Deals within its own limit">Deals</th><th className="r">n</th></tr></thead>
          <tbody>
            {standings.map((s) => (
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
    </>
  );
}
