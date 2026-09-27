import type { Message } from "../api";
import { money } from "../format";

const PRICE = /(?:[$€£]|USD|EUR|GBP)\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)/i;

/** The price a message carries: the structured field, else the first currency amount in the text. */
export function priceOf(m: Message): number | null {
  if (m.move.price != null && m.move.action !== "accept") return m.move.price;
  if (m.move.action === "accept") return null;
  const hit = PRICE.exec(m.text);
  return hit ? Number(hit[1].replace(/,/g, "")) : null;
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
