// Small dependency-free SVG charts for the scorecard.
import type { ReactNode } from 'react';
import { duration, pct, shortDate } from './format';
import type { TimelineBar } from './metrics';

export const COLORS = {
  PASS: '#107c10',
  FAIL: '#c50f1f',
  INCONCLUSIVE: '#c19c00',
  ERROR: '#8a8886',
  'fabric-native': '#117865',
  foundry: '#5b5fc7',
  dax: '#0f6cbd',
  why: '#8764b8',
  answer: '#605e5c',
  grid: '#e1dfdd',
  text: '#605e5c',
} as const;

export interface SeriesPoint { x: Date; y: number | null; label: string }
export interface Series { name: string; color: string; points: SeriesPoint[] }

export function TrendChart({ series, height = 220, yMax = 1, yFormat = (v: number) => pct(v) }: {
  series: Series[]; height?: number; yMax?: number; yFormat?: (v: number) => string;
}) {
  const width = 640;
  const pad = { l: 48, r: 16, t: 12, b: 28 };
  const all = series.flatMap((s) => s.points).filter((p) => p.y !== null);
  if (!all.length) return <Empty text="No runs in this window yet." />;
  const xs = all.map((p) => p.x.getTime());
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs) === x0 ? x0 + 86400000 : Math.max(...xs);
  const top = Math.max(yMax, ...all.map((p) => p.y ?? 0));
  const sx = (t: number) => pad.l + ((t - x0) / (x1 - x0)) * (width - pad.l - pad.r);
  const sy = (v: number) => pad.t + (1 - v / top) * (height - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  return (
    <figure className="ev-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Trend chart">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={sy(t)} y2={sy(t)} stroke={COLORS.grid} />
            <text x={pad.l - 6} y={sy(t) + 4} textAnchor="end" className="ev-axis">{yFormat(t)}</text>
          </g>
        ))}
        <text x={pad.l} y={height - 8} className="ev-axis">{shortDate(new Date(x0))}</text>
        <text x={width - pad.r} y={height - 8} textAnchor="end" className="ev-axis">{shortDate(new Date(x1))}</text>
        {series.map((s) => {
          const pts = s.points.filter((p) => p.y !== null);
          const d = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x.getTime()).toFixed(1)},${sy(p.y ?? 0).toFixed(1)}`).join(' ');
          return (
            <g key={s.name}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={2.5} />
              {pts.map((p) => (
                <circle key={`${s.name}-${p.x.getTime()}-${p.label}`} cx={sx(p.x.getTime())} cy={sy(p.y ?? 0)} r={4} fill={s.color}>
                  <title>{`${s.name} · ${p.label}: ${yFormat(p.y ?? 0)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      <Legend items={series.map((s) => ({ label: s.name, color: s.color }))} />
    </figure>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <figcaption className="ev-legend">
      {items.map((i) => (
        <span key={i.label}><i style={{ background: i.color }} />{i.label}</span>
      ))}
    </figcaption>
  );
}

export interface StackColumn { label: string; title: string; parts: { name: string; value: number; color: string }[] }

