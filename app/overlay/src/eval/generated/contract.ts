// Generated from src/cfeval/schema.py by tools/gen_app_contract.py. Do not edit by hand.
// Property names follow the Rayfin entity convention: camelCase of the SQL column name.

export type ColumnType = 'string' | 'int' | 'real' | 'datetime' | 'dynamic';
/** property name -> [SQL column name, telemetry type] */
export type ColumnMap = Record<string, readonly [string, ColumnType]>;

/** One row per evaluation run (written when the run finishes). */
export interface EvalRunRow {
  runId: string | null;
  runName: string | null;
  evalOption: string | null;
  surface: string | null;
  startedUtc: Date | null;
  endedUtc: Date | null;
  status: string | null;
  host: string | null;
  harnessVersion: string | null;
  goldenSetName: string | null;
  goldenSetHash: string | null;
  questionCount: number | null;
  askCount: number | null;
  repeats: number | null;
  explainMode: string | null;
  traceEnabled: number | null;
  testUser: string | null;
  judgeModel: string | null;
  foundryEvalId: string | null;
  foundryRunId: string | null;
  foundryReportUrl: string | null;
  passRate: number | null;
  valueAccuracy: number | null;
  artifactAccuracy: number | null;
  modelAccuracy: number | null;
  latencyP50Ms: number | null;
  latencyP95Ms: number | null;
  notes: string | null;
  rowId: string | null;
  target: string | null;
  k: number | null;
  passPowK: number | null;
  wilsonLow: number | null;
  wilsonHigh: number | null;
  judgePromptHash: string | null;
  judgeCalibrationId: string | null;
  gatePolicyHash: string | null;
  schemaVersion: number | null;
}

/** Snapshot of the golden set used by each run. */
export interface EvalQuestionRow {
  runId: string | null;
  questionId: string | null;
  question: string | null;
  category: string | null;
  expectedArtifact: string | null;
  artifactAliases: string | null;
  expectedModel: string | null;
  decoys: string | null;
  expectedValue: number | null;
  unit: string | null;
  relTol: number | null;
  absTol: number | null;
  expectedAnswer: string | null;
  referenceDax: string | null;
  criticality: string | null;
  rowId: string | null;
  expectedArtifactId: string | null;
  caseType: string | null;
  persona: string | null;
  tags: string | null;
  intent: string | null;
  gates: string | null;
  paraphrase: string | null;
}

/** DAX queries Fabric IQ ran for each ask, from workspace monitoring (SemanticModelLogs). */
export interface FabricIqQueryRow {
  runId: string | null;
  askId: string | null;
  queryTimeUtc: Date | null;
  offsetMs: number | null;
  workspaceId: string | null;
  itemId: string | null;
  itemName: string | null;
  applicationName: string | null;
  operationName: string | null;
  durationMs: number | null;
  dax: string | null;
  daxChars: number | null;
  correlationId: string | null;
  rowId: string | null;
  operationId: string | null;
  applicationContext: string | null;
  cpuTimeMs: number | null;
}

/** One row per ask per scoring backend: verdict, accuracy, routing, DAX and latency in one place. */
export interface EvalResultRow {
  runId: string | null;
  askId: string | null;
  questionId: string | null;
  attempt: number | null;
  question: string | null;
  category: string | null;
  criticality: string | null;
  testUser: string | null;
  askStartUtc: Date | null;
  backend: string | null;
  verdict: string | null;
  valueScore: number | null;
  artifactScore: number | null;
  modelScore: number | null;
  judgeAnswerScore: number | null;
  whyScore: number | null;
  decoyHit: number | null;
  powerBiCited: number | null;
  expectedArtifact: string | null;
  citedArtifacts: string | null;
  expectedModel: string | null;
  queriedModels: string | null;
  expectedValue: number | null;
  extractedValue: number | null;
  valueErrorPct: number | null;
  latencyMs: number | null;
  whyLatencyMs: number | null;
  daxQueryCount: number | null;
  daxTotalMs: number | null;
  daxMaxMs: number | null;
  firstDaxOffsetMs: number | null;
  traceStatus: string | null;
  answerPreview: string | null;
  whyPreview: string | null;
  reasons: string | null;
  judgeNotes: string | null;
  error: string | null;
  scoredUtc: Date | null;
  rowId: string | null;
  caseType: string | null;
  persona: string | null;
  matchKind: string | null;
  extractionMethod: string | null;
  routingEvidence: string | null;
  correlationConfidence: string | null;
}

/** Stage timings for end-to-end telemetry: ask, follow-up, trace, scoring, publish. */
export interface EvalEventRow {
  runId: string | null;
  askId: string | null;
  eventTimeUtc: Date | null;
  stage: string | null;
  durationMs: number | null;
  status: string | null;
  details: string | null;
  rowId: string | null;
}

export const ENTITY_NAMES = ['EvalRun', 'EvalQuestion', 'FabricIqQuery', 'EvalResult', 'EvalEvent'] as const;
export type EntityName = (typeof ENTITY_NAMES)[number];

