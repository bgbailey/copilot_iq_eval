import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  answerObservations,
  askTimeline,
  backendAgreement,
  failureReasons,
  kpis,
  latencyBreakdown,
  latencyHistogram,
  latestResults,
  latestRuns,
  mcnemarExactP,
  modelScore,
  passAtK,
  passPowK,
  percentile,
  questionStats,
  resultVerdict,
  routingMatrix,
  runCoverage,
  runSeries,
  runSummaries,
  selectView,
  slowestQueries,
  stageDurations,
  wilsonInterval,
} from '../../overlay/src/eval/metrics.ts';

function assertClose(actual, expected, tol = 1e-9, msg = '') {
  assert.equal(typeof actual, 'number', `Expected number${msg ? `: ${msg}` : ''}`);
  assert.ok(
    Math.abs(actual - expected) <= tol,
    `Expected ${actual} to be within ${tol} of ${expected}${msg ? ` (${msg})` : ''}`,
  );
}

function makeRun(overrides = {}) {
  return {
    runId: 'run-1',
    runName: 'Contoso run 1',
    evalOption: 'fabric-native',
    surface: 'simulated',
    startedUtc: new Date('2026-11-01T10:00:00Z'),
    endedUtc: new Date('2026-11-01T10:05:00Z'),
    status: 'completed',
    host: 'local',
    harnessVersion: '0.2.0',
    goldenSetName: 'contoso.yaml',
    goldenSetHash: 'abc123',
    questionCount: 2,
    askCount: 2,
    repeats: 1,
    explainMode: 'followup',
    traceEnabled: 1,
    testUser: 'eval.tester@contoso.com',
    judgeModel: 'simulated-judge',
    foundryEvalId: null,
    foundryRunId: null,
    foundryReportUrl: null,
    passRate: null,
    valueAccuracy: null,
    artifactAccuracy: null,
    modelAccuracy: null,
    latencyP50Ms: null,
    latencyP95Ms: null,
    notes: null,
    rowId: null,
    target: 'copilot-chat',
    k: 1,
    passPowK: null,
    wilsonLow: null,
    wilsonHigh: null,
    judgePromptHash: null,
    judgeCalibrationId: null,
    gatePolicyHash: null,
    schemaVersion: 2,
    ...overrides,
  };
}

function makeQuestion(overrides = {}) {
  return {
    runId: 'run-1',
    questionId: 'Q01',
    question: 'What was gross revenue in FY2025?',
    category: 'routing',
    expectedArtifact: 'Sales Analytics',
    artifactAliases: null,
    expectedModel: 'Sales Analytics',
    decoys: 'Sales Sandbox',
    expectedValue: 12840000,
    unit: 'currency',
    relTol: 0.005,
    absTol: null,
    expectedAnswer: '$12.84M',
    referenceDax: 'EVALUATE ROW("v", [Gross Revenue])',
    criticality: 'critical',
    rowId: null,
    expectedArtifactId: null,
    caseType: 'numeric',
    persona: 'analyst',
    tags: null,
    intent: null,
    gates: null,
    paraphrase: null,
    ...overrides,
  };
}

function makeResult(overrides = {}) {
  return {
    runId: 'run-1',
    askId: 'run-1-Q01-1',
    questionId: 'Q01',
    attempt: 1,
    question: 'What was gross revenue in FY2025?',
    category: 'routing',
    criticality: 'critical',
    testUser: 'eval.tester@contoso.com',
    askStartUtc: new Date('2026-11-01T10:00:10Z'),
    backend: 'fabric-native',
    verdict: 'PASS',
    valueScore: 1,
    artifactScore: 1,
    modelScore: 1,
    judgeAnswerScore: 1,
    whyScore: 1,
    decoyHit: 0,
    powerBiCited: 1,
    expectedArtifact: 'Sales Analytics',
    citedArtifacts: 'Sales Analytics',
    expectedModel: 'Sales Analytics',
    queriedModels: 'Sales Analytics',
    expectedValue: 12840000,
    extractedValue: 12840000,
    valueErrorPct: 0,
    latencyMs: 4200,
    whyLatencyMs: 2100,
    daxQueryCount: 2,
    daxTotalMs: 650,
    daxMaxMs: 400,
    firstDaxOffsetMs: 1200,
    traceStatus: 'observed',
    answerPreview: 'Gross revenue in FY2025 was $12.84M.',
    whyPreview: 'Read from Sales Analytics.',
    reasons: '',
    judgeNotes: '',
    error: null,
    scoredUtc: new Date('2026-11-01T10:01:00Z'),
    rowId: null,
    caseType: 'numeric',
    persona: 'analyst',
    matchKind: 'exact',
    extractionMethod: 'first',
    routingEvidence: 'engine+citations',
    correlationConfidence: 'high',
    ...overrides,
  };
}

