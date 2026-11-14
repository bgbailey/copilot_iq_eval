// Scorecard metrics over normalized telemetry rows. Pure: no runtime imports, unit-tested with
// node --test. Definitions match the Python harness (pipeline.run_metrics and cfeval.stats) and KQL.
import type { EvalEventRow, EvalQuestionRow, EvalResultRow, EvalRunRow, FabricIqQueryRow } from './generated/contract';

export type Verdict = 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'ERROR';
export const VERDICTS: readonly Verdict[] = ['PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR'];
export const BACKENDS = ['fabric-native', 'foundry'] as const;

const DEFAULT_WILSON_Z = 1.959963984540054;

export interface EvalData {
  runs: EvalRunRow[];
  questions: EvalQuestionRow[];
  results: EvalResultRow[];
  queries: FabricIqQueryRow[];
  events: EvalEventRow[];
  source: 'sample' | 'live';
  loadedAt: Date;
  truncated: boolean;
}

/** Wilson score confidence interval [low, high] matching Python cfeval.stats. */
export function wilsonInterval(successes: number, total: number, z = DEFAULT_WILSON_Z): [number, number] {
  if (!Number.isFinite(total) || !Number.isFinite(successes) || total <= 0) return [0, 0];
  const clamped = Math.max(0, Math.min(successes, total));
  const p = clamped / total;
  const z2 = z * z;
  const denom = 1 + z2 / total;
  const center = (p + z2 / (2 * total)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / total + z2 / (4 * total * total))) / denom;
  return [Math.max(0, center - half), Math.min(1, center + half)];
}

/** Unbiased pass@k estimator: 1 - comb(n - c, k_eff) / comb(n, k_eff). */
export function passAtK(n: number, c: number, k: number): number {
  if (!Number.isFinite(n) || !Number.isFinite(c) || !Number.isFinite(k) || n <= 0 || k <= 0 || c <= 0) return 0;
  const nInt = Math.floor(n);
  const cInt = Math.min(Math.floor(c), nInt);
  const kEff = Math.min(Math.floor(k), nInt);
  if (nInt <= 0 || kEff <= 0 || cInt <= 0) return 0;
  if (nInt - cInt < kEff) return 1;
  let ratio = 1;
  for (let i = 0; i < kEff; i += 1) {
    ratio *= (nInt - cInt - i) / (nInt - i);
  }
  return 1 - ratio;
}

/** Strict reliability metric pass^k: (c / n)^k. */
export function passPowK(n: number, c: number, k: number): number {
  if (!Number.isFinite(n) || !Number.isFinite(c) || !Number.isFinite(k) || n <= 0 || k <= 0 || c <= 0) return 0;
  if (c >= n) return 1;
  return Math.pow(c / n, k);
}

/** Two-sided exact McNemar binomial test p-value on discordant counts (b, c). */
export function mcnemarExactP(b: number, c: number): number {
  if (!Number.isFinite(b) || !Number.isFinite(c) || b < 0 || c < 0) {
    throw new RangeError('Discordant counts b and c must be non-negative finite numbers.');
  }
  const bInt = Math.floor(b);
  const cInt = Math.floor(c);
  const n = bInt + cInt;
  if (n === 0 || bInt === cInt) return 1;
  const m = Math.min(bInt, cInt);
  if (n <= 1000) {
    let term = Math.pow(0.5, n);
    let tail = term;
    for (let i = 1; i <= m; i += 1) {
      term *= (n - i + 1) / i;
      tail += term;
    }
    return Math.min(1, 2 * tail);
  }
  let log2Term = -n;
  let tail = Math.pow(2, log2Term);
  for (let i = 1; i <= m; i += 1) {
    log2Term += Math.log2((n - i + 1) / i);
    tail += Math.pow(2, log2Term);
  }
  return Math.min(1, 2 * tail);
}

/** Linear interpolation between closest ranks (numpy default; same as the harness). */
export function percentile(values: readonly (number | null | undefined)[], p: number): number | null {
  const vals = values.filter((v): v is number => typeof v === 'number' && !Number.isNaN(v)).sort((a, b) => a - b);
  if (vals.length === 0) return null;
  const k = ((vals.length - 1) * p) / 100;
  const lo = Math.floor(k);
  const hi = Math.min(lo + 1, vals.length - 1);
  return Math.round((vals[lo] + (vals[hi] - vals[lo]) * (k - lo)) * 10) / 10;
}

function time(d: Date | null | undefined): number {
  return d ? d.getTime() : 0;
}

function nonEmptyId(id: string | null | undefined): string | null {
  return typeof id === 'string' && id.length > 0 ? id : null;
}

function stableJson(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value !== 'object') return String(value);
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableJson(v)}`).join(',')}}`;
}

export function askKey(row: { runId: string | null; askId: string | null }): string {
  return JSON.stringify([row.runId, row.askId]);
}

export function resultKey(row: EvalResultRow): string {
  return JSON.stringify([row.runId, row.askId, row.backend]);
}

