import { useMemo, useState } from 'react';
import { Card, ScoreChip, Timeline, VerdictChip } from '../charts';
import { backendLabel, dateTime, duration, num, pct, stripFences, truncate } from '../format';
import { askKey as joinedAskKey, askTimeline, distinctRows, modelScore, questionStats, resultKey, resultVerdict, traceObserved } from '../metrics';
import type { EvalQuestionRow, EvalResultRow, EvalRunRow, FabricIqQueryRow } from '../generated/contract';

export function Questions({ results, questions, runs, backend = 'all', queries, initialQuestion = null }: {
  results: EvalResultRow[]; questions: EvalQuestionRow[]; runs: EvalRunRow[]; backend?: string; queries: FabricIqQueryRow[]; initialQuestion?: string | null;
}) {
  const stats = useMemo(() => questionStats(results, questions, runs, backend), [results, questions, runs, backend]);
  const [selected, setSelected] = useState<string | null>(initialQuestion);
  const current = stats.find((s) => s.questionId === selected) ?? null;
  const history = useMemo(
    () => results.filter((r) => r.questionId === selected).sort((a, b) => (b.askStartUtc?.getTime() ?? 0) - (a.askStartUtc?.getTime() ?? 0)),
    [results, selected],
  );
  const [askKey, setAskKey] = useState<string | null>(null);
  const keyOf = resultKey;
  const ask = history.find((r) => keyOf(r) === askKey) ?? history[0] ?? null;
  const dax = ask ? distinctRows(queries.filter((q) => joinedAskKey(q) === joinedAskKey(ask))).sort((a, b) => (a.offsetMs ?? 0) - (b.offsetMs ?? 0)) : [];

  return (
    <div className="ev-page">
      <Card title="Golden questions">
        <table className="ev-table ev-clickable">
          <thead>
            <tr><th>ID</th><th>Question</th><th>Latest score</th><th className="ev-num">Score pass rate</th><th className="ev-num">Asks / scores</th>
              <th className="ev-num">Observed model sets</th><th className="ev-num">Value range</th><th className="ev-num">p50</th></tr>
          </thead>
          <tbody>
            {stats.map((s) => (
              <tr key={s.questionId} tabIndex={0}
                onClick={() => { setSelected(s.questionId); setAskKey(null); }}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(s.questionId); setAskKey(null); } }}
                className={s.questionId === selected ? 'ev-selected' : ''}>
                <td>{s.questionId}{s.criticality === 'critical' && <span className="ev-tag">critical</span>}</td>
                <td>{truncate(s.question, 90)}</td>
                <td>{s.latest ? <VerdictChip verdict={s.latestVerdict} /> : 'Pending scores'}</td>
                <td className="ev-num">{pct(s.passRate)}{s.missingScores > 0 && <div className="ev-muted">{s.missingScores} pending</div>}</td>
                <td className="ev-num">{s.asks} / {s.scores}</td>
                <td className={`ev-num ${s.distinctModelSets > 1 ? 'ev-warn-text' : ''}`}>{s.distinctModelSets}</td>
                <td className="ev-num">{s.valueMin === null ? '–' : s.valueMin === s.valueMax ? num(s.valueMin, 2) : `${num(s.valueMin, 2)}–${num(s.valueMax, 2)}`}</td>
                <td className="ev-num">{duration(s.latencyP50)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="ev-note">Select a question to see what Copilot answered, what it cited, its own explanation and the DAX Fabric IQ ran.</p>
      </Card>

      {current && !ask && <Card title={`${current.questionId}: ${truncate(current.question, 80)}`}><p className="ev-note">Pending scores: the golden question is known, but no backend result is available. Missing data is not a successful evaluation.</p></Card>}
      {current && ask && (
        <div className="ev-grid2">
          <Card title={`${current.questionId}: ${truncate(current.question, 80)}`} actions={
            <select value={keyOf(ask)} onChange={(e) => setAskKey(e.target.value)} aria-label="Ask">
              {history.map((r) => (
                <option key={keyOf(r)} value={keyOf(r)}>{`${dateTime(r.askStartUtc)} · try ${r.attempt} · ${r.backend === 'foundry' ? 'Option 2' : 'Option 1'} · ${resultVerdict(r)}`}</option>
              ))}
            </select>
          }>
            <div className="ev-chips">
              <VerdictChip verdict={resultVerdict(ask)} />
              <ScoreChip label="Value" score={ask.valueScore} />
              <ScoreChip label="Artifact" score={ask.artifactScore} />
              <ScoreChip label="Model" score={modelScore(ask)} />
              <ScoreChip label="Judge" score={ask.judgeAnswerScore} />
              <ScoreChip label="Why" score={ask.whyScore} />
            </div>
            <dl className="ev-facts">
              <dt>Scored by</dt><dd>{backendLabel(ask.backend)}</dd>
              <dt>Expected</dt><dd>{num(ask.expectedValue, 4)} from <b>{ask.expectedArtifact}</b> ({ask.expectedModel})</dd>
              <dt>Copilot answered</dt><dd>{ask.answerPreview || ask.error || '–'}</dd>
              <dt>Value found</dt><dd>{num(ask.extractedValue, 4)}{ask.valueErrorPct !== null && ` (${num(ask.valueErrorPct, 2)}% off)`}</dd>
              <dt>Cited</dt><dd>{ask.citedArtifacts || 'nothing'}</dd>
              <dt>Fabric IQ queried</dt><dd>{ask.queriedModels || (ask.traceStatus === 'disabled' ? 'DAX capture off' : traceObserved(ask) ? 'query details not available' : 'DAX evidence not available')} <span className="ev-muted">({ask.traceStatus || 'missing'}{ask.traceStatus === 'observed' ? ' · time-window heuristic' : ''})</span></dd>
              <dt>Copilot's 'why'</dt><dd className="ev-pre">{stripFences(ask.whyPreview) || '–'}</dd>
              {ask.reasons && (<><dt>Why it failed</dt><dd>{ask.reasons.split(' | ').map((r) => <div key={r}>{r}</div>)}</dd></>)}
              {ask.judgeNotes && (<><dt>Judge notes</dt><dd>{ask.judgeNotes.split(' | ').map((r) => <div key={r}>{r}</div>)}</dd></>)}
            </dl>
          </Card>
          <Card title="Ask timeline and DAX">
            <Timeline bars={askTimeline(ask, queries)} />
            <p className="ev-note">Observed DAX is heuristic time-window evidence, not a guarantee that all queries or their order were captured. Legacy sample status “complete” remains readable.</p>
            {dax.length === 0 && <p className="ev-note">{traceObserved(ask) ? 'No DAX detail rows are available for this ask in this load.' : 'DAX evidence is missing, pending or errored; missing evidence is not a successful model gate.'}</p>}
            {dax.map((q, i) => (
              <details key={`${q.correlationId}-${i}`} open={i === 0}>
                <summary>{`${q.itemName} · ${duration(q.durationMs)} · ended ${duration(q.offsetMs)} after the ask started`}</summary>
                <pre className="ev-code">{q.dax}</pre>
              </details>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
}