test('empty datasets return safe null/empty outputs without NaN', () => {
  assert.equal(percentile([], 50), null);
  const emptyKpis = kpis([]);
  assert.equal(emptyKpis.asks, 0);
  assert.equal(emptyKpis.scores, 0);
  assert.equal(emptyKpis.passRate, null);
  assert.equal(emptyKpis.latencyP50, null);
  assert.deepEqual(runSeries([], [], []), []);
  assert.deepEqual(runSummaries([]), []);
  assert.deepEqual(questionStats([]), []);
  assert.deepEqual(failureReasons([]), []);
  assert.deepEqual(routingMatrix([]), []);
  assert.deepEqual(latencyHistogram([]), []);
  assert.deepEqual(latencyBreakdown([]), []);
  assert.deepEqual(stageDurations([]), []);
  assert.deepEqual(slowestQueries([]), []);
  assert.deepEqual(backendAgreement([]), { asks: 0, agree: 0, rate: null });
});

test('wilsonInterval matches published/Python reference values to 1e-9', () => {
  assert.deepEqual(wilsonInterval(0, 0), [0, 0]);
  assert.deepEqual(wilsonInterval(1, -5), [0, 0]);

  const [low8of8, high8of8] = wilsonInterval(8, 8);
  assertClose(low8of8, 0.6755924351161198, 1e-9, '8/8 low');
  assertClose(high8of8, 1.0, 1e-9, '8/8 high');

  const [low0of8, high0of8] = wilsonInterval(0, 8);
  assertClose(low0of8, 0.0, 1e-9, '0/8 low');
  assertClose(high0of8, 0.3244075648838802, 1e-9, '0/8 high');

  const [low5of8, high5of8] = wilsonInterval(5, 8);
  assertClose(low5of8, 0.3057423946026274, 1e-9, '5/8 low');
  assertClose(high5of8, 0.8631557141764026, 1e-9, '5/8 high');

  const [low40of40, high40of40] = wilsonInterval(40, 40);
  assertClose(low40of40, 0.9123783988027135, 1e-9, '40/40 low');
  assertClose(high40of40, 1.0, 1e-9, '40/40 high');
});

test('passAtK and passPowK handle zero, single-attempt, and multi-attempt cases', () => {
  assert.equal(passAtK(0, 0, 1), 0);
  assert.equal(passAtK(3, 1, 0), 0);
  assert.equal(passAtK(3, 0, 2), 0);
  assert.equal(passAtK(1, 1, 1), 1);
  assert.equal(passAtK(1, 0, 1), 0);

  assertClose(passAtK(3, 1, 1), 1 / 3, 1e-12);
  assertClose(passAtK(3, 1, 2), 2 / 3, 1e-12);
  assert.equal(passAtK(3, 1, 3), 1);
  assert.equal(passAtK(3, 1, 5), 1); // k > n clamps k_eff to n
  assertClose(passAtK(4, 2, 2), 5 / 6, 1e-12);
  assertClose(passAtK(5, 2, 3), 0.9, 1e-12); // 1 - comb(3,3)/comb(5,3) = 1 - 1/10

  assert.equal(passPowK(0, 0, 3), 0);
  assert.equal(passPowK(3, 2, 0), 0);
  assert.equal(passPowK(3, 0, 3), 0);
  assert.equal(passPowK(1, 1, 1), 1);
  assert.equal(passPowK(3, 3, 3), 1);
  assertClose(passPowK(3, 2, 3), 8 / 27, 1e-12);
  assertClose(passPowK(4, 2, 2), 0.25, 1e-12);
});

test('mcnemarExactP computes exact two-sided binomial p-values', () => {
  assert.equal(mcnemarExactP(0, 0), 1);
  assert.equal(mcnemarExactP(4, 4), 1);
  assert.equal(mcnemarExactP(0, 1), 1);
  assert.equal(mcnemarExactP(1, 0), 1);
  assertClose(mcnemarExactP(0, 5), 0.0625, 1e-12);
  assertClose(mcnemarExactP(5, 0), 0.0625, 1e-12);
  assertClose(mcnemarExactP(0, 6), 0.03125, 1e-12);
  assertClose(mcnemarExactP(1, 7), 18 / 256, 1e-12);
  assertClose(mcnemarExactP(7, 1), 18 / 256, 1e-12);
  assertClose(mcnemarExactP(1, 9), 22 / 1024, 1e-12);
  assertClose(mcnemarExactP(2, 8), 112 / 1024, 1e-12);
  assert.throws(() => mcnemarExactP(-1, 3), RangeError);
});

