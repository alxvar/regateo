import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import type { Breakdown } from "../api";
import { pValue, signed } from "../format";

/** Width of a container, tracked with ResizeObserver, so SVG charts stay responsive. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function StatTile({ label, value, foot }: { label: string; value: ReactNode; foot?: ReactNode }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

export function ProgressBar({ done, total }: { done: number; total: number | null }) {
  const frac = total ? Math.min(done / total, 1) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={done} aria-valuemax={total ?? undefined}>
      <div style={{ width: `${100 * frac}%` }} />
    </div>
  );
}

interface Tip { x: number; y: number; content: ReactNode }

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="chart-tip" style={{ position: "absolute", left: tip.x + 12, top: tip.y + 12, zIndex: 3 }}>
      {tip.content}
    </div>
  );
}

/**
 * Forest plot of paired differences (A − B) with 95% CIs, one row per group.
 * Significant rows (p < 0.05) get a filled dot, others hollow: the verdict never rides on color alone.
 */
export function ForestPlot({ rows, aLabel, bLabel }: { rows: Breakdown[]; aLabel: string; bLabel: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const valid = rows.filter((r) => r.diff.mean_diff != null && r.diff.lo != null && r.diff.hi != null);
  if (!valid.length) return <p className="muted">No complete pairs yet.</p>;

  const labelW = Math.min(190, Math.max(110, width * 0.32));
  const rowH = 30;
  const top = 8;
  const bottom = 30;
  const h = top + valid.length * rowH + bottom;
  const extent = Math.max(0.05, ...valid.flatMap((r) => [Math.abs(r.diff.lo!), Math.abs(r.diff.hi!)])) * 1.1;
  const plotL = labelW + 8;
  const plotR = Math.max(plotL + 40, width - 12);
  const x = (v: number) => plotL + ((v + extent) / (2 * extent)) * (plotR - plotL);
  const ticks = [-extent, -extent / 2, 0, extent / 2, extent].map((t) => Math.round(t * 100) / 100);

  return (
    <div ref={ref} style={{ position: "relative" }} onMouseLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={width} height={h} role="img" aria-label={`Paired difference ${aLabel} minus ${bLabel} by group`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={top} y2={h - bottom} stroke={t === 0 ? "var(--axis)" : "var(--grid)"}
                    strokeWidth={t === 0 ? 1.5 : 1} />
              <text x={x(t)} y={h - bottom + 16} textAnchor="middle" className="num">{signed(t, 2)}</text>
            </g>
          ))}
          <text x={plotL} y={h - 2} textAnchor="start">← {bLabel} better</text>
          <text x={plotR} y={h - 2} textAnchor="end">{aLabel} better →</text>
          {valid.map((r, i) => {
            const cy = top + i * rowH + rowH / 2;
            const sig = (r.diff.p_value ?? 1) < 0.05;
            return (
              <g key={r.key}
                 onMouseMove={(e) => {
                   const box = ref.current!.getBoundingClientRect();
                   setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content: (
                     <div>
                       <strong>{r.key}</strong>
                       <div>A − B {signed(r.diff.mean_diff)} [{signed(r.diff.lo)}, {signed(r.diff.hi)}]</div>
                       <div>{pValue(r.diff.p_value)} · n = {r.diff.n}</div>
                       <div className="muted">A {r.a.mean?.toFixed(3)} · B {r.b.mean?.toFixed(3)}</div>
                     </div>
                   ) });
                 }}>
                <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill="transparent" />
                <text x={labelW} y={cy + 4} textAnchor="end" className="label-strong">
                  {r.key.length > 26 ? `${r.key.slice(0, 25)}…` : r.key}
                </text>
                <line x1={x(r.diff.lo!)} x2={x(r.diff.hi!)} y1={cy} y2={cy} stroke="var(--text-2)" strokeWidth={2}
                      strokeLinecap="round" />
                <circle cx={x(r.diff.mean_diff!)} cy={cy} r={5} strokeWidth={2} stroke="var(--text)"
                        fill={sig ? "var(--text)" : "var(--surface)"} />
              </g>
            );
          })}
        </svg>
      )}
      <div className="legend" style={{ marginTop: 4 }}>
        <span><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="var(--text)" /></svg>significant (p &lt; 0.05)</span>
        <span><svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="none" stroke="var(--text)" strokeWidth="1.5" /></svg>not significant</span>
        <span>bars: 95% CI of A − B surplus share</span>
      </div>
      <Tooltip tip={tip} />
    </div>
  );
}

