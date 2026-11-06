// Copilot Chat x Fabric IQ evaluation scorecard: accuracy, routing, DAX and latency.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './eval.css';
import { configuredMode, loadLive, loadSample } from './dataSource';
import { dateTime } from './format';
import { selectView, type EvalData } from './metrics';
import { allowedSource, createLoadGate, type DataSource } from './loadState';
import { Overview } from './pages/Overview';
import { Performance } from './pages/Performance';
import { Questions } from './pages/Questions';
import { Runs } from './pages/Runs';
import { useAuth } from './useAuth';

const TABS = ['Overview', 'Questions', 'Performance', 'Runs'] as const;
type Tab = (typeof TABS)[number];

export default function EvalApp() {
  const mode = configuredMode();
  const auth = useAuth(mode !== 'sample');
  const [source, setSource] = useState<'live' | 'sample' | null>(mode === 'sample' ? 'sample' : null);
  const [wantLive, setWantLive] = useState(false);
  const gate = useRef(createLoadGate()).current;
  const [days, setDays] = useState(30);
  const [backend, setBackend] = useState('all');
  const [surface, setSurface] = useState('all');
  const [tab, setTab] = useState<Tab>('Overview');
  const [data, setData] = useState<EvalData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chooseSource = useCallback((next: DataSource | null) => {
    if (next && !allowedSource(mode, next)) return;
    gate.invalidate();
    setData(null);
    setError(null);
    setLoading(false);
    setSource(next);
  }, [gate, mode]);

  // A sample viewer's explicit sign-in intent survives until authentication completes.
  useEffect(() => {
    if (auth.isAuthenticated && (source === null || wantLive)) {
      chooseSource('live');
      setWantLive(false);
    } else if (source === 'live' && auth.ready && !auth.isAuthenticated) {
      chooseSource(null);
    }
  }, [auth.isAuthenticated, auth.ready, source, wantLive, chooseSource]);

  const useLive = () => {
    if (auth.isAuthenticated) chooseSource('live');
    else {
      setWantLive(true);
      auth.signIn(); // Keep popup initiation inside this synchronous click.
    }
  };

  const load = useCallback(async () => {
    if (!source) return;
    const request = gate.start();
    setLoading(true);
    setData(null);
    setError(null);
    try {
      const next = source === 'live' ? await loadLive(Math.max(days, 1)) : await loadSample();
      if (gate.isCurrent(request)) setData(next);
    } catch (err) {
      if (gate.isCurrent(request)) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (gate.isCurrent(request)) setLoading(false);
    }
  }, [source, days, gate]);

  useEffect(() => {
    void load();
    return () => gate.invalidate();
  }, [load, gate]);

  const view = useMemo(() => {
    if (!data || data.source !== source || (source === 'live' && !auth.isAuthenticated)) return null;
    return selectView(data, { backend, sinceDays: days, surface });
  }, [data, backend, days, surface, source, auth.isAuthenticated]);

  if (!source) {
    return (
      <div className="ev-app ev-center">
        <h1>Copilot × Fabric IQ evaluation scorecard</h1>
        <p>Sign in with your Fabric account to read the evaluation telemetry{mode === 'auto' ? ', or explore simulated sample data.' : '.'}</p>
        <div className="ev-actions">
          <button type="button" className="ev-primary" onClick={auth.signIn} disabled={!auth.ready}>Sign in with Fabric</button>
          {allowedSource(mode, 'sample') && <button type="button" onClick={() => chooseSource('sample')}>View sample data</button>}
        </div>
        {auth.error && <p className="ev-error">{auth.error}</p>}
      </div>
    );
  }

  return (
    <div className="ev-app">
      <header className="ev-header">
        <div>
          <h1>Copilot × Fabric IQ evaluation scorecard</h1>
          <p className="ev-sub">
            {source === 'live' ? 'Live telemetry from the Eventhouse (via OneLake, a few minutes behind)' : 'Sample data from simulated runs'}
            {view && data && ` · loaded ${dateTime(data.loadedAt)}`}
            {view && data?.truncated && ' · showing the newest rows only'}
          </p>
        </div>
        <div className="ev-filters">
          <label>Scored by
            <select value={backend} onChange={(e) => setBackend(e.target.value)}>
              <option value="all">Both options</option>
              <option value="fabric-native">Option 1 · Fabric-native</option>
              <option value="foundry">Option 2 · Foundry Evaluations</option>
            </select>
          </label>
          <label>Window
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
          <label>Data
            <select value={surface} onChange={(e) => setSurface(e.target.value)}>
              <option value="all">Live and simulated</option>
              <option value="copilot-chat-api">Live only</option>
              <option value="simulated">Simulated only</option>
            </select>
          </label>
          <button type="button" onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
          {source === 'sample' && mode !== 'sample' && <button type="button" onClick={useLive}>Use live data</button>}
          {source === 'live' && mode === 'auto' && <button type="button" onClick={() => { setWantLive(false); chooseSource('sample'); }}>View sample data</button>}
        </div>
      </header>
      <nav className="ev-tabs" aria-label="Scorecard sections">
        {TABS.map((t) => (
          <button type="button" key={t} className={t === tab ? 'ev-active' : ''} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {(error || auth.error) && <p className="ev-error" role="alert">{error || auth.error}</p>}
      {!view && !error && <p className="ev-empty" role="status">Loading evaluation telemetry…</p>}
      {view?.incomplete && <p className="ev-note" role="status">Incomplete telemetry: expected scores, golden questions, or run metadata are missing in this window. Accuracy is withheld until those rows arrive; refresh after OneLake catches up or select a wider window.</p>}
      {view && view.results.length === 0 && <p className="ev-empty">No scores available in this window. Known runs and golden questions remain visible as pending.</p>}
      {view && (
        <main>
          {tab === 'Overview' && <Overview results={view.results} points={view.points} complete={!view.incomplete} />}
          {tab === 'Questions' && <Questions results={view.results} questions={view.questions} runs={view.runs} backend={backend} queries={view.queries} />}
          {tab === 'Performance' && <Performance results={view.results} points={view.points} queries={view.queries} events={view.events} complete={!view.incomplete} />}
          {tab === 'Runs' && <Runs runs={view.runs} points={view.points} results={view.results} />}
        </main>
      )}
    </div>
  );
}