test('defensive deduplication collapses duplicate rowId and natural keys without double-counting KPIs', () => {
  const r1 = makeResult({ askId: 'a1', questionId: 'Q01', verdict: 'PASS', rowId: 'res-row-1' });
  const r1DupRowId = makeResult({ askId: 'a1', questionId: 'Q01', verdict: 'PASS', rowId: 'res-row-1' });
  const r2 = makeResult({ askId: 'a2', questionId: 'Q02', verdict: 'FAIL', valueScore: 0, rowId: null });
  const r2DupNatural = makeResult({
    askId: 'a2',
    questionId: 'Q02',
    verdict: 'FAIL',
    valueScore: 0,
    rowId: null,
    judgeNotes: 'duplicate replay note',
  });

  const deduped = latestResults([r1, r1DupRowId, r2, r2DupNatural]);
  assert.equal(deduped.length, 2);

  const summaryKpis = kpis([r1, r1DupRowId, r2, r2DupNatural]);
  assert.equal(summaryKpis.asks, 2);
  assert.equal(summaryKpis.scores, 2);
  assert.equal(summaryKpis.pass, 1);
  assert.equal(summaryKpis.fail, 1);
  assertClose(summaryKpis.passRate, 0.5, 1e-12);

  // Rescoring with a newer scoredUtc overrides earlier verdict on the same natural key.
  const r2Rescored = makeResult({
    askId: 'a2',
    questionId: 'Q02',
    verdict: 'PASS',
    valueScore: 1,
    scoredUtc: new Date('2026-11-01T10:10:00Z'),
    rowId: 'res-row-2-v2',
  });
  const afterRescore = kpis([r1, r2, r2Rescored]);
  assert.equal(afterRescore.scores, 2);
  assert.equal(afterRescore.pass, 2);
  assertClose(afterRescore.passRate, 1.0, 1e-12);
});

test('runSummaries exposes wilsonLow, wilsonHigh, passPowK, target, and routingEvidence with dedupe', () => {
  const run = makeRun({
    runId: 'run-multi',
    questionCount: 2,
    askCount: 6,
    repeats: 3,
    k: 3,
    target: 'mcp-agent',
    rowId: 'run-row-1',
  });
  const runDup = makeRun({
    runId: 'run-multi',
    questionCount: 2,
    askCount: 6,
    repeats: 3,
    k: 3,
    target: 'mcp-agent',
    rowId: 'run-row-1',
  });

  // Q01 passes 3/3 (passPowK = 1), Q02 passes 2/3 (passPowK = 8/27). Total pass = 5/6.
  const results = [
    makeResult({ runId: 'run-multi', askId: 'a-q1-1', questionId: 'Q01', attempt: 1, verdict: 'PASS', routingEvidence: 'tool_call' }),
    makeResult({ runId: 'run-multi', askId: 'a-q1-2', questionId: 'Q01', attempt: 2, verdict: 'PASS', routingEvidence: 'tool_call' }),
    makeResult({ runId: 'run-multi', askId: 'a-q1-3', questionId: 'Q01', attempt: 3, verdict: 'PASS', routingEvidence: 'tool_call' }),
    makeResult({ runId: 'run-multi', askId: 'a-q2-1', questionId: 'Q02', attempt: 1, verdict: 'PASS', routingEvidence: 'tool_call' }),
    makeResult({ runId: 'run-multi', askId: 'a-q2-2', questionId: 'Q02', attempt: 2, verdict: 'PASS', routingEvidence: 'tool_call' }),
    makeResult({ runId: 'run-multi', askId: 'a-q2-3', questionId: 'Q02', attempt: 3, verdict: 'FAIL', valueScore: 0, routingEvidence: 'tool_call' }),
  ];
  // Feed every row twice to simulate raw un-deduped Eventhouse stream.
  const summaries = runSummaries([run, runDup], [...results, ...results]);
  assert.equal(summaries.length, 1);
  const s = summaries[0];
  assert.equal(s.runId, 'run-multi');
  assert.equal(s.asks, 6);
  assert.equal(s.scores, 6);
  assert.equal(s.target, 'mcp-agent');
  assert.equal(s.routingEvidence, 'tool_call');
  assertClose(s.passRate, 5 / 6, 1e-12);
  assertClose(s.passPowK, (1 + 8 / 27) / 2, 1e-12);
  const [expectedLow, expectedHigh] = wilsonInterval(5, 6);
  assertClose(s.wilsonLow, expectedLow, 1e-12);
  assertClose(s.wilsonHigh, expectedHigh, 1e-12);

  // When result rows are absent, runSummaries falls back to stored EvalRun columns.
  const storedOnlyRun = makeRun({
    runId: 'run-stored',
    target: null,
    surface: 'transcript-import',
    traceEnabled: 0,
    askCount: 8,
    passRate: 0.75,
    passPowK: 0.625,
    wilsonLow: 0.409275,
    wilsonHigh: 0.928521,
  });
  const [stored] = runSummaries([storedOnlyRun], []);
  assert.equal(stored.target, 'transcript-import');
  assert.equal(stored.routingEvidence, 'citations-only');
  assertClose(stored.passRate, 0.75, 1e-12);
  assertClose(stored.passPowK, 0.625, 1e-12);
  assertClose(stored.wilsonLow, 0.409275, 1e-12);
  assertClose(stored.wilsonHigh, 0.928521, 1e-12);
});

