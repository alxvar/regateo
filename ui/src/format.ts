import type { Estimate } from "./api";

const SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" };

export function money(value: number | null | undefined, currency = "USD"): string {
  if (value == null) return "–";
  const num = value.toLocaleString(undefined, { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 });
  const sym = SYMBOLS[currency];
  return sym ? `${sym}${num}` : `${num} ${currency}`;
}

export const usd = (v: number) => (v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);
export const num = (v: number | null | undefined, d = 3) => (v == null ? "–" : v.toFixed(d));
export const pct = (v: number | null | undefined, d = 0) => (v == null ? "–" : `${(100 * v).toFixed(d)}%`);
export const signed = (v: number | null | undefined, d = 3) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`);
export const compact = (v: number) => Intl.NumberFormat(undefined, { notation: "compact" }).format(v);

export function ci(e: Estimate, asPct = false): string {
  if (e.mean == null || e.lo == null || e.hi == null) return "–";
  const f = asPct ? (x: number) => pct(x, 1) : (x: number) => num(x);
  return `${f(e.mean)} [${f(e.lo)}, ${f(e.hi)}]`;
}

/** Just the interval, for places where the mean is already shown. */
export function interval(e: Estimate, asPct = false): string {
  if (e.lo == null || e.hi == null) return "–";
  const f = asPct ? (x: number) => pct(x, 1) : (x: number) => num(x);
  return `${f(e.lo)} – ${f(e.hi)}`;
}

export function pValue(p: number | null | undefined): string {
  if (p == null) return "–";
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "–";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export function duration(start: number, end: number | null): string {
  const s = (end ?? Date.now() / 1000) - start;
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}
