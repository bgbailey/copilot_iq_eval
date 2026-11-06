import { COLORS, Card, HBars, Kpi, StackedColumns, TrendChart, type Series } from '../charts';
import { backendLabel, duration, num, pct, shortDate } from '../format';
import { BACKENDS, VERDICTS, failureReasons, kpis, routingMatrix, type RunPoint } from '../metrics';
import type { EvalResultRow } from '../generated/contract';

export function Overview({ results, points, complete = true }: { results: EvalResultRow[]; points: RunPoint[]; complete?: boolean }) {
  const k = kpis(results, complete);
  const tone = (v: number | null, good = 0.9, warn = 0.7) => (v === null ? undefined : v >= good ? 'good' : v >= warn ? 'warn' : 'bad');
  const series: Series[] = BACKENDS.map((b) => ({
    name: backendLabel(b),
    color: COLORS[b],
    points: points.filter((p) => p.backend === b && p.startedUtc).map((p) => ({ x: p.startedUtc as Date, y: p.passRate, label: p.runName })),
  })).filter((s) => s.points.length > 0);
  const columns = points.map((p) => ({
    label: shortDate(p.startedUtc),
    title: `${p.runName} (${backendLabel(p.backend)})`,
    parts: VERDICTS.map((v) => ({ name: v, value: p.verdicts[v], color: COLORS[v] })),
  }));
  const reasons = failureReasons(results).map((r) => ({ label: r.label, value: r.count }));
  const routing = routingMatrix(results);
  return (
    <div className="ev-page">
      <div className="ev-kpis">
        <Kpi label="Pass rate" value={pct(k.passRate)} hint={`${k.pass} of ${k.scores} backend scores · ${k.asks} asks${complete ? '' : ' · incomplete'}`} tone={tone(k.passRate)} />
        <Kpi label="Correct value" value={pct(k.valueAccuracy)} hint="answer within tolerance" tone={tone(k.valueAccuracy)} />
        <Kpi label="Right report cited" value={pct(k.artifactAccuracy)} hint="Copilot's citations" tone={tone(k.artifactAccuracy)} />
        <Kpi label="Right model queried" value={pct(k.modelAccuracy)} hint="from the DAX Fabric IQ ran" tone={tone(k.modelAccuracy)} />
        <Kpi label="Decoy rate" value={pct(k.decoyRate)} hint="cited or queried a decoy" tone={k.decoyRate === null ? undefined : k.decoyRate === 0 ? 'good' : k.decoyRate < 0.1 ? 'warn' : 'bad'} />
        <Kpi label="Latency p50 / p95" value={`${duration(k.latencyP50)} / ${duration(k.latencyP95)}`} hint="Copilot answer time" />
        <Kpi label="DAX per ask" value={num(k.daxPerAsk, 1)} hint={`p50 ${duration(k.daxMsP50)} captured DAX work`} />
        <Kpi label="Errors" value={num(k.error)} hint={`${k.inconclusive} inconclusive backend scores`} tone={k.error ? 'bad' : undefined} />
      </div>
      <p className="ev-note">Accuracy counts backend scores, not combined ask verdicts. Answer latency counts each non-error ask once. {complete ? '' : 'Incomplete telemetry: accuracy is withheld.'}</p>
      <div className="ev-grid2">
        <Card title="Pass rate by run"><TrendChart series={series} /></Card>
        <Card title="Verdicts by run"><StackedColumns columns={columns} /></Card>
      </div>
      <div className="ev-grid2">
        <Card title="Why asks fail"><HBars items={reasons} /></Card>
        <Card title="Routing: expected model vs models Fabric IQ queried">
          <table className="ev-table">
            <thead><tr><th>Expected model</th><th>Queried</th><th className="ev-num">Asks</th></tr></thead>
            <tbody>
              {routing.map((r) => (
                <tr key={`${r.expected}-${r.queried}`} className={r.observed && r.queried !== r.expected ? 'ev-row-warn' : ''}>
                  <td>{r.expected}</td><td>{r.queried}{r.traceStatus === 'observed' && <span className="ev-muted"> · observed (heuristic)</span>}</td><td className="ev-num">{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
