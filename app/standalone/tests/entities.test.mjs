import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { COLUMNS } from '../../overlay/src/eval/generated/contract.ts';
import {
  APP_TABLES,
  camelCase,
  pascalCase,
  prepareGeneration,
} from '../../scripts/generate-entities.mjs';

const METADATA_EXAMPLE = fileURLToPath(new URL('../../connectors/evals/metadata.example.json', import.meta.url));
const SCRATCH_DIR = fileURLToPath(new URL('./.scratch-entities', import.meta.url));

test('camelCase and pascalCase follow Rayfin entity naming conventions', () => {
  assert.equal(camelCase('RunId'), 'runId');
  assert.equal(camelCase('LatencyP95Ms'), 'latencyP95Ms');
  assert.equal(camelCase('FirstDaxOffsetMs'), 'firstDaxOffsetMs');
  assert.equal(pascalCase('evals'), 'Evals');
  assert.equal(pascalCase('EvalResult'), 'EvalResult');
});

test('prepareGeneration validates metadata.example.json and generates all 5 read-only entities', () => {
  const outDir = join(SCRATCH_DIR, 'out');
  const plan = prepareGeneration({
    metadata: METADATA_EXAMPLE,
    out: outDir,
    connector: 'evals',
  });

  assert.equal(plan.entities.length, APP_TABLES.length);
  assert.deepEqual(
    plan.entities.map((e) => e.className),
    APP_TABLES,
  );
  assert.match(plan.schema, /connector: 'fabric-sqlanalytics'/);
  assert.match(plan.schema, /operations: \['read'\]/);
  assert.match(plan.schema, /export type EvalsSchema = GraphQLBackedConnector</);

  for (const entity of plan.entities) {
    assert.match(entity.text, /@role\('authenticated', \['read'\]\)/);
    assert.match(entity.text, /@entity\(\)/);
    const requiredProps = Object.keys(COLUMNS[entity.className] ?? {});
    for (const prop of requiredProps) {
      assert.ok(
        entity.fields.includes(prop),
        `Entity ${entity.className} missing contract field ${prop}`,
      );
    }
  }
});

test('prepareGeneration rejects missing tables, missing columns, and incompatible SQL types', () => {
  mkdirSync(SCRATCH_DIR, { recursive: true });
  try {
    const baseMeta = JSON.parse(readFileSync(METADATA_EXAMPLE, 'utf8'));

    // 1. Missing required table
    const missingTablePath = join(SCRATCH_DIR, 'missing-table.json');
    const missingTableMeta = {
      schemas: [
        {
          schemaName: 'dbo',
          tables: baseMeta.schemas[0].tables.filter((t) => t.tableName !== 'EvalEvent'),
        },
      ],
    };
    writeFileSync(missingTablePath, JSON.stringify(missingTableMeta), 'utf8');
    assert.throws(
      () => prepareGeneration({ metadata: missingTablePath, out: SCRATCH_DIR }),
      /metadata\.json has no table\(s\) EvalEvent/,
    );

    // 2. Missing required column
    const missingColPath = join(SCRATCH_DIR, 'missing-col.json');
    const missingColMeta = structuredClone(baseMeta);
    const evalRunTable = missingColMeta.schemas[0].tables.find((t) => t.tableName === 'EvalRun');
    evalRunTable.columns = evalRunTable.columns.filter((c) => c.columnName !== 'RunId');
    writeFileSync(missingColPath, JSON.stringify(missingColMeta), 'utf8');
    assert.throws(
      () => prepareGeneration({ metadata: missingColPath, out: SCRATCH_DIR }),
      /missing required column EvalRun\.RunId/,
    );

    // 3. Incompatible SQL dataType
    const badTypePath = join(SCRATCH_DIR, 'bad-type.json');
    const badTypeMeta = structuredClone(baseMeta);
    const evalResultTable = badTypeMeta.schemas[0].tables.find((t) => t.tableName === 'EvalResult');
    const passCol = evalResultTable.columns.find((c) => c.columnName === 'LatencyMs');
    passCol.dataType = 'varchar';
    writeFileSync(badTypePath, JSON.stringify(badTypeMeta), 'utf8');
    assert.throws(
      () => prepareGeneration({ metadata: badTypePath, out: SCRATCH_DIR }),
      /Incompatible column mapping for EvalResult\.LatencyMs/,
    );
  } finally {
    rmSync(SCRATCH_DIR, { recursive: true, force: true });
  }
});
