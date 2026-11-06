// Loads telemetry either from the deployed connector (live) or from the bundled sample file.
import { COLUMNS, FIELDS, type EntityName, type EvalEventRow, type EvalQuestionRow, type EvalResultRow, type EvalRunRow, type FabricIqQueryRow } from './generated/contract';
import { distinctRows, type EvalData } from './metrics';
import { normalizeRows, type RawRow } from './normalize';
import type { DataMode } from './loadState';

export function configuredMode(): DataMode {
  const mode = String(import.meta.env.VITE_EVAL_DATA ?? 'auto').toLowerCase();
  return mode === 'live' || mode === 'sample' ? mode : 'auto';
}

function build(tables: Partial<Record<EntityName, RawRow[]>>, source: EvalData['source'], truncated: boolean): EvalData {
  return {
    runs: normalizeRows<EvalRunRow>(tables.EvalRun ?? [], COLUMNS.EvalRun),
    questions: distinctRows(normalizeRows<EvalQuestionRow>(tables.EvalQuestion ?? [], COLUMNS.EvalQuestion)),
    results: normalizeRows<EvalResultRow>(tables.EvalResult ?? [], COLUMNS.EvalResult),
    queries: distinctRows(normalizeRows<FabricIqQueryRow>(tables.FabricIqQuery ?? [], COLUMNS.FabricIqQuery)),
    events: distinctRows(normalizeRows<EvalEventRow>(tables.EvalEvent ?? [], COLUMNS.EvalEvent)),
    source,
    truncated,
    loadedAt: new Date(),
  };
}

export async function loadSample(): Promise<EvalData> {
  const res = await fetch(`${import.meta.env.BASE_URL}sample-data/evals.json`);
  if (!res.ok) throw new Error(`Sample data not found (${res.status}). Run: python -m cfeval demo-data --app-json …`);
  const json = (await res.json()) as { tables: Partial<Record<EntityName, RawRow[]>> };
  return build(json.tables, 'sample', false);
}

// Minimal structural view of a connector entity's query chain (see the Rayfin "Fabric SQL sources" docs).
interface Page { items: RawRow[]; hasNextPage: boolean; endCursor?: string }
interface QueryChain {
  where(filter: Record<string, unknown>): QueryChain;
  orderBy(order: Record<string, 'asc' | 'desc'>): QueryChain;
  first(n: number): QueryChain;
  after(cursor: string): QueryChain;
  executePaginated?: () => Promise<Page>;
  execute(): Promise<RawRow[]>;
}
interface EntityClient { select(fields: string[]): QueryChain }

const PAGE_SIZE = 500;
const MAX_ROWS = 20000;

async function readAll(entity: EntityClient, fields: readonly string[], timeField: string, since?: Date, filter?: Record<string, unknown>): Promise<{ rows: RawRow[]; truncated: boolean }> {
  const rows: RawRow[] = [];
  let cursor: string | undefined;
  for (;;) {
    let chain = entity.select([...fields]);
    if (since) chain = chain.where({ [timeField]: { gte: since } });
    if (filter) chain = chain.where(filter);
    chain = chain.orderBy({ [timeField]: 'desc' }).first(PAGE_SIZE);
    if (cursor) chain = chain.after(cursor);
    if (!chain.executePaginated) {
      const items = await chain.execute();
      return { rows: items, truncated: items.length >= PAGE_SIZE };
    }
    const page = await chain.executePaginated();
    rows.push(...page.items);
    if (!page.hasNextPage) return { rows, truncated: false };
    if (!page.endCursor || page.endCursor === cursor) return { rows, truncated: true };
    if (rows.length >= MAX_ROWS) return { rows, truncated: true };
    cursor = page.endCursor;
  }
}

export async function loadLive(sinceDays: number): Promise<EvalData> {
  const { rayfinClient } = await import('./rayfinClient');
  const evals = (rayfinClient.connectors as unknown as { evals: Record<EntityName, EntityClient> }).evals;
  const since = new Date(Date.now() - sinceDays * 86400000);
  const [runs, results, queries, events] = await Promise.all([
    readAll(evals.EvalRun, FIELDS.EvalRun, 'startedUtc', since),
    readAll(evals.EvalResult, FIELDS.EvalResult, 'askStartUtc', since),
    readAll(evals.FabricIqQuery, FIELDS.FabricIqQuery, 'queryTimeUtc', since),
    readAll(evals.EvalEvent, FIELDS.EvalEvent, 'eventTimeUtc', since),
  ]);
  const runIds = [...new Set([...runs.rows, ...results.rows].map((r) => r.runId ?? r.RunId).filter((id): id is string => typeof id === 'string'))];
  // EvalQuestion has no timestamp. Use discovered RunIds and documented DAB or/eq filters.
  const questions = runIds.length
    ? await readAll(evals.EvalQuestion, FIELDS.EvalQuestion, 'runId', undefined, { or: runIds.map((id) => ({ runId: { eq: id } })) })
    : { rows: [], truncated: false };
  const truncated = runs.truncated || results.truncated || queries.truncated || events.truncated || questions.truncated;
  return build({ EvalRun: runs.rows, EvalQuestion: questions.rows, EvalResult: results.rows, FabricIqQuery: queries.rows, EvalEvent: events.rows }, 'live', truncated);
}