export function StackedColumns({ columns, height = 200 }: { columns: StackColumn[]; height?: number }) {
  if (!columns.length) return <Empty text="No runs in this window yet." />;
  const width = 640;
  const pad = { l: 8, r: 8, t: 8, b: 30 };
  const max = Math.max(1, ...columns.map((c) => c.parts.reduce((a, p) => a + p.value, 0)));
  const slot = (width - pad.l - pad.r) / columns.length;
  const bw = Math.min(42, slot * 0.7);
  const scale = (height - pad.t - pad.b) / max;
  return (
    <figure className="ev-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Verdicts by run">
        {columns.map((c, i) => {
          let y = height - pad.b;
          const x = pad.l + i * slot + (slot - bw) / 2;
          return (
            <g key={`${c.label}-${i}`}>
              {c.parts.filter((p) => p.value > 0).map((p) => {
                const h = p.value * scale;
                y -= h;
                return (
                  <rect key={p.name} x={x} y={y} width={bw} height={h} fill={p.color}>
                    <title>{`${c.title} · ${p.name}: ${p.value}`}</title>
                  </rect>
                );
              })}
              <text x={x + bw / 2} y={height - 12} textAnchor="middle" className="ev-axis">{c.label}</text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function HBars({ items, color = COLORS.FAIL, format = (v: number) => String(v) }: {
  items: { label: string; value: number }[]; color?: string; format?: (v: number) => string;
}) {
  if (!items.length) return <Empty text="Nothing to show." />;
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="ev-hbars">
      {items.map((i) => (
        <li key={i.label}>
          <span className="ev-hbars-label">{i.label}</span>
          <span className="ev-hbars-track"><span style={{ width: `${(i.value / max) * 100}%`, background: color }} /></span>
          <span className="ev-hbars-value">{format(i.value)}</span>
        </li>
      ))}
    </ul>
  );
}

export function IndependentHBars({ rows, legend }: {
  rows: { label: string; parts: { name: string; value: number | null; color: string }[] }[];
  legend: { label: string; color: string }[];
}) {
  if (!rows.length) return <Empty text="Nothing to show." />;
  const max = Math.max(...rows.flatMap((r) => r.parts.map((p) => p.value ?? 0)), 1);
  return (
    <figure className="ev-chart">
      <ul className="ev-hbars">
        {rows.map((r) => (
            <li key={r.label}>
              <span className="ev-hbars-label">{r.label}</span>
              <span className="ev-independent-bars">
                {r.parts.map((p) => (
                  <span key={p.name} className="ev-hbars-track" title={`${p.name}: ${duration(p.value)}`}>
                    <span style={{ width: `${((p.value ?? 0) / max) * 100}%`, background: p.color }} />
                  </span>
                ))}
              </span>
              <span className="ev-hbars-value ev-independent-values">
                {r.parts.map((p) => <span key={p.name} title={p.name}>{duration(p.value)}</span>)}
              </span>
            </li>
        ))}
      </ul>
      <Legend items={legend} />
    </figure>
  );
}

export function Histogram({ buckets, color = COLORS.dax }: { buckets: { from: number; to: number; count: number }[]; color?: string }) {
  if (!buckets.length) return <Empty text="No latency data yet." />;
  const width = 640;
  const height = 180;
  const pad = { l: 8, r: 8, t: 8, b: 26 };
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const bw = (width - pad.l - pad.r) / buckets.length;
  return (
    <figure className="ev-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Latency distribution">
        {buckets.map((b, i) => {
          const h = (b.count / max) * (height - pad.t - pad.b);
          return (
            <g key={b.from}>
              <rect x={pad.l + i * bw + 1} y={height - pad.b - h} width={Math.max(bw - 2, 1)} height={h} fill={color}>
                <title>{`${duration(b.from)}–${duration(b.to)}: ${b.count} asks`}</title>
              </rect>
              {i % Math.ceil(buckets.length / 8) === 0 && (
                <text x={pad.l + i * bw} y={height - 8} className="ev-axis">{duration(b.from)}</text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function Timeline({ bars }: { bars: TimelineBar[] }) {
  if (!bars.length) return <Empty text="No timing data." />;
  const width = 640;
  const row = 22;
  const labelW = 150;
  const end = Math.max(...bars.map((b) => b.endMs), 1);
  const sx = (ms: number) => labelW + (ms / end) * (width - labelW - 12);
  const height = bars.length * row + 26;
  const color = (k: TimelineBar['kind']) => (k === 'dax' ? COLORS.dax : k === 'why' ? COLORS.why : COLORS.answer);
  return (
    <figure className="ev-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Ask timeline">
        {bars.map((b, i) => (
          <g key={`${b.kind}-${i}`}>
            <text x={labelW - 8} y={i * row + 15} textAnchor="end" className="ev-axis">{b.label}</text>
            <rect x={sx(b.startMs)} y={i * row + 4} width={Math.max(sx(b.endMs) - sx(b.startMs), 2)} height={row - 8} rx={3} fill={color(b.kind)}>
              <title>{`${b.label}: ${duration(b.startMs)} → ${duration(b.endMs)}${b.detail ? `\n${b.detail.slice(0, 300)}` : ''}`}</title>
            </rect>
          </g>
        ))}
        <text x={labelW} y={height - 6} className="ev-axis">0</text>
        <text x={width - 12} y={height - 6} textAnchor="end" className="ev-axis">{duration(end)}</text>
      </svg>
      <Legend items={[{ label: 'Copilot answer', color: COLORS.answer }, { label: "Follow-up 'why'", color: COLORS.why }, { label: 'DAX query (Fabric IQ)', color: COLORS.dax }]} />
    </figure>
  );
}

export function Empty({ text }: { text: string }) {
  return <p className="ev-empty">{text}</p>;
}

export function Card({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="ev-card">
      <header>
        <h3>{title}</h3>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'good' | 'warn' | 'bad' }) {
  return (
    <div className={`ev-kpi ${tone ? `ev-${tone}` : ''}`}>
      <span className="ev-kpi-label">{label}</span>
      <span className="ev-kpi-value">{value}</span>
      {hint && <span className="ev-kpi-hint">{hint}</span>}
    </div>
  );
}

export function VerdictChip({ verdict }: { verdict: string | null }) {
  const v = verdict ?? '–';
  return <span className={`ev-chip ev-chip-${v.toLowerCase()}`}>{v}</span>;
}

export function ScoreChip({ label, score }: { label: string; score: number | null }) {
  const state = score === null ? 'na' : score >= 1 ? 'pass' : score <= 0 ? 'fail' : score === 0.5 ? 'inconclusive' : score >= 0.75 ? 'pass' : 'fail';
  const text = score === null ? 'n/a' : score === 1 || score === 0 || score === 0.5 ? { pass: 'pass', fail: 'fail', inconclusive: '?', na: 'n/a' }[state] : score.toFixed(2);
  return <span className={`ev-chip ev-chip-${state}`}>{label}: {text}</span>;
}
