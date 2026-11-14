#!/usr/bin/env node
// Check or remove duplicate records across all 5 evaluation tables using RowId or natural keys.
// Never reads a live source.
//   node app/scripts/dedupe-sample.mjs [--file <sample.json>] [--check]
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const TABLES = ['EvalRun', 'EvalQuestion', 'EvalResult', 'FabricIqQuery', 'EvalEvent'];

function hasNonEmpty(value) {
  return value !== undefined && value !== null && String(value) !== '';
}

function stableDetail(value) {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  if (typeof value !== 'object') return String(value);
  if (Array.isArray(value)) return `[${value.map(stableDetail).join(',')}]`;
  const entries = Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableDetail(v)}`).join(',')}}`;
}

function shortHash(text) {
  return createHash('sha256').update(String(text)).digest('hex').slice(0, 16);
}

export function naturalKey(table, row) {
  const runId = row?.RunId ?? row?.runId ?? '';
  switch (table) {
    case 'EvalRun':
      return `${runId}`;
    case 'EvalQuestion':
      return `${runId}|${row?.QuestionId ?? row?.questionId ?? ''}`;
    case 'EvalResult':
      return `${runId}|${row?.AskId ?? row?.askId ?? ''}|${row?.Backend ?? row?.backend ?? ''}`;
    case 'FabricIqQuery': {
      const askId = row?.AskId ?? row?.askId ?? '';
      const startTime = row?.StartTimeUtc ?? row?.QueryTimeUtc ?? row?.startTimeUtc ?? row?.queryTimeUtc ?? '';
      const queryHash = hasNonEmpty(row?.QueryHash ?? row?.queryHash)
        ? (row.QueryHash ?? row.queryHash)
        : (row?.Dax !== undefined || row?.dax !== undefined
          ? shortHash(row.Dax ?? row.dax ?? '')
          : (row?.CorrelationId ?? row?.correlationId ?? ''));
      return `${runId}|${askId}|${startTime}|${queryHash}`;
    }
    case 'EvalEvent': {
      const ts = row?.Timestamp ?? row?.EventTimeUtc ?? row?.timestamp ?? row?.eventTimeUtc ?? '';
      const stage = row?.Stage ?? row?.stage ?? '';
      const askId = row?.AskId ?? row?.askId ?? '';
      const rawDetail = row?.Detail !== undefined
        ? row.Detail
        : (row?.Details !== undefined ? row.Details : (row?.detail !== undefined ? row.detail : row?.details));
      return `${runId}|${ts}|${stage}|${askId}|${stableDetail(rawDetail)}`;
    }
    default:
      return stableDetail(row);
  }
}

export function rowKey(table, row) {
  const explicitRowId = row?.RowId ?? row?.rowId;
  return hasNonEmpty(explicitRowId) ? String(explicitRowId) : naturalKey(table, row);
}

function inspectTables(bundle) {
  const hasTablesWrapper = Boolean(bundle && typeof bundle === 'object' && bundle.tables && typeof bundle.tables === 'object');
  const sourceTables = hasTablesWrapper ? bundle.tables : (bundle ?? {});
  const dedupedTables = { ...sourceTables };
  const duplicates = {};
  const counts = {};
  let totalDuplicates = 0;

  for (const table of TABLES) {
    const rows = Array.isArray(sourceTables[table]) ? sourceTables[table] : [];
    const seen = new Set();
    const kept = [];
    for (const row of rows) {
      const key = rowKey(table, row);
      if (seen.has(key)) continue;
      seen.add(key);
      kept.push(row);
    }
    const removedCount = rows.length - kept.length;
    dedupedTables[table] = kept;
    duplicates[table] = removedCount;
    counts[table] = { total: rows.length, unique: kept.length, duplicates: removedCount };
    totalDuplicates += removedCount;
  }

  const cleaned = hasTablesWrapper ? { ...bundle, tables: dedupedTables } : dedupedTables;
  return { cleaned, duplicates, counts, totalDuplicates, hasDuplicates: totalDuplicates > 0 };
}

export function analyzeBundle(bundle) {
  const { duplicates, counts, totalDuplicates, hasDuplicates } = inspectTables(bundle);
  return { duplicates, counts, totalDuplicates, hasDuplicates };
}

export function dedupeBundle(bundle) {
  return inspectTables(bundle).cleaned;
}

export function dedupeSample(sample) {
  const { cleaned, duplicates } = inspectTables(sample);
  return { data: cleaned, removed: duplicates };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  const checkOnly = args.includes('--check');
  const fileFlagIndex = args.indexOf('--file');
  const positionalFile = args.find((arg, idx) => !arg.startsWith('--') && idx !== fileFlagIndex + 1);
  const defaultFile = fileURLToPath(new URL('../overlay/public/sample-data/evals.json', import.meta.url));
  const file = fileFlagIndex >= 0 ? args[fileFlagIndex + 1] : (positionalFile ?? defaultFile);

  const raw = JSON.parse(readFileSync(file, 'utf8'));
  const analysis = analyzeBundle(raw);
  if (checkOnly) {
    console.log(`Duplicate counts per table: ${JSON.stringify(analysis.duplicates)} (total: ${analysis.totalDuplicates})`);
    process.exitCode = analysis.hasDuplicates ? 1 : 0;
  } else {
    if (analysis.hasDuplicates) {
      const cleaned = dedupeBundle(raw);
      writeFileSync(file, `${JSON.stringify(cleaned, null, 1)}\n`);
    }
    console.log(`Removed duplicate rows: ${JSON.stringify(analysis.duplicates)} (total: ${analysis.totalDuplicates})`);
  }
}
