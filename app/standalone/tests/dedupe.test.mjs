import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  TABLES,
  analyzeBundle,
  dedupeBundle,
  naturalKey,
  rowKey,
} from '../../scripts/dedupe-sample.mjs';

const SCRIPT_PATH = fileURLToPath(new URL('../../scripts/dedupe-sample.mjs', import.meta.url));
const SCRATCH_DIR = fileURLToPath(new URL('./.scratch-dedupe', import.meta.url));

function makeCleanBundle() {
  return {
    generatedUtc: '2026-11-13T00:00:00Z',
    simulated: true,
    tables: {
      EvalRun: [
        { RunId: 'run-1', RunName: 'Baseline 1', EvalOption: 'fabric-native' },
      ],
      EvalQuestion: [
        { RunId: 'run-1', QuestionId: 'Q01', Question: 'Gross revenue FY2025?' },
      ],
      EvalResult: [
        { RunId: 'run-1', AskId: 'run-1-Q01-1', Backend: 'fabric-native', Verdict: 'PASS', Reasons: '' },
      ],
      FabricIqQuery: [
        {
          RunId: 'run-1',
          AskId: 'run-1-Q01-1',
          StartTimeUtc: '2026-11-13T00:00:03Z',
          QueryHash: 'hash-abc123',
          Dax: 'EVALUATE ROW("v", 12840000)',
        },
      ],
      EvalEvent: [
        {
          RunId: 'run-1',
          Timestamp: '2026-11-13T00:00:05Z',
          Stage: 'copilot.ask',
          AskId: 'run-1-Q01-1',
          Detail: '{"question_id":"Q01"}',
        },
      ],
    },
  };
}

test('analyzeBundle reports zero duplicates on a clean 5-table bundle', () => {
  assert.deepEqual(TABLES, ['EvalRun', 'EvalQuestion', 'EvalResult', 'FabricIqQuery', 'EvalEvent']);
  const bundle = makeCleanBundle();
  const report = analyzeBundle(bundle);
  assert.equal(report.totalDuplicates, 0);
  assert.equal(report.hasDuplicates, false);
  for (const table of TABLES) {
    assert.equal(report.duplicates[table], 0);
    assert.equal(report.counts[table].total, 1);
    assert.equal(report.counts[table].unique, 1);
  }
});