export const COLUMNS: Record<EntityName, ColumnMap> = {
  EvalRun: {
    runId: ['RunId', 'string'],
    runName: ['RunName', 'string'],
    evalOption: ['EvalOption', 'string'],
    surface: ['Surface', 'string'],
    startedUtc: ['StartedUtc', 'datetime'],
    endedUtc: ['EndedUtc', 'datetime'],
    status: ['Status', 'string'],
    host: ['Host', 'string'],
    harnessVersion: ['HarnessVersion', 'string'],
    goldenSetName: ['GoldenSetName', 'string'],
    goldenSetHash: ['GoldenSetHash', 'string'],
    questionCount: ['QuestionCount', 'int'],
    askCount: ['AskCount', 'int'],
    repeats: ['Repeats', 'int'],
    explainMode: ['ExplainMode', 'string'],
    traceEnabled: ['TraceEnabled', 'int'],
    testUser: ['TestUser', 'string'],
    judgeModel: ['JudgeModel', 'string'],
    foundryEvalId: ['FoundryEvalId', 'string'],
    foundryRunId: ['FoundryRunId', 'string'],
    foundryReportUrl: ['FoundryReportUrl', 'string'],
    passRate: ['PassRate', 'real'],
    valueAccuracy: ['ValueAccuracy', 'real'],
    artifactAccuracy: ['ArtifactAccuracy', 'real'],
    modelAccuracy: ['ModelAccuracy', 'real'],
    latencyP50Ms: ['LatencyP50Ms', 'real'],
    latencyP95Ms: ['LatencyP95Ms', 'real'],
    notes: ['Notes', 'string'],
    rowId: ['RowId', 'string'],
    target: ['Target', 'string'],
    k: ['K', 'int'],
    passPowK: ['PassPowK', 'real'],
    wilsonLow: ['WilsonLow', 'real'],
    wilsonHigh: ['WilsonHigh', 'real'],
    judgePromptHash: ['JudgePromptHash', 'string'],
    judgeCalibrationId: ['JudgeCalibrationId', 'string'],
    gatePolicyHash: ['GatePolicyHash', 'string'],
    schemaVersion: ['SchemaVersion', 'int'],
  },
  EvalQuestion: {
    runId: ['RunId', 'string'],
    questionId: ['QuestionId', 'string'],
    question: ['Question', 'string'],
    category: ['Category', 'string'],
    expectedArtifact: ['ExpectedArtifact', 'string'],
    artifactAliases: ['ArtifactAliases', 'string'],
    expectedModel: ['ExpectedModel', 'string'],
    decoys: ['Decoys', 'string'],
    expectedValue: ['ExpectedValue', 'real'],
    unit: ['Unit', 'string'],
    relTol: ['RelTol', 'real'],
    absTol: ['AbsTol', 'real'],
    expectedAnswer: ['ExpectedAnswer', 'string'],
    referenceDax: ['ReferenceDax', 'string'],
    criticality: ['Criticality', 'string'],
    rowId: ['RowId', 'string'],
    expectedArtifactId: ['ExpectedArtifactId', 'string'],
    caseType: ['CaseType', 'string'],
    persona: ['Persona', 'string'],
    tags: ['Tags', 'string'],
    intent: ['Intent', 'string'],
    gates: ['Gates', 'string'],
    paraphrase: ['Paraphrase', 'string'],
  },
  FabricIqQuery: {
    runId: ['RunId', 'string'],
    askId: ['AskId', 'string'],
    queryTimeUtc: ['QueryTimeUtc', 'datetime'],
    offsetMs: ['OffsetMs', 'real'],
    workspaceId: ['WorkspaceId', 'string'],
    itemId: ['ItemId', 'string'],
    itemName: ['ItemName', 'string'],
    applicationName: ['ApplicationName', 'string'],
    operationName: ['OperationName', 'string'],
    durationMs: ['DurationMs', 'real'],
    dax: ['Dax', 'string'],
    daxChars: ['DaxChars', 'int'],
    correlationId: ['CorrelationId', 'string'],
    rowId: ['RowId', 'string'],
    operationId: ['OperationId', 'string'],
    applicationContext: ['ApplicationContext', 'string'],
    cpuTimeMs: ['CpuTimeMs', 'real'],
  },
  EvalResult: {
    runId: ['RunId', 'string'],
    askId: ['AskId', 'string'],
    questionId: ['QuestionId', 'string'],
    attempt: ['Attempt', 'int'],
    question: ['Question', 'string'],
    category: ['Category', 'string'],
    criticality: ['Criticality', 'string'],
    testUser: ['TestUser', 'string'],
    askStartUtc: ['AskStartUtc', 'datetime'],
    backend: ['Backend', 'string'],
    verdict: ['Verdict', 'string'],
    valueScore: ['ValueScore', 'real'],
    artifactScore: ['ArtifactScore', 'real'],
    modelScore: ['ModelScore', 'real'],
    judgeAnswerScore: ['JudgeAnswerScore', 'real'],
    whyScore: ['WhyScore', 'real'],
    decoyHit: ['DecoyHit', 'int'],
    powerBiCited: ['PowerBiCited', 'int'],
    expectedArtifact: ['ExpectedArtifact', 'string'],
    citedArtifacts: ['CitedArtifacts', 'string'],
    expectedModel: ['ExpectedModel', 'string'],
    queriedModels: ['QueriedModels', 'string'],
    expectedValue: ['ExpectedValue', 'real'],
    extractedValue: ['ExtractedValue', 'real'],
    valueErrorPct: ['ValueErrorPct', 'real'],
    latencyMs: ['LatencyMs', 'real'],
    whyLatencyMs: ['WhyLatencyMs', 'real'],
    daxQueryCount: ['DaxQueryCount', 'int'],
    daxTotalMs: ['DaxTotalMs', 'real'],
    daxMaxMs: ['DaxMaxMs', 'real'],
    firstDaxOffsetMs: ['FirstDaxOffsetMs', 'real'],
    traceStatus: ['TraceStatus', 'string'],
    answerPreview: ['AnswerPreview', 'string'],
    whyPreview: ['WhyPreview', 'string'],
    reasons: ['Reasons', 'string'],
    judgeNotes: ['JudgeNotes', 'string'],
    error: ['Error', 'string'],
    scoredUtc: ['ScoredUtc', 'datetime'],
    rowId: ['RowId', 'string'],
    caseType: ['CaseType', 'string'],
    persona: ['Persona', 'string'],
    matchKind: ['MatchKind', 'string'],
    extractionMethod: ['ExtractionMethod', 'string'],
    routingEvidence: ['RoutingEvidence', 'string'],
    correlationConfidence: ['CorrelationConfidence', 'string'],
  },
  EvalEvent: {
    runId: ['RunId', 'string'],
    askId: ['AskId', 'string'],
    eventTimeUtc: ['EventTimeUtc', 'datetime'],
    stage: ['Stage', 'string'],
    durationMs: ['DurationMs', 'real'],
    status: ['Status', 'string'],
    details: ['Details', 'dynamic'],
    rowId: ['RowId', 'string'],
  },
};

