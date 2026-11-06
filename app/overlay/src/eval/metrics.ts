// Scorecard metrics over normalized telemetry rows. Pure: no runtime imports, unit-tested with
// node --test. Definitions match the Python harness (pipeline.run_metrics) and the KQL functions.
import type { EvalEventRow, EvalQuestionRow, EvalResultRow, EvalRunRow, FabricIqQueryRow } from './generated/contract';

export type Verdict = 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'ERROR';
export const VERDICTS: readonly Verdict[] = ['PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR'];
export const BACKENDS = ['fabric-native', 'foundry'] as const;

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

export function askKey(row: { runId: string | null; askId: string | null }): string {
  return JSON.stringify([row.runId, row.askId]);
}

export function resultKey(row: EvalResultRow): string {
  return JSON.stringify([row.runId, row.askId, row.backend]);
}

/** Only remove identical records; never merge conflicting live observations. */
export function distinctRows<T extends object>(rows: readonly T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = JSON.stringify(Object.entries(row).sort(([a], [b]) => a.localeCompare(b)));
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
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
  if (verdict === 'PASS' && (modelScore(row) === 0.5 || ['pending', 'missing', 'incomplete', 'error'].includes(row.traceStatus ?? ''))) {
    return 'INCONCLUSIVE';
  }
  return verdict;
}

/** Rescoring appends rows: keep the latest score per ask and backend. */
export function latestResults(rows: readonly EvalResultRow[]): EvalResultRow[] {
  const best = new Map<string, EvalResultRow>();
  for (const r of rows) {
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

/** Keep the latest row per run (a rescore writes another EvalRun row). */
export function latestRuns(rows: readonly EvalRunRow[]): EvalRunRow[] {
  const best = new Map<string, EvalRunRow>();
  for (const r of rows) {
    const cur = best.get(r.runId ?? '');
    if (!cur || time(r.endedUtc) >= time(cur.endedUtc)) best.set(r.runId ?? '', r);
  }
  return [...best.values()].sort((a, b) => time(b.startedUtc) - time(a.startedUtc));
}

export interface ResultFilter {
  backend?: string; // 'all' or a backend name
  sinceDays?: number;
  now?: Date;
  runId?: string;
  surface?: string; // 'all' | 'simulated' | 'copilot-chat-api'
  runSurfaces?: Map<string, string>;
}

export function filterResults(rows: readonly EvalResultRow[], f: ResultFilter): EvalResultRow[] {
  const since = f.sinceDays ? time(f.now ?? new Date()) - f.sinceDays * 86400000 : null;
  return rows.filter((r) => {
    if (f.backend && f.backend !== 'all' && r.backend !== f.backend) return false;
    if (f.runId && r.runId !== f.runId) return false;
    if (since !== null && time(r.askStartUtc) < since) return false;
    if (f.surface && f.surface !== 'all' && f.runSurfaces && f.runSurfaces.get(r.runId ?? '') !== f.surface) {
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
  const declared = BACKENDS.filter((b) => run.evalOption?.includes(b));
  return backend === 'all' ? declared : declared.filter((b) => b === backend);
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
  const questionIds = new Set(questions.filter((q) => q.runId === run.runId && q.questionId).map((q) => q.questionId));
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
  asks: number;
  passRate: number | null;
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
  const runById = new Map(runs.map((r) => [r.runId ?? '', r]));
  const groups = new Map<string, EvalResultRow[]>();
  for (const r of latestResults(results)) {
    const key = `${r.runId}|${r.backend}`;
    const list = groups.get(key) ?? [];
    list.push(r);
    groups.set(key, list);
  }
  for (const run of runs) {
    for (const b of runBackends(run, backend)) {
      const key = `${run.runId}|${b}`;
      if (!groups.has(key)) groups.set(key, []);
    }
  }
  const points: RunPoint[] = [];
  for (const [key, rows] of groups) {
    const [runId, backend] = key.split('|');
    const run = runById.get(runId);
    const coverage = run ? runCoverage(run, results, questions, backend) : null;
    const complete = !truncated && Boolean(coverage?.complete);
    const k = kpis(rows, complete);
    const verdicts = { PASS: k.pass, FAIL: k.fail, INCONCLUSIVE: k.inconclusive, ERROR: k.error };
    const firstAsk = rows.reduce<Date | null>((m, r) => (r.askStartUtc && (!m || r.askStartUtc < m) ? r.askStartUtc : m), null);
    points.push({
      runId, backend, verdicts, asks: k.asks, complete, expectedAsks: coverage?.expectedAsks ?? null,
      passRate: k.passRate, valueAccuracy: k.valueAccuracy,
      artifactAccuracy: k.artifactAccuracy, modelAccuracy: k.modelAccuracy, latencyP50: k.latencyP50,
      latencyP95: k.latencyP95, runName: run?.runName ?? runId, startedUtc: run?.startedUtc ?? firstAsk,
      surface: run?.surface ?? '', foundryReportUrl: run?.foundryReportUrl ?? '',
    });
  }
  return points.sort((a, b) => time(a.startedUtc) - time(b.startedUtc) || a.backend.localeCompare(b.backend));
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
    && (!filters.surface || filters.surface === 'all' || r.surface === filters.surface)
    && (!filters.backend || filters.backend === 'all' || runBackends(r, filters.backend).length > 0));
  const runIds = new Set([...runs.map((r) => r.runId), ...resultRunIds]);
  const questions = data.questions.filter((q) => runIds.has(q.runId));
  const coverage = runs.map((r) => runCoverage(r, results, questions, filters.backend));
  const knownRuns = new Set(runs.map((r) => r.runId));
  const incomplete = data.truncated || coverage.some((r) => !r.complete) || results.some((r) => !knownRuns.has(r.runId));
  const asks = new Set(results.map(askKey));
  return {
    results, runs, questions, coverage, incomplete,
    points: runSeries(results, runs, questions, filters.backend, data.truncated),
    queries: distinctRows(data.queries.filter((q) => asks.has(askKey(q)))),
    events: distinctRows(data.events.filter((e) => runIds.has(e.runId))),
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

export function stageDurations(events: readonly EvalEventRow[]): { stage: string; count: number; p50: number | null; p95: number | null; totalMs: number; failures: number }[] {
  const groups = new Map<string, EvalEventRow[]>();
  for (const e of distinctRows(events)) {
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
  return distinctRows(queries).sort((a, b) => (b.durationMs ?? 0) - (a.durationMs ?? 0)).slice(0, n);
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
  const own = distinctRows(queries.filter((q) => askKey(q) === askKey(result))).sort((a, b) => (a.offsetMs ?? 0) - (b.offsetMs ?? 0));
  for (const q of own) {
    const end = q.offsetMs ?? 0;
    bars.push({ label: q.itemName ?? 'DAX', kind: 'dax', startMs: Math.max(end - (q.durationMs ?? 0), 0), endMs: end, detail: q.dax ?? '' });
  }
  return bars;
}
