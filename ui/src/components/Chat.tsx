import type { Message, Reading } from "../api";
import { money } from "../format";

/** The price a message offers or accepts, as the referee read it (backend: referee.reader). */
export const priceOf = (m: Message): number | null => m.offer;

/** What the sender meant: the protocol's record of its dropped action/price, or an LLM agent's decision. */
function intendedPrice(m: Message): number | null {
  const meta = m.move.meta ?? {};
  for (const key of ["intent", "decision"]) {
    const d = meta[key] as { price?: number | null } | undefined;
    if (typeof d?.price === "number") return d.price;
  }
  return null;
}

function describe(r: Reading, currency: string): string {
  const price = r.kind === "offer" || r.kind === "accept" ? ` ${r.price != null ? money(r.price, currency) : "?"}` : "";
  return `${r.kind}${price}`;
}

export function Chat({ messages, names, currency, closingIdx }: {
  messages: Message[]; names: { seller: string; buyer: string }; currency: string; closingIdx: number | null;
}) {
  if (!messages.length) return <p className="muted">No messages yet.</p>;
  return (
    <div className="chat">
      {messages.map((m) => {
        const meta = m.move.meta ?? {};
        const flags = [
          meta.timeout ? "timed out" : null,
          meta.fallback ? "fallback" : null,
          meta.repaired ? "veto: repaired" : Array.isArray(meta.vetoes) && meta.vetoes.length ? "veto: retried" : null,
        ].filter(Boolean) as string[];
        const intended = intendedPrice(m);
        if (intended != null && m.offer != null && Math.abs(intended - m.offer) > 0.005) {
          flags.push(`reads as ${money(m.offer, currency)}, meant ${money(intended, currency)}`);
        }
        return (
          <div key={m.idx} className={`bubble-row ${m.sender}`}>
            <div className={`bubble ${m.sender}${m.idx === closingIdx ? " closing" : ""}`}>
              <div className="who">
                <strong>{m.sender}</strong>
                <span className="muted">{names[m.sender]}</span>
                <span className="muted">#{m.idx + 1}</span>
                <span className="chip" title={m.reading.note || `read by ${m.reading.source}`}>
                  {describe(m.reading, currency)}
                  {m.reading.source === "llm" ? " · model" : m.reading.ambiguous ? " · unclear" : ""}
                </span>
                {m.reading.shadow && (
                  <span className="chip" title="shadow reader (log only)">
                    model reads {describe(m.reading.shadow, currency)}
                  </span>
                )}
                {flags.map((f) => <span key={f} className="chip">{f}</span>)}
                <span className="muted">{m.latency_s.toFixed(1)}s</span>
              </div>
              <div className="text">{m.text || <em className="muted">(no message)</em>}</div>
              {Object.keys(meta).length > 0 && (
                <details className="meta">
                  <summary>agent internals</summary>
                  <pre className="mono">{JSON.stringify(meta, null, 2)}</pre>
                </details>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
