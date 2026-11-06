import { COLORS, Card, Histogram, IndependentHBars, Kpi, TrendChart, type Series } from '../charts';
import { backendLabel, duration, num, pct, truncate } from '../format';
import { kpis, latencyBreakdown, latencyHistogram, slowestQueries, stageDurations, type RunPoint } from '../metrics';
import type { EvalEventRow, EvalResultRow, FabricIqQueryRow } from '../generated/contract';

export function Performance({ results, points, queries, events, complete = true }: {
  results: EvalResultRow[]; points: RunPoint[]; queries: FabricIqQueryRow[]; events: EvalEventRow[]; complete?: boolean;
}) {
  const k = kpis(results, complete);
  const maxLatency = Math.max(1000, ...points.map((p) => p.latencyP95 ?? 0));
  const series: Series[] = [
    { name: 'p50', color: COLORS['fabric-native'], points: points.filter((p) => p.startedUtc).map((p) => ({ x: p.startedUtc as Date, y: p.latencyP50, label: `${p.runName} (${backendLabel(p.backend)})` })) },
    { name: 'p95', color: COLORS.foundry, points: points.filter((p) => p.startedUtc).map((p) => ({ x: p.startedUtc as Date, y: p.latencyP95, label: `${p.runName} (${backendLabel(p.backend)})` })) },
  ];
  const breakdown = latencyBreakdown(results).map((b) => ({
    label: b.questionId,
    parts: [
      { name: 'Answer round trip', value: b.answerMs, color: COLORS.answer },
      { name: 'Captured DAX work (answer + why)', value: b.daxMs, color: COLORS.dax },
      { name: "Follow-up 'why'", value: b.whyMs, color: COLORS.why },
    ],
  }));
  const stages = stageDurations(events);
  return (
    <div className="ev-page">
      <div className="ev-kpis">
        <Kpi label="Answer p50" value={duration(k.latencyP50)} />
        <Kpi label="Answer p95" value={duration(k.latencyP95)} />
        <Kpi label="DAX per ask" value={num(k.daxPerAsk, 1)} />
        <Kpi label="Captured DAX work p50" value={duration(k.daxMsP50)} hint="answer + why queries; may overlap" />
        <Kpi label="Asks with DAX captured" value={pct(k.traceCoverage)} hint="observed / trace-enabled asks · heuristic" />
        <Kpi label="Judge: answer correct" value={pct(k.judgeAnswer)} hint="average backend score" />
      </div>
      <p className="ev-note">Latency uses distinct non-error asks; missing scores are not successes. Captured DAX includes answer and why queries, can overlap and can exceed answer latency. These are independent measures, not an additive or critical-path decomposition.</p>
      <div className="ev-grid2">
        <Card title="Answer latency by run"><TrendChart series={series} yMax={maxLatency} yFormat={(v) => duration(v)} /></Card>
        <Card title="Answer latency distribution"><Histogram buckets={latencyHistogram(results)} /></Card>
      </div>
      <div className="ev-grid2">
        <Card title="Answer latency vs captured DAX work (independent averages)">
          <IndependentHBars rows={breakdown} legend={[{ label: 'Answer round trip', color: COLORS.answer }, { label: 'Captured DAX work (answer + why)', color: COLORS.dax }, { label: "Follow-up 'why'", color: COLORS.why }]} />
        </Card>
        <Card title="Harness stages">
          <table className="ev-table">
            <thead><tr><th>Stage</th><th className="ev-num">Count</th><th className="ev-num">p50</th><th className="ev-num">p95</th><th className="ev-num">Failures</th></tr></thead>
            <tbody>
              {stages.map((s) => (
                <tr key={s.stage}><td>{s.stage}</td><td className="ev-num">{s.count}</td><td className="ev-num">{duration(s.p50)}</td><td className="ev-num">{duration(s.p95)}</td><td className="ev-num">{s.failures}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <Card title="Slowest DAX queries">
        <table className="ev-table">
          <thead><tr><th>Semantic model</th><th className="ev-num">Duration</th><th>Ask</th><th>DAX</th></tr></thead>
          <tbody>
            {slowestQueries(queries).map((q, i) => (
              <tr key={`${q.correlationId}-${i}`}><td>{q.itemName}</td><td className="ev-num">{duration(q.durationMs)}</td><td className="ev-mono">{truncate(q.askId, 44)}</td><td className="ev-mono">{truncate(q.dax, 120)}</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
