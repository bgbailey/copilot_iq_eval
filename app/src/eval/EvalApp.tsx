import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useAuth } from '@/hooks/auth.context';
import { loadLive, sampleData, type Data } from './data';
import Overview from './Overview';
import Questions from './Questions';
import './eval.css';

const configured = import.meta.env.VITE_EVAL_DATA || 'auto';
const timestamp = (value: string | Date) => {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
};

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
    setData(null);
    setError('');
    setRunId('');
    setSelected('');
    if (!['auto', 'live', 'sample'].includes(configured)) {
      setError(`Unknown VITE_EVAL_DATA value: ${configured}`);
      return;
    }
    if (mode === 'sample') {
      setData(sampleData);
      setLoading(false);
      return;
    }
    if (!auth.isAuthenticated) {
      setLoading(false);
      return;
    }
    setLoading(true);
    loadLive()
      .then(value => {
        if (active) {
          setData(value);
        }
      })
      .catch(reason => {
        if (active) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [mode, auth.isAuthenticated]);

  const runs = useMemo(() => [...(data?.runs || [])].sort(
    (a, b) => timestamp(b.startedUtc) - timestamp(a.startedUtc),
  ), [data]);
  const currentId = runId && runs.some(run => run.runId === runId) ? runId : runs[0]?.runId;

  let content: ReactNode;
  if (loading || (mode === 'live' && auth.isLoading)) {
    content = <div className="message">Loading evaluation results…</div>;
  } else if (error) {
    content = (
      <div className="message error" role="alert">
        <strong>Couldn't load evaluation results.</strong>
        <p>{error}</p>
      </div>
    );
  } else if (mode === 'live' && !auth.isAuthenticated) {
    content = (
      <div className="message">
        <h2>Sign in to view live results</h2>
        <p>{auth.error?.message || 'Live data requires a deployed app and access to the evals connector.'}</p>
        {auth.canSignIn && (
          <button className="primary" onClick={() => void auth.signIn()} disabled={auth.isSigningIn}>
            {auth.isSigningIn ? 'Signing in…' : 'Sign in with Microsoft'}
          </button>
        )}
        {auth.signInError && <p role="alert">{auth.signInError.message}</p>}
        {configured === 'auto' && <p>Or switch to sample data to explore the scorecard.</p>}
      </div>
    );
  } else if (!runs.length) {
    content = (
      <div className="message">
        <h2>No runs yet</h2>
        <p>Run an evaluation and publish the results to see them here.</p>
      </div>
    );
  } else if (page === 'overview') {
    content = <Overview runs={runs} results={data?.results || []} onExplore={() => setPage('questions')} />;
  } else {
    content = <Questions data={data} currentId={currentId} selected={selected} onSelect={setSelected} />;
  }

  return (
    <div className="scorecard">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">C</div>
          <div>
            <strong>Copilot + Fabric IQ evaluation</strong>
            <small>Scorecard</small>
          </div>
        </div>
        <nav aria-label="Scorecard pages">
          <button className={page === 'overview' ? 'active' : ''} onClick={() => setPage('overview')}>
            Overview
          </button>
          <button className={page === 'questions' ? 'active' : ''} onClick={() => setPage('questions')}>
            Questions
          </button>
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" /> {mode === 'sample' ? 'Sample data' : 'Live data'}
          <small>Fabric evaluation accelerator</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>{page === 'overview' ? 'OVERVIEW' : 'QUESTIONS'}</div>
          <div className="top-actions">
            <span className={`source ${mode}`}>{mode === 'sample' ? '●  Sample data' : '●  Live data'}</span>
            {configured === 'auto' && (
              <button className="switch" onClick={() => setMode(mode === 'sample' ? 'live' : 'sample')}>
                Switch to {mode === 'sample' ? 'live' : 'sample'}
              </button>
            )}
          </div>
        </header>
        <div className="content">
          <div className="heading">
            <div>
              <div className="eyebrow">COPILOT EVALUATION</div>
              <h1>{page === 'overview' ? 'Scorecard overview' : 'Question results'}</h1>
              <p>{page === 'overview' ? 'Track answer quality and see where your model can improve.'
                : 'Explore the verdict and evidence behind each answer.'}</p>
            </div>
            {page === 'questions' && runs.length > 0 && (
              <label className="run-picker">SELECT RUN
                <select value={currentId || ''} onChange={e => { setRunId(e.target.value); setSelected(''); }}>
                  {runs.map(run => (
                    <option key={run.runId} value={run.runId}>{run.label || run.runId}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {content}
        </div>
      </main>
    </div>
  );
}