/** Only remove identical records (or matching rowId); never merge conflicting live observations. */
export function distinctRows<T extends object>(rows: readonly T[]): T[] {
  const seenIds = new Set<string>();
  const seenKeys = new Set<string>();
  return rows.filter((row) => {
    const rowId = nonEmptyId((row as { rowId?: string | null }).rowId);
    if (rowId !== null) {
      if (seenIds.has(rowId)) return false;
      seenIds.add(rowId);
    }
    const key = stableJson(row);
    if (seenKeys.has(key)) return false;
    seenKeys.add(key);
    return true;
  });
}

function dedupeQuestions(rows: readonly EvalQuestionRow[]): EvalQuestionRow[] {
  const seenIds = new Set<string>();
  const byKey = new Map<string, EvalQuestionRow>();
  for (const q of rows) {
    const rowId = nonEmptyId(q.rowId);
    if (rowId !== null) {
      if (seenIds.has(rowId)) continue;
      seenIds.add(rowId);
    }
    const key = `${q.runId ?? ''}|${q.questionId ?? ''}`;
    if (!byKey.has(key)) byKey.set(key, q);
  }
  return [...byKey.values()];
}

function dedupeQueries(rows: readonly FabricIqQueryRow[]): FabricIqQueryRow[] {
  const seen = new Set<string>();
  const out: FabricIqQueryRow[] = [];
  for (const q of rows) {
    const key = nonEmptyId(q.rowId)
      ?? `${q.runId ?? ''}|${q.askId ?? ''}|${time(q.queryTimeUtc)}|${q.offsetMs ?? ''}|${q.dax ?? ''}|${q.correlationId ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(q);
  }
  return out;
}

function dedupeEvents(rows: readonly EvalEventRow[]): EvalEventRow[] {
  const seen = new Set<string>();
  const out: EvalEventRow[] = [];
  for (const e of rows) {
    const key = nonEmptyId(e.rowId)
      ?? `${e.runId ?? ''}|${time(e.eventTimeUtc)}|${e.stage ?? ''}|${e.askId ?? ''}|${stableJson(e.details)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}

/** observed is usable, settled time-window evidence, NOT proof of exhaustive query capture. */
export function traceObserved(row: EvalResultRow): boolean {
  return row.traceStatus === 'observed' || row.traceStatus === 'complete'; // Legacy sample status.
}

export function modelScore(row: EvalResultRow): number | null {
  return row.modelScore === 1 && !traceObserved(row) ? 0.5 : row.modelScore;
}

/** Preserve explicit failures/errors; incomplete evidence must never become a PASS. */
export function resultVerdict(row: EvalResultRow): Verdict {
  const verdict = row.verdict as Verdict;
  if (!VERDICTS.includes(verdict)) return 'INCONCLUSIVE';
  const citationsOnly = row.traceStatus === 'disabled' || row.routingEvidence === 'citations-only' || row.routingEvidence === 'tool_call';
  if (
    verdict === 'PASS'
    && ((!citationsOnly && modelScore(row) === 0.5) || ['pending', 'missing', 'incomplete', 'error'].includes(row.traceStatus ?? ''))
  ) {
    return 'INCONCLUSIVE';
  }
  return verdict;
}

/** Rescoring appends rows: deduplicate by rowId first, then keep latest score per ask and backend. */
export function latestResults(rows: readonly EvalResultRow[]): EvalResultRow[] {
  const seenIds = new Set<string>();
  const best = new Map<string, EvalResultRow>();
  for (const r of rows) {
    const rowId = nonEmptyId(r.rowId);
    if (rowId !== null) {
      if (seenIds.has(rowId)) continue;
      seenIds.add(rowId);
    }
    const key = resultKey(r);
    const cur = best.get(key);
    if (!cur || time(r.scoredUtc) >= time(cur.scoredUtc)) best.set(key, r);
  }
  return [...best.values()];
}

/** An answer is observed once, regardless of how many backends scored it. No combined verdict. */
export function answerObservations(rows: readonly EvalResultRow[]): EvalResultRow[] {
  const best = new Map<string, EvalResultRow>();
  for (const r of latestResults(rows)) {
    if (resultVerdict(r) === 'ERROR') continue;
    const key = askKey(r);
    const previous = best.get(key);
    if (!previous || time(r.scoredUtc) >= time(previous.scoredUtc)) best.set(key, r);
  }
  return [...best.values()];
}

/** Keep the latest row per run (deduplicating by rowId and collapsing rescore appends by runId). */
export function latestRuns(rows: readonly EvalRunRow[]): EvalRunRow[] {
  const seenIds = new Set<string>();
  const best = new Map<string, EvalRunRow>();
  for (const r of rows) {
    const rowId = nonEmptyId(r.rowId);
    if (rowId !== null) {
      if (seenIds.has(rowId)) continue;
      seenIds.add(rowId);
    }
    const key = r.runId ?? '';
    const cur = best.get(key);
    if (!cur || time(r.endedUtc ?? r.startedUtc) >= time(cur.endedUtc ?? cur.startedUtc)) best.set(key, r);
  }
  return [...best.values()].sort((a, b) => time(b.startedUtc) - time(a.startedUtc));
}

export interface ResultFilter {
  backend?: string; // 'all' or a backend name
  sinceDays?: number;
  now?: Date;
  runId?: string;
  surface?: string; // 'all' | 'live' | 'simulated' | specific surface name
  runSurfaces?: Map<string, string>;
}

export function isLiveSurface(surface: string | null | undefined): boolean {
  return Boolean(surface && surface !== 'simulated');
}

function matchesSurfaceFilter(actualSurface: string | null | undefined, filterSurface: string | undefined): boolean {
  if (!filterSurface || filterSurface === 'all') return true;
  if (filterSurface === 'live') return isLiveSurface(actualSurface);
  return (actualSurface ?? '') === filterSurface;
}

export function filterResults(rows: readonly EvalResultRow[], f: ResultFilter): EvalResultRow[] {
  const since = f.sinceDays ? time(f.now ?? new Date()) - f.sinceDays * 86400000 : null;
  return rows.filter((r) => {
    if (f.backend && f.backend !== 'all' && r.backend !== f.backend) return false;
    if (f.runId && r.runId !== f.runId) return false;
    if (since !== null && time(r.askStartUtc) < since) return false;
    if (f.surface && f.surface !== 'all' && f.runSurfaces && !matchesSurfaceFilter(f.runSurfaces.get(r.runId ?? ''), f.surface)) {
      return false;
    }
    return true;
  });
}

function accuracy(scores: readonly (number | null)[]): number | null {
  const decided = scores.filter((s): s is number => s === 0 || s === 1);
  return decided.length ? decided.reduce((a, b) => a + b, 0) / decided.length : null;
}

function mean(values: readonly (number | null)[]): number | null {
  const v = values.filter((x): x is number => typeof x === 'number');
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

export interface Kpis {
  asks: number;
  scores: number;
  pass: number;
  fail: number;
  inconclusive: number;
  error: number;
  passRate: number | null;
  valueAccuracy: number | null;
  artifactAccuracy: number | null;
  modelAccuracy: number | null;
  decoyRate: number | null;
  judgeAnswer: number | null;
  whyScore: number | null;
  latencyP50: number | null;
  latencyP95: number | null;
  daxPerAsk: number | null;
  daxMsP50: number | null;
  traceCoverage: number | null;
}

export function kpis(rows: readonly EvalResultRow[], complete = true): Kpis {
  const scores = latestResults(rows);
  const n = scores.length;
  const count = (v: Verdict) => scores.filter((r) => resultVerdict(r) === v).length;
  const ok = scores.filter((r) => resultVerdict(r) !== 'ERROR');
  const answers = answerObservations(scores);
  const traced = answers.filter((r) => r.traceStatus && r.traceStatus !== 'disabled');
  const captured = traced.filter(traceObserved);
  return {
    asks: new Set(scores.map(askKey)).size,
    scores: n,
    pass: count('PASS'),
    fail: count('FAIL'),
    inconclusive: count('INCONCLUSIVE'),
    error: count('ERROR'),
    passRate: complete && n ? count('PASS') / n : null,
    valueAccuracy: complete ? accuracy(ok.map((r) => r.valueScore)) : null,
    artifactAccuracy: complete ? accuracy(ok.map((r) => r.artifactScore)) : null,
    modelAccuracy: complete ? accuracy(ok.map(modelScore)) : null,
    decoyRate: complete && ok.length ? ok.filter((r) => (r.decoyHit ?? 0) > 0).length / ok.length : null,
    judgeAnswer: complete ? mean(ok.map((r) => r.judgeAnswerScore)) : null,
    whyScore: complete ? mean(ok.map((r) => r.whyScore)) : null,
    latencyP50: percentile(answers.map((r) => r.latencyMs), 50),
    latencyP95: percentile(answers.map((r) => r.latencyMs), 95),
    daxPerAsk: captured.length ? mean(captured.map((r) => r.daxQueryCount)) : null,
    daxMsP50: percentile(captured.filter((r) => (r.daxQueryCount ?? 0) > 0).map((r) => r.daxTotalMs), 50),
    traceCoverage: traced.length ? captured.filter((r) => (r.daxQueryCount ?? 0) > 0).length / traced.length : null,
  };
}

export function runBackends(run: EvalRunRow, backend = 'all'): string[] {
  const opt = run.evalOption ?? '';
  const declared = opt === 'both' ? [...BACKENDS] : BACKENDS.filter((b) => opt.includes(b));
  return backend === 'all' ? declared : declared.filter((b) => b === backend);
}

function inferRunPassPowK(rows: readonly EvalResultRow[], k: number): number | null {
  if (!rows.length || k <= 0) return null;
  const byCase = new Map<string, EvalResultRow[]>();
  for (const r of rows) {
    const key = r.questionId ?? r.askId ?? '';
    const list = byCase.get(key) ?? [];
    list.push(r);
    byCase.set(key, list);
  }
  if (!byCase.size) return null;
  let sum = 0;
  for (const caseRows of byCase.values()) {
    const passed = caseRows.filter((r) => resultVerdict(r) === 'PASS').length;
    sum += passPowK(caseRows.length, passed, k);
  }
  return sum / byCase.size;
}

function inferRoutingEvidence(rows: readonly EvalResultRow[], run?: EvalRunRow): string | null {
  const ok = rows.filter((r) => resultVerdict(r) !== 'ERROR');
  const pool = ok.length ? ok : rows;
  const explicit = pool.map((r) => nonEmptyId(r.routingEvidence)).filter((v): v is string => v !== null);
  if (explicit.length > 0) {
    const counts = new Map<string, number>();
    for (const tier of explicit) counts.set(tier, (counts.get(tier) ?? 0) + 1);
    const rank: Record<string, number> = { unverified: 0, 'citations-only': 1, 'engine+citations': 2, tool_call: 3 };
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || (rank[a[0]] ?? 99) - (rank[b[0]] ?? 99))[0][0];
  }
  if (pool.some(traceObserved)) return 'engine+citations';
  if (run?.traceEnabled === 0 || (pool.length > 0 && pool.every((r) => r.traceStatus === 'disabled'))) {
    return 'citations-only';
  }
  if (pool.some((r) => (r.powerBiCited ?? 0) > 0 || Boolean(r.citedArtifacts))) return 'citations-only';
  if (pool.length > 0) return 'unverified';
  return null;
}

export interface RunCoverage {
  runId: string;
  expectedAsks: number | null;
  availableScores: number;
  expectedScores: number | null;
  complete: boolean;
}

/** Missing rows are availability state, never invented failed or inconclusive scores. */
export function runCoverage(run: EvalRunRow, results: readonly EvalResultRow[], questions: readonly EvalQuestionRow[], backend = 'all'): RunCoverage {
  const backends = runBackends(run, backend);
  const expectedAsks = run.askCount;
  const own = latestResults(results).filter((r) => r.runId === run.runId && backends.includes(r.backend ?? ''));
  const cleanQuestions = dedupeQuestions(questions);
  const questionIds = new Set(cleanQuestions.filter((q) => q.runId === run.runId && q.questionId).map((q) => q.questionId));
  const questionCount = questionIds.size;
  const expectedScores = expectedAsks === null ? null : expectedAsks * backends.length;
  const complete = expectedAsks !== null && expectedAsks > 0 && backends.length > 0
    && run.questionCount !== null && questionCount === run.questionCount
    && backends.every((b) => {
      const scored = own.filter((r) => r.backend === b && r.askId);
      return new Set(scored.map(askKey)).size === expectedAsks
        && [...questionIds].every((id) => new Set(scored.filter((r) => r.questionId === id).map(askKey)).size === (run.repeats ?? 1));
    });
  return { runId: run.runId ?? '', expectedAsks, availableScores: own.length, expectedScores, complete };
}

export interface RunPoint {
  runId: string;
  runName: string;
  backend: string;
  startedUtc: Date | null;
  surface: string;
  target: string | null;
  routingEvidence: string | null;
  asks: number;
  passRate: number | null;
  passPowK: number | null;
  wilsonLow: number | null;
  wilsonHigh: number | null;
  valueAccuracy: number | null;
  artifactAccuracy: number | null;
  modelAccuracy: number | null;
  latencyP50: number | null;
  latencyP95: number | null;
  verdicts: Record<Verdict, number>;
  foundryReportUrl: string;
  complete: boolean;
  expectedAsks: number | null;
}

/** One point per run and backend, oldest first. */
export function runSeries(results: readonly EvalResultRow[], runs: readonly EvalRunRow[], questions: readonly EvalQuestionRow[], backend = 'all', truncated = false): RunPoint[] {
  const cleanRuns = latestRuns(runs);
  const cleanQuestions = dedupeQuestions(questions);
  const dedupedResults = latestResults(results);
  const runById = new Map(cleanRuns.map((r) => [r.runId ?? '', r]));
  const groups = new Map<string, EvalResultRow[]>();
  for (const r of dedupedResults) {
    const key = `${r.runId}|${r.backend}`;
    const list = groups.get(key) ?? [];
    list.push(r);
    groups.set(key, list);
  }
  for (const run of cleanRuns) {
    for (const b of runBackends(run, backend)) {
      const key = `${run.runId}|${b}`;
      if (!groups.has(key)) groups.set(key, []);
    }
  }
  const points: RunPoint[] = [];
  for (const [key, rows] of groups) {
    const [runId, rowBackend] = key.split('|');
    const run = runById.get(runId);
    const coverage = run ? runCoverage(run, dedupedResults, cleanQuestions, rowBackend) : null;
    const complete = !truncated && Boolean(coverage?.complete);
    const k = kpis(rows, complete);
    const kAttempts = Math.max(1, run?.k ?? run?.repeats ?? 1);
    const [wLow, wHigh] = complete && k.scores > 0
      ? wilsonInterval(k.pass, k.scores)
      : [run?.wilsonLow ?? null, run?.wilsonHigh ?? null];
    const computedPassPowK = complete && rows.length > 0
      ? inferRunPassPowK(rows, kAttempts)
      : (run?.passPowK ?? null);
    const verdicts = { PASS: k.pass, FAIL: k.fail, INCONCLUSIVE: k.inconclusive, ERROR: k.error };
    const firstAsk = rows.reduce<Date | null>((m, r) => (r.askStartUtc && (!m || r.askStartUtc < m) ? r.askStartUtc : m), null);
    points.push({
      runId, backend: rowBackend, verdicts, asks: k.asks, complete, expectedAsks: coverage?.expectedAsks ?? null,
      passRate: k.passRate, passPowK: computedPassPowK, wilsonLow: wLow, wilsonHigh: wHigh,
      valueAccuracy: k.valueAccuracy, artifactAccuracy: k.artifactAccuracy, modelAccuracy: k.modelAccuracy,
      latencyP50: k.latencyP50, latencyP95: k.latencyP95, runName: run?.runName ?? runId,
      startedUtc: run?.startedUtc ?? firstAsk, surface: run?.surface ?? '',
      target: nonEmptyId(run?.target) ?? nonEmptyId(run?.surface) ?? null,
      routingEvidence: inferRoutingEvidence(rows, run),
      foundryReportUrl: run?.foundryReportUrl ?? '',
    });
  }
  return points.sort((a, b) => time(a.startedUtc) - time(b.startedUtc) || a.backend.localeCompare(b.backend));
}

export interface RunSummary {
  runId: string;
  runName: string;
  backend: string;
  surface: string;
  target: string | null;
  routingEvidence: string | null;
  startedUtc: Date | null;
  endedUtc: Date | null;
  asks: number;
  scores: number;
  k: number;
  passRate: number | null;
  passPowK: number | null;
  wilsonLow: number | null;
  wilsonHigh: number | null;
  valueAccuracy: number | null;
  artifactAccuracy: number | null;
  modelAccuracy: number | null;
  latencyP50: number | null;
  latencyP95: number | null;
  verdicts: Record<Verdict, number>;
}

/** Collapse paired multi-backend rows (e.g. fabric-native + foundry) to one primary trial per ask. */
function primaryTrialRows(rows: readonly EvalResultRow[], backend: string): EvalResultRow[] {
  if (backend !== 'all' || rows.length <= 1) return [...rows];
  const byAsk = new Map<string, EvalResultRow>();
  for (const r of rows) {
    const key = askKey(r);
    const cur = byAsk.get(key);
    if (!cur || (cur.backend !== 'fabric-native' && r.backend === 'fabric-native')) {
      byAsk.set(key, r);
    }
  }
  return [...byAsk.values()];
}

/** Defensive per-run summary preferring computed metrics over stored EvalRun columns. */
export function runSummaries(
  runs: readonly EvalRunRow[],
  results: readonly EvalResultRow[] = [],
  backend = 'all',
): RunSummary[] {
  const cleanRuns = latestRuns(runs);
  const dedupedResults = latestResults(results).filter((r) => backend === 'all' || r.backend === backend);
  const runById = new Map(cleanRuns.map((r) => [r.runId ?? '', r]));
  const byRun = new Map<string, EvalResultRow[]>();
  for (const r of dedupedResults) {
    const id = r.runId ?? '';
    const list = byRun.get(id) ?? [];
    list.push(r);
    byRun.set(id, list);
  }
  for (const r of cleanRuns) {
    if (backend !== 'all' && runBackends(r, backend).length === 0) continue;
    const id = r.runId ?? '';
    if (!byRun.has(id)) byRun.set(id, []);
  }
  const out: RunSummary[] = [];
  for (const [runId, rows] of byRun) {
    const run = runById.get(runId);
    const trialRows = primaryTrialRows(rows, backend);
    const maxAttempt = trialRows.reduce((m, r) => Math.max(m, r.attempt ?? 1), 1);
    const kAttempts = Math.max(1, run?.k ?? run?.repeats ?? maxAttempt);
    const k = kpis(trialRows, trialRows.length > 0);
    const hasRows = k.scores > 0;
    const [wLow, wHigh] = hasRows
      ? wilsonInterval(k.pass, k.scores)
      : [run?.wilsonLow ?? null, run?.wilsonHigh ?? null];
    const computedPassPowK = hasRows ? inferRunPassPowK(trialRows, kAttempts) : (run?.passPowK ?? null);
    out.push({
      runId,
      runName: run?.runName ?? runId,
      backend: backend === 'all' ? (run?.evalOption ?? (rows[0]?.backend ?? 'all')) : backend,
      surface: run?.surface ?? '',
      target: nonEmptyId(run?.target) ?? nonEmptyId(run?.surface) ?? null,
      routingEvidence: inferRoutingEvidence(rows, run),
      startedUtc: run?.startedUtc ?? null,
      endedUtc: run?.endedUtc ?? null,
      asks: hasRows ? k.asks : (run?.askCount ?? 0),
      scores: k.scores,
      k: kAttempts,
      passRate: hasRows ? k.passRate : (run?.passRate ?? null),
      passPowK: computedPassPowK,
      wilsonLow: wLow,
      wilsonHigh: wHigh,
      valueAccuracy: hasRows ? k.valueAccuracy : (run?.valueAccuracy ?? null),
      artifactAccuracy: hasRows ? k.artifactAccuracy : (run?.artifactAccuracy ?? null),
      modelAccuracy: hasRows ? k.modelAccuracy : (run?.modelAccuracy ?? null),
      latencyP50: hasRows ? k.latencyP50 : (run?.latencyP50Ms ?? null),
      latencyP95: hasRows ? k.latencyP95 : (run?.latencyP95Ms ?? null),
      verdicts: { PASS: k.pass, FAIL: k.fail, INCONCLUSIVE: k.inconclusive, ERROR: k.error },
    });
  }
  return out.sort((a, b) => time(b.startedUtc) - time(a.startedUtc) || a.runId.localeCompare(b.runId));
}

export interface QuestionStat {
  questionId: string;
  question: string;
  category: string;
  criticality: string;
  asks: number;
  scores: number;
  missingScores: number;
  runs: number;
  passRate: number | null;
  latestVerdict: string;
  latest: EvalResultRow | null;
  distinctModelSets: number;
  distinctCitedSets: number;
  valueMin: number | null;
  valueMax: number | null;
  expectedValue: number | null;
  latencyP50: number | null;
}

export function questionStats(rows: readonly EvalResultRow[], questions: readonly EvalQuestionRow[] = [], runs: readonly EvalRunRow[] = [], backend = 'all'): QuestionStat[] {
  const groups = new Map<string, EvalResultRow[]>();
  for (const r of latestResults(rows)) {
    const list = groups.get(r.questionId ?? '') ?? [];
    list.push(r);
    groups.set(r.questionId ?? '', list);
  }
  const snapshots = new Map(questions.map((q) => [JSON.stringify([q.runId, q.questionId]), q]));
  for (const q of snapshots.values()) if (!groups.has(q.questionId ?? '')) groups.set(q.questionId ?? '', []);
  const runById = new Map(runs.map((r) => [r.runId, r]));
  const stats: QuestionStat[] = [];
  for (const [questionId, list] of groups) {
    const sorted = [...list].sort((a, b) => time(a.askStartUtc) - time(b.askStartUtc));
    const latest = sorted.at(-1) ?? null;
    const ownQuestions = [...snapshots.values()].filter((q) => q.questionId === questionId);
    const reference = latest ?? ownQuestions.at(-1);
    const answers = answerObservations(list);
    const values = answers.map((r) => r.extractedValue).filter((v): v is number => typeof v === 'number');
    const missingScores = ownQuestions.reduce((total, q) => {
      const run = runById.get(q.runId);
      if (!run) return total + 1;
      const backends = runBackends(run, backend);
      if (!backends.length) return total + 1;
      return total + backends.reduce((n, b) => {
        const available = new Set(list.filter((r) => r.runId === q.runId && r.backend === b).map(askKey)).size;
        return n + Math.max((run.repeats ?? 1) - available, 0);
      }, 0);
    }, 0);
    stats.push({
      questionId, latest, question: reference?.question ?? '', category: reference?.category ?? '',
      criticality: reference?.criticality ?? '', asks: new Set(list.map(askKey)).size, scores: list.length, missingScores,
      runs: new Set([...list.map((r) => r.runId), ...ownQuestions.map((q) => q.runId)]).size,
      passRate: kpis(list, missingScores === 0).passRate,
      latestVerdict: latest ? resultVerdict(latest) : 'PENDING',
      distinctModelSets: new Set(answers.filter(traceObserved).map((r) => r.queriedModels ?? '')).size,
      distinctCitedSets: new Set(answers.map((r) => r.citedArtifacts ?? '')).size,
      valueMin: values.length ? Math.min(...values) : null, valueMax: values.length ? Math.max(...values) : null,
      expectedValue: reference?.expectedValue ?? null, latencyP50: percentile(answers.map((r) => r.latencyMs), 50),
    });
  }
  return stats.sort((a, b) => a.questionId.localeCompare(b.questionId));
}

/** Shared selection for the shell and offline tests, including runs with no available score. */
export function selectView(data: EvalData, filters: ResultFilter) {
  const allRuns = latestRuns(data.runs);
  const sampleTime = Math.max(0, ...data.results.map((r) => time(r.askStartUtc)), ...allRuns.map((r) => time(r.startedUtc)));
  const now = filters.now ?? (data.source === 'sample' && sampleTime ? new Date(sampleTime) : new Date());
  const runSurfaces = new Map(allRuns.map((r) => [r.runId ?? '', r.surface ?? '']));
  const results = filterResults(latestResults(data.results), { ...filters, now, runSurfaces });
  const resultRunIds = new Set(results.map((r) => r.runId));
  const since = filters.sinceDays ? now.getTime() - filters.sinceDays * 86400000 : 0;
  const runs = allRuns.filter((r) =>
    (time(r.startedUtc) >= since || resultRunIds.has(r.runId))
    && matchesSurfaceFilter(r.surface, filters.surface)
    && (!filters.backend || filters.backend === 'all' || runBackends(r, filters.backend).length > 0));
  const runIds = new Set([...runs.map((r) => r.runId), ...resultRunIds]);
  const questions = dedupeQuestions(data.questions.filter((q) => runIds.has(q.runId)));
  const coverage = runs.map((r) => runCoverage(r, results, questions, filters.backend));
  const knownRuns = new Set(runs.map((r) => r.runId));
  const incomplete = data.truncated || coverage.some((r) => !r.complete) || results.some((r) => !knownRuns.has(r.runId));
  const asks = new Set(results.map(askKey));
  return {
    results, runs, questions, coverage, incomplete,
    points: runSeries(results, runs, questions, filters.backend, data.truncated),
    summaries: runSummaries(runs, results, filters.backend),
    queries: dedupeQueries(data.queries.filter((q) => asks.has(askKey(q)))),
    events: dedupeEvents(data.events.filter((e) => runIds.has(e.runId))),
  };
}

const REASONS: readonly [RegExp, string][] = [
  [/^Copilot Chat API error/i, 'Copilot Chat API error'],
  [/^value: .*differs from expected/i, 'Wrong value'],
  [/^value: no .*value found/i, 'No value in the answer'],
  [/^value: .*too coarsely/i, 'Value rounded too coarsely to verify'],
  [/^artifact: decoy cited/i, 'Cited a decoy'],
  [/^artifact: .*non-Power BI item with a matching name/i, 'Cited a document instead of the report'],
  [/^artifact: no Power BI/i, 'No Power BI citation'],
  [/^artifact: cited other Power BI/i, 'Cited the wrong report'],
  [/^model: decoy semantic model/i, 'Queried a decoy semantic model'],
  [/^model: queried other semantic models/i, 'Queried the wrong semantic model'],
  [/^model: no semantic model query/i, 'No DAX observed'],
  [/^model: DAX trace not available/i, 'DAX trace pending'],
  [/^judge_answer:/i, 'Judge: answer not correct'],
  [/^why:/i, "Judge: explanation doesn't match the evidence"],
];

export function reasonLabel(part: string): string {
  const text = part.trim();
  for (const [pattern, label] of REASONS) if (pattern.test(text)) return label;
  const check = text.split(':')[0];
  return check ? `${check}: other` : 'Other';
}

/** Most common failure reasons across asks that didn't pass. */
export function failureReasons(rows: readonly EvalResultRow[], top = 8): { label: string; count: number }[] {
  const counts = new Map<string, number>();
  const seen = new Set<string>();
  for (const r of latestResults(rows)) {
    if (resultVerdict(r) === 'PASS' || !r.reasons) continue;
    const labels = new Set(r.reasons.split(' | ').filter(Boolean).map(reasonLabel));
    for (const label of labels) {
      const key = JSON.stringify([askKey(r), label]);
      if (!seen.has(key)) counts.set(label, (counts.get(label) ?? 0) + 1);
      seen.add(key);
    }
  }
  return [...counts.entries()].map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)).slice(0, top);
}

