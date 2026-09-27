import {
  CartesianGrid, Line, LineChart, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import type { Message, Outcome, Scenario } from "../api";
import { money } from "../format";
import { priceOf } from "./Chat";

/**
 * Offers over the course of a match, one line per side, against both walk-away prices.
 * The band between the reservations is the ZOPA: any deal inside it is good for both.
 */
export function PricePath({ scenario, messages, outcome }: {
  scenario: Scenario; messages: Message[]; outcome: Outcome | null;
}) {
  const rows = messages.map((m) => {
    const p = priceOf(m);
    return { idx: m.idx + 1, seller: m.sender === "seller" ? p : null, buyer: m.sender === "buyer" ? p : null };
  });
  const prices = rows.flatMap((r) => [r.seller, r.buyer]).filter((v): v is number => v != null);
  const lo = Math.min(scenario.seller_reservation, scenario.buyer_reservation, ...prices);
  const hi = Math.max(scenario.seller_reservation, scenario.buyer_reservation, ...prices);
  const pad = (hi - lo) * 0.08 || 5;
  const cur = scenario.currency;
  const zopaLo = Math.min(scenario.seller_reservation, scenario.buyer_reservation);
  const zopaHi = Math.max(scenario.seller_reservation, scenario.buyer_reservation);

  return (
    <div>
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 16, right: 16, bottom: 4, left: 6 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="idx" stroke="var(--axis)" tick={{ fill: "var(--muted)", fontSize: 11 }}
                   tickLine={false} label={{ value: "message", position: "insideBottomRight", offset: -2,
                                             fill: "var(--muted)", fontSize: 11 }} />
            <YAxis domain={[Math.floor(lo - pad), Math.ceil(hi + pad)]} stroke="var(--axis)" width={64}
                   tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false}
                   tickFormatter={(v: number) => money(v, cur)} />
            {scenario.buyer_reservation > scenario.seller_reservation && (
              <ReferenceArea y1={zopaLo} y2={zopaHi} fill="var(--zopa)" ifOverflow="extendDomain" />
            )}
            <ReferenceLine y={scenario.seller_reservation} stroke="var(--series-1)" strokeDasharray="4 4"
                           label={{ value: `seller min ${money(scenario.seller_reservation, cur)}`,
                                    position: scenario.seller_reservation <= scenario.buyer_reservation ? "insideBottomLeft" : "insideTopLeft",
                                    fill: "var(--text-2)", fontSize: 11 }} />
            <ReferenceLine y={scenario.buyer_reservation} stroke="var(--series-2)" strokeDasharray="4 4"
                           label={{ value: `buyer max ${money(scenario.buyer_reservation, cur)}`,
                                    position: scenario.seller_reservation <= scenario.buyer_reservation ? "insideTopLeft" : "insideBottomLeft",
                                    fill: "var(--text-2)", fontSize: 11 }} />
            <Tooltip
              cursor={{ stroke: "var(--axis)" }}
              content={({ active, payload, label }) => active && payload?.length ? (
                <div className="chart-tip">
                  <div className="muted">message {label}</div>
                  {payload.filter((p) => p.value != null).map((p) => (
                    <div key={String(p.dataKey)} className="row" style={{ gap: 6 }}>
                      <i className="swatch" style={{ background: p.color }} />
                      {String(p.dataKey)} offers <strong>{money(p.value as number, cur)}</strong>
                    </div>
                  ))}
                </div>
              ) : null}
            />
            <Line type="linear" dataKey="seller" stroke="var(--series-1)" strokeWidth={2} connectNulls
                  dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: "var(--series-1)" }}
                  activeDot={{ r: 5 }} isAnimationActive={false} />
            <Line type="linear" dataKey="buyer" stroke="var(--series-2)" strokeWidth={2} connectNulls
                  dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: "var(--series-2)" }}
                  activeDot={{ r: 5 }} isAnimationActive={false} />
            {outcome?.deal && outcome.price != null && outcome.closed_at != null && (
              <ReferenceDot x={outcome.closed_at + 1} y={outcome.price} r={7} fill="var(--good)"
                            stroke="var(--surface)" strokeWidth={2}
                            label={{ value: `deal ${money(outcome.price, cur)}`, position: "left",
                                     fill: "var(--text)", fontSize: 12 }} />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="legend">
        <span><i className="swatch" style={{ background: "var(--series-1)" }} />seller offers</span>
        <span><i className="swatch" style={{ background: "var(--series-2)" }} />buyer offers</span>
        <span><i className="swatch" style={{ background: "var(--zopa)", outline: "1px solid var(--good)" }} />
          zone of possible agreement</span>
      </div>
    </div>
  );
}