test('citations-only gate policy preserves PASS while incomplete engine trace downgrades PASS to INCONCLUSIVE', () => {
  const citationsPass = makeResult({
    verdict: 'PASS',
    traceStatus: 'disabled',
    modelScore: null,
    routingEvidence: 'citations-only',
  });
  assert.equal(resultVerdict(citationsPass), 'PASS');

  const pendingTrace = makeResult({
    verdict: 'PASS',
    traceStatus: 'pending',
    modelScore: 1,
    routingEvidence: 'unverified',
  });
  assert.equal(modelScore(pendingTrace), 0.5);
  assert.equal(resultVerdict(pendingTrace), 'INCONCLUSIVE');
});

test('M0-04: metrics never computes additive latency residuals and deduplicates events/queries', () => {
  const metricsPath = fileURLToPath(new URL('../../overlay/src/eval/metrics.ts', import.meta.url));
  const source = readFileSync(metricsPath, 'utf8');
  assert.equal(/nondaxms/i.test(source), false, 'metrics.ts must not reference NonDaxMs');
  assert.equal(/latencyms\s*-\s*daxtotalms/i.test(source), false, 'metrics.ts must never subtract DaxTotalMs from LatencyMs');

  // Even when DAX duration spans answer + follow-up and exceeds answer latency, both independent measures are preserved.
  const overlapping = makeResult({
    questionId: 'Q01',
    latencyMs: 3000,
    whyLatencyMs: 2500,
    daxTotalMs: 4400,
    daxQueryCount: 3,
    traceStatus: 'observed',
  });
  const breakdown = latencyBreakdown([overlapping]);
  assert.equal(breakdown.length, 1);
  assert.equal(breakdown[0].answerMs, 3000);
  assert.equal(breakdown[0].daxMs, 4400);
  assert.equal(breakdown[0].whyMs, 2500);
  assert.equal('nonDaxMs' in breakdown[0], false);

  // Duplicate EvalEvent rows (by rowId or natural key) are collapsed in stageDurations.
  const ev1 = {
    runId: 'run-1',
    askId: 'a1',
    eventTimeUtc: new Date('2026-11-01T10:00:18Z'),
    stage: 'score.judge',
    durationMs: 120,
    status: 'ok',
    details: { q: 'Q01' },
    rowId: null,
  };
  const ev1Dup = { ...ev1, durationMs: 125 }; // same natural key (runId, eventTimeUtc, stage, askId, details)
  const stages = stageDurations([ev1, ev1Dup]);
  assert.equal(stages.length, 1);
  assert.equal(stages[0].count, 1);
  assert.equal(stages[0].totalMs, 120);

  // selectView, runCoverage, latestRuns, answerObservations, askTimeline all work end-to-end.
  const run = makeRun({ questionCount: 1, askCount: 1 });
  const q = makeQuestion();
  const queryRow = {
    runId: 'run-1',
    askId: 'run-1-Q01-1',
    queryTimeUtc: new Date('2026-11-01T10:00:12Z'),
    offsetMs: 2000,
    workspaceId: 'ws-1',
    itemId: 'model-1',
    itemName: 'Sales Analytics',
    applicationName: 'PowerBI',
    operationName: 'QueryEnd',
    durationMs: 450,
    dax: 'EVALUATE ROW("v", 1)',
    daxChars: 20,
    correlationId: 'corr-1',
    rowId: 'q-row-1',
    operationId: null,
    applicationContext: null,
    cpuTimeMs: 310,
  };
  const view = selectView(
    {
      runs: [run, run],
      questions: [q, q],
      results: [overlapping, overlapping],
      queries: [queryRow, queryRow],
      events: [ev1, ev1Dup],
      source: 'sample',
      loadedAt: new Date('2026-11-01T12:00:00Z'),
      truncated: false,
    },
    { backend: 'all' },
  );
  assert.equal(view.runs.length, 1);
  assert.equal(view.questions.length, 1);
  assert.equal(view.results.length, 1);
  assert.equal(view.queries.length, 1);
  assert.equal(view.events.length, 1);
  assert.equal(view.incomplete, false);
  assert.equal(latestRuns([run, run]).length, 1);
  assert.equal(answerObservations([overlapping]).length, 1);
  assert.equal(runCoverage(run, [overlapping], [q]).complete, true);
  assert.equal(askTimeline(overlapping, [queryRow, queryRow]).length, 3);
});

