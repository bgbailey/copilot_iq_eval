import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '@/hooks/auth.context';
import { loadLive, sampleData, touchedDecoy, type Data, type Result } from './data';
import './eval.css';

const configured = import.meta.env.VITE_EVAL_DATA || 'auto';
const number = (value: number | null | undefined) => value == null ? 'Not found' : Number(value).toLocaleString('en-US', { maximumFractionDigits: 4 });
const percent = (value: number) => `${Math.round(value * 100)}%`;
const displayDate = (value: string | Date) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
};
const timestamp = (value: string | Date) => {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
};

function Check({ label, status, reason }: { label: string; status: string; reason: string }) {
  const state = status?.toLowerCase() || 'skipped';
  return <div className="check"><div><strong>{label}</strong><span className={`badge ${state}`}>{status || 'not checked'}</span></div><p>{reason || 'No reason recorded'}</p></div>;
}

export default function EvalApp() {
  const auth = useAuth();
  const [mode, setMode] = useState<'live' | 'sample'>(configured === 'sample' ? 'sample' : 'live');
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState<'overview' | 'questions'>('overview');
  const [runId, setRunId] = useState('');
  const [selected, setSelected] = useState('');

  useEffect(() => {
    let active = true;
    setData(null); setError(''); setRunId(''); setSelected('');
    if (!['auto', 'live', 'sample'].includes(configured)) { setError(`Unknown VITE_EVAL_DATA value: ${configured}`); return; }
    if (mode === 'sample') { setData(sampleData); setLoading(false); return; }
    if (!auth.isAuthenticated) { setLoading(false); return; }
    setLoading(true);
    loadLive().then(value => { if (active) setData(value); }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, auth.isAuthenticated]);

  const runs = useMemo(() => [...(data?.runs || [])].sort((a, b) => timestamp(b.startedUtc) - timestamp(a.startedUtc)), [data]);
  const currentId = runId && runs.some(run => run.runId === runId) ? runId : runs[0]?.runId;
  const answers = useMemo(() => (data?.results || []).filter(r => r.runId === currentId).sort((a, b) => a.questionId.localeCompare(b.questionId) || a.attempt - b.attempt), [data, currentId]);
  const latest = runs[0];
  const latestAnswers = (data?.results || []).filter(r => r.runId === latest?.runId);
  const key = (r: Result) => `${r.questionId}\u0000${r.attempt}`;
  const detail = answers.find(r => key(r) === selected) || answers[0];
  const queries = (data?.queries || []).filter(q => detail && q.runId === detail.runId && q.questionId === detail.questionId && q.attempt === detail.attempt).sort((a, b) => timestamp(a.timestamp) - timestamp(b.timestamp));
  const counts = [
    { title: 'Value check', count: latestAnswers.filter(r => r.valueCheck?.toLowerCase() === 'pass').length, note: 'matched the expected value' },
    { title: 'Citation check', count: latestAnswers.filter(r => r.citationCheck?.toLowerCase() === 'pass').length, note: 'cited the right report' },
    { title: 'Model check', count: latestAnswers.filter(r => r.modelCheck?.toLowerCase() === 'pass').length, note: 'queried the right model' },
    { title: 'Decoy touched', count: latestAnswers.filter(touchedDecoy).length, note: 'cited or queried a decoy' },
  ];

  return <div className="scorecard">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">C</div><div><strong>Copilot IQ</strong><small>Evaluation scorecard</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Scorecard pages">
        <button className={page === 'overview' ? 'active' : ''} onClick={() => setPage('overview')}>Overview</button>
        <button className={page === 'questions' ? 'active' : ''} onClick={() => setPage('questions')}>Questions</button>
      </nav>
      <div className="sidebar-footer"><span className="status-dot" /> {mode === 'sample' ? 'Sample data' : 'Live data'}<small>Fabric evaluation accelerator</small></div>
    </aside>
    <main>
      <header className="topbar"><div>ANALYTICS <span>/</span> {page === 'overview' ? 'OVERVIEW' : 'QUESTIONS'}</div><div className="top-actions"><span className={`source ${mode}`}>{mode === 'sample' ? '●  Sample data' : '●  Live data'}</span>{configured === 'auto' && <button className="switch" onClick={() => setMode(mode === 'sample' ? 'live' : 'sample')}>Switch to {mode === 'sample' ? 'live' : 'sample'}</button>}</div></header>
      <div className="content">
        <div className="heading"><div><div className="eyebrow">COPILOT EVALUATION</div><h1>{page === 'overview' ? 'Scorecard overview' : 'Question results'}</h1><p>{page === 'overview' ? 'Track answer quality and see where your model can improve.' : 'Explore the verdict and evidence behind each answer.'}</p></div>
          {page === 'questions' && runs.length > 0 && <label className="run-picker">SELECT RUN<select value={currentId || ''} onChange={e => { setRunId(e.target.value); setSelected(''); }}>{runs.map(run => <option key={run.runId} value={run.runId}>{run.label || run.runId}</option>)}</select></label>}
        </div>
        {loading || (mode === 'live' && auth.isLoading) ? <div className="message">Loading evaluation results…</div>
          : error ? <div className="message error" role="alert"><strong>Couldn't load evaluation results.</strong><p>{error}</p></div>
          : mode === 'live' && !auth.isAuthenticated ? <div className="message"><h2>Sign in to view live results</h2><p>{auth.error?.message || 'Live data requires a deployed app and access to the evals connector.'}</p>{auth.canSignIn && <button className="primary" onClick={() => void auth.signIn()} disabled={auth.isSigningIn}>{auth.isSigningIn ? 'Signing in…' : 'Sign in with Microsoft'}</button>}{auth.signInError && <p role="alert">{auth.signInError.message}</p>}{configured === 'auto' && <p>Or switch to sample data to explore the scorecard.</p>}</div>
          : !runs.length ? <div className="message"><h2>No runs yet</h2><p>Run an evaluation and publish the results to see them here.</p></div>
          : page === 'overview' ? <>
            <section className="intro"><div><span className="pill">LATEST RUN</span><h2>How is Copilot performing?</h2><p>{latest?.label || latest?.runId} · {latest?.passed} of {latest?.answers} answers passed.</p></div><div className="pass-kpi"><strong>{percent(Number(latest?.passRate || 0))}</strong><span>Pass rate</span></div></section>
            <section className="panel"><div className="section-title"><div><h2>Pass rate by run</h2><p>Overall verdict across all answers</p></div><span className="subtle">{runs.length} {runs.length === 1 ? 'run' : 'runs'}</span></div>
              <div className="bars">{[...runs].reverse().map(run => <div className="bar-row" key={run.runId}><div className="bar-label"><strong>{run.label || run.runId}</strong><small>{displayDate(run.startedUtc)}</small></div><div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, Number(run.passRate) * 100))}%` }} /></div><div className="bar-value">{percent(Number(run.passRate))}<small>{run.passed} / {run.answers} passed</small></div></div>)}</div>
            </section>
            <div className="section-title check-heading"><div><h2>Checks at a glance</h2><p>{latest?.label || latest?.runId} · {latestAnswers.length} answers</p></div><button className="text-button" onClick={() => setPage('questions')}>Explore questions →</button></div>
            {!latestAnswers.length ? <div className="message">No answers recorded for the latest run.</div> : <><div className="metric-grid">{counts.map(item => <div className="metric" key={item.title}><span>{item.title}</span><strong>{item.count}<small> / {latestAnswers.length}</small></strong><p>{item.note}</p></div>)}</div><section className="panel verdict-summary"><h2>Latest run verdicts</h2><div>{['PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR'].map(verdict => <span key={verdict}><span className={`badge ${verdict.toLowerCase()}`}>{verdict}</span> {latestAnswers.filter(r => r.verdict?.toUpperCase() === verdict).length}</span>)}</div></section></>}
          </> : !answers.length ? <div className="message">No answers recorded for this run.</div> : <div className="question-layout">
            <section className="panel question-list"><div className="section-title"><div><h2>All questions</h2><p>{answers.length} answers in this run · select a question to inspect its evidence</p></div></div>
              <div className="table-scroll"><table><thead><tr><th>QuestionId</th><th>Attempt</th><th>Verdict</th><th>ValueReason</th><th>CitationReason</th><th>ModelReason</th></tr></thead><tbody>
              {answers.map(r => <tr key={key(r)} className={detail && key(detail) === key(r) ? 'selected' : ''}><td><button className="question-select" onClick={() => setSelected(key(r))} aria-pressed={!!detail && key(detail) === key(r)}>{r.questionId}</button></td><td>{r.attempt}</td><td><span className={`badge ${r.verdict?.toLowerCase()}`}>{r.verdict}</span></td><td>{r.valueReason || 'No reason recorded'}</td><td>{r.citationReason || 'No reason recorded'}</td><td>{r.modelReason || 'No reason recorded'}</td></tr>)}
              </tbody></table></div>
            </section>
            {detail && <section className="panel detail"><div className="detail-top"><div><span className="eyebrow">QUESTION {detail.questionId} · ATTEMPT {detail.attempt}</span><h2>{detail.question}</h2></div><span className={`badge ${detail.verdict?.toLowerCase()}`}>{detail.verdict}</span></div>
              <div className="answer-box"><div className="detail-label">COPILOT'S ANSWER</div><p>{detail.answer || 'No answer recorded.'}</p></div>
              <div className="value-pair"><div><span>EXPECTED VALUE</span><strong>{number(detail.expected)}</strong></div><div><span>FOUND VALUE</span><strong>{number(detail.found)}</strong></div></div>
              <h3>Evaluation checks</h3><div className="checks"><Check label="Value" status={detail.valueCheck} reason={detail.valueReason} /><Check label="Citation" status={detail.citationCheck} reason={detail.citationReason} /><Check label="Model" status={detail.modelCheck} reason={detail.modelReason} /></div>
              <h3>Evidence</h3><div className="evidence"><div><span>CITED REPORTS</span><p>{detail.citedReports || 'None recorded'}</p></div><div><span>QUERIED MODELS</span><p>{detail.queriedModels || 'None recorded'}</p></div></div>
              <div className="detail-label dax-label">DAX QUERIES <span>{queries.length}</span></div>{queries.length ? queries.map((query, i) => <div className="query" key={i}><div>{query.semanticModel || 'Unknown model'} {query.durationMs != null && <span>· {number(query.durationMs)} ms</span>}</div><pre>{query.dax || 'No query text recorded'}</pre></div>) : <p className="subtle">No DAX queries recorded for this answer.</p>}
            </section>}
          </div>}
      </div>
    </main>
  </div>;
}
