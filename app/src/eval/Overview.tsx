import { touchedDecoy, type Result, type Run } from './data';

const percent = (value: number) => `${Math.round(value * 100)}%`;
const displayDate = (value: string | Date) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value)
    : date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
};

export default function Overview({ runs, results, onExplore }: {
  runs: Run[]; results: Result[]; onExplore: () => void;
}) {
  const latest = runs[0];
  const latestAnswers = results.filter(r => r.runId === latest?.runId);
  const counts = [
    { title: 'Value check', count: latestAnswers.filter(r => r.valueCheck?.toLowerCase() === 'pass').length,
      note: 'matched the expected value' },
    { title: 'Citation check', count: latestAnswers.filter(r => r.citationCheck?.toLowerCase() === 'pass').length,
      note: 'cited the right report' },
    { title: 'Model check', count: latestAnswers.filter(r => r.modelCheck?.toLowerCase() === 'pass').length,
      note: 'queried the right model' },
    { title: 'Decoy touched', count: latestAnswers.filter(touchedDecoy).length, note: 'cited or queried a decoy' },
  ];

  return (
    <>
      <section className="intro">
        <div>
          <span className="pill">LATEST RUN</span>
          <h2>How is Copilot performing?</h2>
          <p>{latest?.label || latest?.runId} · {latest?.passed} of {latest?.answers} answers passed.</p>
        </div>
        <div className="pass-kpi">
          <strong>{percent(Number(latest?.passRate || 0))}</strong>
          <span>Pass rate</span>
        </div>
      </section>
      <section className="panel">
        <div className="section-title">
          <div>
            <h2>Pass rate by run</h2>
            <p>Overall verdict across all answers</p>
          </div>
          <span className="subtle">{runs.length} {runs.length === 1 ? 'run' : 'runs'}</span>
        </div>
        <div className="bars">
          {[...runs].reverse().map(run => (
            <div className="bar-row" key={run.runId}>
              <div className="bar-label">
                <strong>{run.label || run.runId}</strong>
                <small>{displayDate(run.startedUtc)}</small>
              </div>
              <div className="bar-track">
                <div className="bar-fill"
                  style={{ width: `${Math.min(100, Math.max(0, Number(run.passRate) * 100))}%` }} />
              </div>
              <div className="bar-value">
                {percent(Number(run.passRate))}
                <small>{run.passed} / {run.answers} passed</small>
              </div>
            </div>
          ))}
        </div>
      </section>
      <div className="section-title check-heading">
        <div>
          <h2>Checks at a glance</h2>
          <p>{latest?.label || latest?.runId} · {latestAnswers.length} answers</p>
        </div>
        <button className="text-button" onClick={onExplore}>Explore questions →</button>
      </div>
      {!latestAnswers.length ? <div className="message">No answers recorded for the latest run.</div> : (
        <>
          <div className="metric-grid">
            {counts.map(item => (
              <div className="metric" key={item.title}>
                <span>{item.title}</span>
                <strong>
                  {item.count}<small> / {latestAnswers.length}</small>
                </strong>
                <p>{item.note}</p>
              </div>
            ))}
          </div>
          <section className="panel verdict-summary">
            <h2>Latest run verdicts</h2>
            <div>
              {['PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR'].map(verdict => (
                <span key={verdict}>
                  <span className={`badge ${verdict.toLowerCase()}`}>{verdict}</span>{' '}
                  {latestAnswers.filter(r => r.verdict?.toUpperCase() === verdict).length}
                </span>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}
