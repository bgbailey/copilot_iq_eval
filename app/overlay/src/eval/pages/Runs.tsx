import { Card, Kpi } from '../charts';
import { backendLabel, dateTime, duration, pct } from '../format';
import { backendAgreement, kpis, type RunPoint } from '../metrics';
import type { EvalResultRow, EvalRunRow } from '../generated/contract';

export function Runs({ runs, points, results }: { runs: EvalRunRow[]; points: RunPoint[]; results: EvalResultRow[] }) {
  const agreement = backendAgreement(results);
  const byRun = new Map<string, RunPoint[]>();
  for (const p of points) byRun.set(p.runId, [...(byRun.get(p.runId) ?? []), p]);
  return (
    <div className="ev-page">
      <div className="ev-kpis">
        <Kpi label="Runs" value={String(runs.length)} />
        <Kpi label="Live runs" value={String(runs.filter((r) => r.surface === 'copilot-chat-api').length)} hint="Copilot Chat API" />
        <Kpi label="Option 1 vs Option 2 agreement" value={pct(agreement.rate)} hint={`${agreement.asks} asks scored by both`} />
      </div>
      <Card title="Evaluation runs">
        <table className="ev-table">
          <thead>
            <tr><th>Started</th><th>Run</th><th>Scored by</th><th>Data</th><th className="ev-num">Asks</th><th className="ev-num">Score pass rate</th>
              <th className="ev-num">Value</th><th className="ev-num">Artifact</th><th className="ev-num">Model</th><th className="ev-num">p50</th><th className="ev-num">p95</th><th>Foundry report</th></tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const pts = byRun.get(r.runId ?? '') ?? [];
              const complete = pts.length > 0 && pts.every((p) => p.complete);
              const k = kpis(results.filter((row) => row.runId === r.runId), complete);
              return (
                <tr key={r.runId}>
                  <td>{dateTime(r.startedUtc)}</td>
                  <td title={r.runId ?? ''}>{r.runName}</td>
                  <td>{pts.length ? pts.map((p) => <div key={p.backend}>{backendLabel(p.backend)}: {p.complete ? pct(p.passRate) : `incomplete (${p.asks}/${p.expectedAsks ?? '?'} asks)`}</div>) : `${r.evalOption || 'Unknown backend'} · incomplete`}</td>
                  <td>{r.surface === 'simulated' ? <span className="ev-tag">simulated</span> : r.surface === 'copilot-chat-api' ? 'live' : 'unknown'}</td>
                  <td className="ev-num">{k.asks} / {r.askCount ?? '?'}</td>
                  <td className="ev-num">{pct(k.passRate)}<div className="ev-muted">{k.scores} scores</div></td>
                  <td className="ev-num">{pct(k.valueAccuracy)}</td>
                  <td className="ev-num">{pct(k.artifactAccuracy)}</td>
                  <td className="ev-num">{pct(k.modelAccuracy)}</td>
                  <td className="ev-num">{duration(k.latencyP50)}</td>
                  <td className="ev-num">{duration(k.latencyP95)}</td>
                  <td>{r.foundryReportUrl ? <a href={r.foundryReportUrl} target="_blank" rel="noreferrer">Open</a> : '–'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
