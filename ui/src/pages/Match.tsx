import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useApi, useEventStream, type MatchDetail, type Message } from "../api";
import { Chat } from "../components/Chat";
import { StatTile } from "../components/charts";
import { PricePath } from "../components/PricePath";
import { money, num, usd } from "../format";

export function Match() {
  const { id } = useParams();
  const [version, setVersion] = useState(0);
  const { data, error } = useApi<MatchDetail>(`/matches/${id}`, version);
  const [live, setLive] = useState<Message[]>([]);
  useEffect(() => setLive([]), [id, version]);

  const running = data?.match.status === "running";
  const after = data ? (data.messages.at(-1)?.idx ?? -1) : -1;
  useEventStream(running ? `/matches/${id}/stream?after=${after}` : null, {
    message: (m) => setLive((prev) => [...prev, m as Message]),
    end: () => setVersion((v) => v + 1),
  });

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const { match: m, llm_calls: calls } = data;
  const messages = [...data.messages, ...live.filter((x) => x.idx > after)];
  const s = m.scenario;
  const o = m.outcome;
  const cur = s.currency;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="muted">
            <Link to="/">Runs</Link>{m.run_id && <> / <Link to={`/runs/${m.run_id}`}>run</Link></>} / match
          </div>
          <h1>{m.seller.name} <span className="muted">vs</span> {m.buyer.name}</h1>
          <div className="sub row">
            <span className={`status ${m.status}`}>{m.status}</span>
            <span>{s.item}</span>
            <span className="chip">{m.protocol}</span>
            <span className="chip">{s.info_mode}</span>
            <span className="chip">{s.rules.max_rounds} rounds, deadline {s.rules.deadline_known ? "known" : "hidden"}</span>
          </div>
        </div>
      </div>

      <div className="tiles">
        <StatTile label="Result" value={o ? (o.deal ? money(o.price, cur) : "No deal") : "In progress"}
                  foot={o ? `${o.end_reason.replace("_", " ")} after ${o.messages} messages` : `${messages.length} messages so far`} />
        <StatTile label="Seller share" value={o ? num(o.seller_share) : "–"} foot={`walk-away ${money(s.seller_reservation, cur)}`} />
        <StatTile label="Buyer share" value={o ? num(o.buyer_share) : "–"} foot={`walk-away ${money(s.buyer_reservation, cur)}`} />
        <StatTile label="Zone of agreement" value={money(Math.max(0, s.buyer_reservation - s.seller_reservation), cur)}
                  foot={`market ${money(s.market_low, cur)}–${money(s.market_high, cur)}`} />
        <StatTile label="Model cost" value={usd(m.cost_usd)} foot={`${calls.length} calls`} />
      </div>
      {o?.past_reservation && (
        <div className="card error">The deal broke the {o.past_reservation}'s walk-away price.</div>
      )}
      {o?.detail && o.end_reason === "error" && <div className="card error">{o.detail}</div>}

      <div className="card">
        <h2>Price path</h2>
        <PricePath scenario={s} messages={messages} outcome={o} />
      </div>

      <div className="card">
        <h2>Conversation</h2>
        <Chat messages={messages} names={{ seller: m.seller.name, buyer: m.buyer.name }} currency={cur}
              closingIdx={o?.closed_at ?? null} />
      </div>

      {calls.length > 0 && (
        <div className="card">
          <h2>Model calls</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Role</th><th>Stage</th><th>Model</th><th className="r">In</th><th className="r">Out</th>
                <th className="r">Cached in</th><th className="r">Latency</th><th className="r">Cost</th><th>Error</th></tr></thead>
              <tbody>
                {calls.map((c, i) => (
                  <tr key={i}>
                    <td>{c.tags.role}</td><td>{c.tags.stage}</td><td className="mono">{c.model || c.profile}</td>
                    <td className="r">{c.usage.input_tokens}</td><td className="r">{c.usage.output_tokens}</td>
                    <td className="r">{c.usage.cache_read_tokens}</td><td className="r">{c.latency_s.toFixed(2)}s</td>
                    <td className="r">{c.cached ? "replay" : usd(c.cost_usd)}</td>
                    <td className="error">{c.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