/** Mix two hex colors. */
function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * t)).join(",")})`;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Pair matrix: cell = row agent's mean surplus share against the column agent.
 * Diverging around 0.5 (an even split): blue = row captures more, red = less, gray = even.
 */
export function Heatmap({ labels, cells }: {
  labels: string[];
  cells: { row: string; col: string; mean_share: number; n: number }[];
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const lookup = new Map(cells.map((c) => [`${c.row}|${c.col}`, c]));
  const [neg, mid, pos] = ["--div-neg", "--div-mid", "--div-pos"].map(cssVar);
  const color = (share: number) => {
    const d = Math.max(-0.5, Math.min(0.5, share - 0.5)) / 0.5;
    return d >= 0 ? mix(mid, pos, d) : mix(mid, neg, -d);
  };
  const short = (s: string) => (s.length > 16 ? `${s.slice(0, 15)}…` : s);
  const labelW = 130;
  const size = Math.max(34, Math.min(72, (width - labelW - 4) / Math.max(labels.length, 1)));
  const headH = 64;

  return (
    <div ref={ref} style={{ position: "relative", overflowX: "auto" }} onMouseLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={labelW + size * labels.length + 70} height={headH + size * labels.length + 4}
             role="img" aria-label="Mean surplus share of row agent against column agent">
          {labels.map((l, j) => (
            <text key={l} transform={`translate(${labelW + j * size + size / 2},${headH - 6}) rotate(-35)`}
                  className="label-strong">{short(l)}</text>
          ))}
          {labels.map((row, i) => (
            <g key={row}>
              <text x={labelW - 8} y={headH + i * size + size / 2 + 4} textAnchor="end" className="label-strong">
                {short(row)}
              </text>
              {labels.map((col, j) => {
                const c = lookup.get(`${row}|${col}`);
                const x = labelW + j * size;
                const y = headH + i * size;
                if (!c) return <rect key={col} x={x + 1} y={y + 1} width={size - 2} height={size - 2} rx={4}
                                     fill="var(--surface-2)" />;
                const strong = Math.abs(c.mean_share - 0.5) > 0.3;
                return (
                  <g key={col}
                     onMouseMove={(e) => {
                       const box = ref.current!.getBoundingClientRect();
                       setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content: (
                         <div><strong>{row}</strong> vs {col}<div>mean share {c.mean_share.toFixed(3)} · n = {c.n}</div></div>
                       ) });
                     }}>
                    <rect x={x + 1} y={y + 1} width={size - 2} height={size - 2} rx={4} fill={color(c.mean_share)} />
                    {size >= 40 && (
                      <text x={x + size / 2} y={y + size / 2 + 4} textAnchor="middle" className="num"
                            style={{ fill: strong ? "#fff" : "var(--text)" }}>
                        {c.mean_share.toFixed(2)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      )}
      <div className="legend" style={{ marginTop: 6 }}>
        <span><i className="swatch" style={{ background: "var(--div-neg)" }} />row captures less</span>
        <span><i className="swatch" style={{ background: "var(--div-mid)" }} />even split (0.5)</span>
        <span><i className="swatch" style={{ background: "var(--div-pos)" }} />row captures more</span>
      </div>
      <Tooltip tip={tip} />
    </div>
  );
}