test('dedupeBundle detects and collapses duplicates across all 5 tables by RowId and natural key', () => {
  const dirty = {
    generatedUtc: '2026-11-13T00:00:00Z',
    simulated: true,
    tables: {
      EvalRun: [
        { RunId: 'run-1', RunName: 'First copy' },
        { RunId: 'run-1', RunName: 'Duplicate RunId copy' },
        { RunId: 'run-2', RowId: 'explicit-run-row', RunName: 'Run 2' },
        { RunId: 'run-3', RowId: 'explicit-run-row', RunName: 'Duplicate explicit RowId' },
      ],
      EvalQuestion: [
        { RunId: 'run-1', QuestionId: 'Q01', Question: 'Gross revenue?' },
        { RunId: 'run-1', QuestionId: 'Q01', Question: 'Duplicate question snapshot' },
      ],
      EvalResult: [
        { RunId: 'run-1', AskId: 'a1', Backend: 'fabric-native', Verdict: 'PASS', JudgeNotes: 'note A' },
        { RunId: 'run-1', AskId: 'a1', Backend: 'fabric-native', Verdict: 'PASS', JudgeNotes: 'note B' },
        { RunId: 'run-1', AskId: 'a1', Backend: 'foundry', Verdict: 'PASS', JudgeNotes: 'distinct backend kept' },
      ],
      FabricIqQuery: [
        { RunId: 'run-1', AskId: 'a1', StartTimeUtc: '2026-11-13T00:00:02Z', QueryHash: 'qh1' },
        { RunId: 'run-1', AskId: 'a1', StartTimeUtc: '2026-11-13T00:00:02Z', QueryHash: 'qh1', DurationMs: 99 },
        { RunId: 'run-1', AskId: 'a2', RowId: 'q-rowid-1', QueryTimeUtc: '2026-11-13T00:01:00Z', Dax: 'EVALUATE {1}' },
        { RunId: 'run-1', AskId: 'a2', RowId: 'q-rowid-1', QueryTimeUtc: '2026-11-13T00:01:05Z', Dax: 'EVALUATE {2}' },
      ],
      EvalEvent: [
        { RunId: 'run-1', Timestamp: '2026-11-13T00:00:10Z', Stage: 'score.judge', AskId: 'a1', Detail: 'ok', DurationMs: 0.1 },
        { RunId: 'run-1', Timestamp: '2026-11-13T00:00:10Z', Stage: 'score.judge', AskId: 'a1', Detail: 'ok', DurationMs: 0.2 },
      ],
    },
  };

  assert.equal(naturalKey('EvalRun', { RunId: 'r1' }), 'r1');
  assert.equal(naturalKey('EvalQuestion', { RunId: 'r1', QuestionId: 'Q01' }), 'r1|Q01');
  assert.equal(naturalKey('EvalResult', { RunId: 'r1', AskId: 'a1', Backend: 'foundry' }), 'r1|a1|foundry');
  assert.equal(
    naturalKey('FabricIqQuery', { RunId: 'r1', AskId: 'a1', StartTimeUtc: 't0', QueryHash: 'h0' }),
    'r1|a1|t0|h0',
  );
  assert.equal(
    naturalKey('EvalEvent', { RunId: 'r1', Timestamp: 't1', Stage: 'ask', AskId: 'a1', Detail: 'd1' }),
    'r1|t1|ask|a1|d1',
  );
  assert.equal(rowKey('EvalResult', { RowId: 'custom-id', RunId: 'r1', AskId: 'a1', Backend: 'foundry' }), 'custom-id');

  const before = analyzeBundle(dirty);
  assert.equal(before.hasDuplicates, true);
  assert.deepEqual(before.duplicates, {
    EvalRun: 2,
    EvalQuestion: 1,
    EvalResult: 1,
    FabricIqQuery: 2,
    EvalEvent: 1,
  });
  assert.equal(before.totalDuplicates, 7);

  const cleaned = dedupeBundle(dirty);
  const after = analyzeBundle(cleaned);
  assert.equal(after.totalDuplicates, 0);
  assert.equal(after.hasDuplicates, false);
  assert.equal(cleaned.tables.EvalRun.length, 2);
  assert.equal(cleaned.tables.EvalQuestion.length, 1);
  assert.equal(cleaned.tables.EvalResult.length, 2);
  assert.equal(cleaned.tables.FabricIqQuery.length, 2);
  assert.equal(cleaned.tables.EvalEvent.length, 1);
});

test('CLI --check exits 1 without modifying dirty file and exits 0 after deduplication', () => {
  mkdirSync(SCRATCH_DIR, { recursive: true });
  try {
    const sampleFile = join(SCRATCH_DIR, 'sample-check.json');
    const clean = makeCleanBundle();
    const dirty = {
      ...clean,
      tables: {
        ...clean.tables,
        EvalResult: [...clean.tables.EvalResult, { ...clean.tables.EvalResult[0], Reasons: 'dup' }],
      },
    };
    const originalText = `${JSON.stringify(dirty, null, 1)}\n`;
    writeFileSync(sampleFile, originalText, 'utf8');

    // --check must fail with exit code 1 and MUST NOT modify the file on disk.
    const checkFail = spawnSync(process.execPath, [SCRIPT_PATH, '--file', sampleFile, '--check'], { encoding: 'utf8' });
    assert.equal(checkFail.status, 1);
    assert.match(checkFail.stdout, /"EvalResult":1/);
    assert.equal(readFileSync(sampleFile, 'utf8'), originalText);

    // Running without --check deduplicates in place and exits 0.
    const fixRun = spawnSync(process.execPath, [SCRIPT_PATH, '--file', sampleFile], { encoding: 'utf8' });
    assert.equal(fixRun.status, 0);

    // Subsequent --check exits 0.
    const checkPass = spawnSync(process.execPath, [SCRIPT_PATH, '--file', sampleFile, '--check'], { encoding: 'utf8' });
    assert.equal(checkPass.status, 0);
    assert.match(checkPass.stdout, /\(total: 0\)/);
  } finally {
    rmSync(SCRATCH_DIR, { recursive: true, force: true });
  }
});