test('runSummaries collapses paired multi-backend trials on all-backends lens and live surface filter covers all live targets', () => {
  const dualRun = makeRun({
    runId: 'run-both',
    evalOption: 'both',
    surface: 'mcp-agent',
    target: 'mcp-agent',
    questionCount: 8,
    askCount: 8,
    repeats: 1,
    k: 1,
  });
  const pairedRows = [];
  for (let i = 1; i <= 8; i += 1) {
    const pass = i <= 6;
    const base = {
      runId: 'run-both',
      askId: `run-both-Q0${i}-1`,
      questionId: `Q0${i}`,
      attempt: 1,
      verdict: pass ? 'PASS' : 'FAIL',
      valueScore: pass ? 1 : 0,
    };
    pairedRows.push(makeResult({ ...base, backend: 'fabric-native', rowId: `fn-${i}` }));
    pairedRows.push(makeResult({ ...base, backend: 'foundry', rowId: `fd-${i}` }));
  }

  const [summaryAll] = runSummaries([dualRun], pairedRows, 'all');
  assert.equal(summaryAll.asks, 8);
  assert.equal(summaryAll.scores, 8);
  assertClose(summaryAll.passRate, 6 / 8, 1e-12);
  assertClose(summaryAll.passPowK, 6 / 8, 1e-12);
  const [expectedLow, expectedHigh] = wilsonInterval(6, 8);
  assertClose(summaryAll.wilsonLow, expectedLow, 1e-12);
  assertClose(summaryAll.wilsonHigh, expectedHigh, 1e-12);

  // Live surface filter keeps non-simulated surfaces (copilot-chat-api, mcp-agent, fabric-data-agent, transcript-import)
  const simRun = makeRun({ runId: 'r-sim', surface: 'simulated' });
  const chatRun = makeRun({ runId: 'r-chat', surface: 'copilot-chat-api' });
  const mcpRun = makeRun({ runId: 'r-mcp', surface: 'mcp-agent' });
  const daRun = makeRun({ runId: 'r-da', surface: 'fabric-data-agent' });
  const txRun = makeRun({ runId: 'r-tx', surface: 'transcript-import' });
  const multiSurfaceData = {
    runs: [simRun, chatRun, mcpRun, daRun, txRun],
    questions: [],
    results: [
      makeResult({ runId: 'r-sim', askId: 'a-sim' }),
      makeResult({ runId: 'r-chat', askId: 'a-chat' }),
      makeResult({ runId: 'r-mcp', askId: 'a-mcp' }),
      makeResult({ runId: 'r-da', askId: 'a-da' }),
      makeResult({ runId: 'r-tx', askId: 'a-tx' }),
    ],
    queries: [],
    events: [],
    source: 'sample',
    loadedAt: new Date('2026-11-01T12:00:00Z'),
    truncated: false,
  };
  const liveOnly = selectView(multiSurfaceData, { surface: 'live' });
  assert.deepEqual(
    liveOnly.runs.map((r) => r.runId).sort(),
    ['r-chat', 'r-da', 'r-mcp', 'r-tx'],
  );
  assert.equal(liveOnly.results.length, 4);
});