export const FIELDS: Record<EntityName, readonly string[]> = {
  EvalRun: ['runId', 'runName', 'evalOption', 'surface', 'startedUtc', 'endedUtc', 'status', 'host', 'harnessVersion', 'goldenSetName', 'goldenSetHash', 'questionCount', 'askCount', 'repeats', 'explainMode', 'traceEnabled', 'testUser', 'judgeModel', 'foundryEvalId', 'foundryRunId', 'foundryReportUrl', 'passRate', 'valueAccuracy', 'artifactAccuracy', 'modelAccuracy', 'latencyP50Ms', 'latencyP95Ms', 'notes', 'rowId', 'target', 'k', 'passPowK', 'wilsonLow', 'wilsonHigh', 'judgePromptHash', 'judgeCalibrationId', 'gatePolicyHash', 'schemaVersion'],
  EvalQuestion: ['runId', 'questionId', 'question', 'category', 'expectedArtifact', 'artifactAliases', 'expectedModel', 'decoys', 'expectedValue', 'unit', 'relTol', 'absTol', 'expectedAnswer', 'referenceDax', 'criticality', 'rowId', 'expectedArtifactId', 'caseType', 'persona', 'tags', 'intent', 'gates', 'paraphrase'],
  FabricIqQuery: ['runId', 'askId', 'queryTimeUtc', 'offsetMs', 'workspaceId', 'itemId', 'itemName', 'applicationName', 'operationName', 'durationMs', 'dax', 'daxChars', 'correlationId', 'rowId', 'operationId', 'applicationContext', 'cpuTimeMs'],
  EvalResult: ['runId', 'askId', 'questionId', 'attempt', 'question', 'category', 'criticality', 'testUser', 'askStartUtc', 'backend', 'verdict', 'valueScore', 'artifactScore', 'modelScore', 'judgeAnswerScore', 'whyScore', 'decoyHit', 'powerBiCited', 'expectedArtifact', 'citedArtifacts', 'expectedModel', 'queriedModels', 'expectedValue', 'extractedValue', 'valueErrorPct', 'latencyMs', 'whyLatencyMs', 'daxQueryCount', 'daxTotalMs', 'daxMaxMs', 'firstDaxOffsetMs', 'traceStatus', 'answerPreview', 'whyPreview', 'reasons', 'judgeNotes', 'error', 'scoredUtc', 'rowId', 'caseType', 'persona', 'matchKind', 'extractionMethod', 'routingEvidence', 'correlationConfidence'],
  EvalEvent: ['runId', 'askId', 'eventTimeUtc', 'stage', 'durationMs', 'status', 'details', 'rowId'],
};