/** Expected semantic model vs the models Fabric IQ actually queried. */
export function routingMatrix(rows: readonly EvalResultRow[]): { expected: string; queried: string; count: number; observed: boolean; traceStatus: string }[] {
  const counts = new Map<string, number>();
  for (const r of answerObservations(rows)) {
    if (r.traceStatus === 'disabled') continue;
    const queried = traceObserved(r) ? r.queriedModels || '(none observed)' : `(trace ${r.traceStatus || 'missing'})`;
    const key = `${r.expectedModel ?? ''}\u0000${queried}\u0000${r.traceStatus || 'missing'}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()].map(([key, count]) => {
    const [expected, queried, traceStatus] = key.split('\u0000');
    return { expected, queried, count, traceStatus, observed: traceStatus === 'observed' || traceStatus === 'complete' };
  }).sort((a, b) => a.expected.localeCompare(b.expected) || b.count - a.count);
}

export function latencyHistogram(rows: readonly EvalResultRow[], bucketMs = 2500): { from: number; to: number; count: number }[] {
  const values = answerObservations(rows).map((r) => r.latencyMs).filter((v): v is number => typeof v === 'number');
  if (!values.length) return [];
  const max = Math.max(...values);
  const buckets = Math.max(1, Math.ceil((max + 1) / bucketMs));
  const out = Array.from({ length: buckets }, (_, i) => ({ from: i * bucketMs, to: (i + 1) * bucketMs, count: 0 }));
  for (const v of values) out[Math.min(Math.floor(v / bucketMs), buckets - 1)].count += 1;
  return out;
}

/** Independent averages: DAX spans answer AND why and can overlap/exceed either round trip. */
export function latencyBreakdown(rows: readonly EvalResultRow[]): { questionId: string; answerMs: number; daxMs: number | null; whyMs: number | null }[] {
  const groups = new Map<string, EvalResultRow[]>();
  for (const r of answerObservations(rows)) {
    if (r.latencyMs === null) continue;
    const list = groups.get(r.questionId ?? '') ?? [];
    list.push(r);
    groups.set(r.questionId ?? '', list);
  }
  return [...groups.entries()].map(([questionId, list]) => {
    const captured = list.filter((r) => traceObserved(r) || (r.daxQueryCount ?? 0) > 0);
    return {
      questionId, answerMs: mean(list.map((r) => r.latencyMs)) ?? 0,
      daxMs: mean(captured.map((r) => r.daxTotalMs)),
      whyMs: mean(list.map((r) => r.whyLatencyMs)),
    };
  }).sort((a, b) => a.questionId.localeCompare(b.questionId));
}

/** Independent measured stage durations only; never computes additive residuals across overlapping stages. */
export function stageDurations(events: readonly EvalEventRow[]): { stage: string; count: number; p50: number | null; p95: number | null; totalMs: number; failures: number }[] {
  const groups = new Map<string, EvalEventRow[]>();
  for (const e of dedupeEvents(events)) {
    const list = groups.get(e.stage ?? '') ?? [];
    list.push(e);
    groups.set(e.stage ?? '', list);
  }
  return [...groups.entries()].map(([stage, list]) => ({
    stage, count: list.length, p50: percentile(list.map((e) => e.durationMs), 50),
    p95: percentile(list.map((e) => e.durationMs), 95), totalMs: list.reduce((a, e) => a + (e.durationMs ?? 0), 0),
    failures: list.filter((e) => e.status !== 'ok').length,
  })).sort((a, b) => b.totalMs - a.totalMs);
}

export function slowestQueries(queries: readonly FabricIqQueryRow[], n = 10): FabricIqQueryRow[] {
  return dedupeQueries(queries).sort((a, b) => (b.durationMs ?? 0) - (a.durationMs ?? 0)).slice(0, n);
}

/** For asks scored by both options: how often the verdicts agree. */
export function backendAgreement(rows: readonly EvalResultRow[]): { asks: number; agree: number; rate: number | null } {
  const byAsk = new Map<string, Set<string>>();
  const backends = new Map<string, Set<string>>();
  for (const r of latestResults(rows)) {
    const id = askKey(r);
    if (!byAsk.has(id)) {
      byAsk.set(id, new Set());
      backends.set(id, new Set());
    }
    byAsk.get(id)?.add(resultVerdict(r));
    backends.get(id)?.add(r.backend ?? '');
  }
  let asks = 0;
  let agree = 0;
  for (const [id, verdicts] of byAsk) {
    if ((backends.get(id)?.size ?? 0) < 2) continue;
    asks += 1;
    if (verdicts.size === 1) agree += 1;
  }
  return { asks, agree, rate: asks ? agree / asks : null };
}

export interface TimelineBar {
  label: string;
  kind: 'answer' | 'why' | 'dax';
  startMs: number;
  endMs: number;
  detail: string;
}

/** The ask and the DAX Fabric IQ ran for it, relative to the ask start (OffsetMs marks query end). */
export function askTimeline(result: EvalResultRow, queries: readonly FabricIqQueryRow[]): TimelineBar[] {
  const bars: TimelineBar[] = [];
  const answer = result.latencyMs ?? 0;
  bars.push({ label: 'Copilot answer', kind: 'answer', startMs: 0, endMs: answer, detail: '' });
  if (result.whyLatencyMs) {
    bars.push({ label: "Follow-up 'why'", kind: 'why', startMs: answer, endMs: answer + result.whyLatencyMs, detail: '' });
  }
  const own = dedupeQueries(queries.filter((q) => askKey(q) === askKey(result))).sort((a, b) => (a.offsetMs ?? 0) - (b.offsetMs ?? 0));
  for (const q of own) {
    const end = q.offsetMs ?? 0;
    bars.push({ label: q.itemName ?? 'DAX', kind: 'dax', startMs: Math.max(end - (q.durationMs ?? 0), 0), endMs: end, detail: q.dax ?? '' });
  }
  return bars;
}
