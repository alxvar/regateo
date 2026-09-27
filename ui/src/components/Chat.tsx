import type { Message } from "../api";
import { money } from "../format";

/** The price a message puts forward. Extracted by the backend (referee.prices.offer_path). */
export const priceOf = (m: Message): number | null => m.offer;

/** The price the agent meant, when its internals record a decision (LLM agents). */
function intendedPrice(m: Message): number | null {
  const d = (m.move.meta ?? {}).decision as { price?: number | null } | undefined;
  return typeof d?.price === "number" ? d.price : null;
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
                {m.move.action && (
                  <span className="chip">{m.move.action}{m.move.price != null ? ` ${money(m.move.price, currency)}` : ""}</span>
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
