import { getRayfinClient } from '@/lib/rayfin-client';
import sample from './sample-data.json';

export type Run = { runId: string; label: string; startedUtc: string | Date; answers: number; passed: number; passRate: number };
export type Result = {
  runId: string; questionId: string; attempt: number; question: string; answer: string;
  expected: number | null; found: number | null; valueCheck: string; valueReason: string;
  citedReports: string; citationCheck: string; citationReason: string; queriedModels: string;
  modelCheck: string; modelReason: string; verdict: string;
};
export type Query = { runId: string; questionId: string; attempt: number; timestamp: string | Date; semanticModel: string; dax: string; durationMs: number | null };
export type Data = { runs: Run[]; results: Result[]; queries: Query[] };

export const sampleData = sample as Data;
const runFields = ['runId', 'label', 'startedUtc', 'answers', 'passed', 'passRate'] as const;
const resultFields = ['runId', 'questionId', 'attempt', 'question', 'answer', 'expected', 'found', 'valueCheck', 'valueReason', 'citedReports', 'citationCheck', 'citationReason', 'queriedModels', 'modelCheck', 'modelReason', 'verdict'] as const;
const queryFields = ['runId', 'questionId', 'attempt', 'timestamp', 'semanticModel', 'dax', 'durationMs'] as const;

export async function loadLive(): Promise<Data> {
  const client = await getRayfinClient();
  const entities = client.connectors.evals;
  async function pages<T>(read: (cursor?: string) => Promise<{ items: T[]; hasNextPage: boolean; endCursor?: string | null }>): Promise<T[]> {
    const rows: T[] = [];
    let cursor: string | undefined;
    do {
      const page = await read(cursor);
      rows.push(...page.items);
      if (!page.hasNextPage) break;
      if (!page.endCursor || page.endCursor === cursor) throw new Error('The connector did not return a valid next-page cursor.');
      cursor = page.endCursor;
    } while (true);
    return rows;
  }
  const [runs, results, queries] = await Promise.all([
    pages(cursor => {
      const query = entities.EvalRuns.select([...runFields]).first(1000);
      return (cursor ? query.after(cursor) : query).executePaginated();
    }),
    pages(cursor => {
      const query = entities.EvalResults.select([...resultFields]).first(1000);
      return (cursor ? query.after(cursor) : query).executePaginated();
    }),
    pages(cursor => {
      const query = entities.EvalQueries.select([...queryFields]).first(1000);
      return (cursor ? query.after(cursor) : query).executePaginated();
    }),
  ]);
  return { runs, results, queries } as unknown as Data;
}

export function touchedDecoy(result: Result): boolean {
  return /\bdecoy\b/i.test(`${result.citationReason || ''} ${result.modelReason || ''}`);
}
