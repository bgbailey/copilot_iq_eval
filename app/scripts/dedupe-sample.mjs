#!/usr/bin/env node
// Reproducibly remove only exact duplicate sample DAX/event records. Never reads a live source.
//   node app/scripts/dedupe-sample.mjs [--file <sample.json>] [--check]
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export function dedupeSample(sample) {
  const tables = { ...sample.tables };
  const removed = {};
  for (const name of ['FabricIqQuery', 'EvalEvent']) {
    const seen = new Set();
    const rows = tables[name] ?? [];
    tables[name] = rows.filter((row) => {
      const key = JSON.stringify(Object.entries(row).sort(([a], [b]) => a.localeCompare(b)));
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    removed[name] = rows.length - tables[name].length;
  }
  return { data: { ...sample, tables }, removed };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  const index = args.indexOf('--file');
  const file = index >= 0 ? args[index + 1] : fileURLToPath(new URL('../overlay/public/sample-data/evals.json', import.meta.url));
  const { data, removed } = dedupeSample(JSON.parse(readFileSync(file, 'utf8')));
  const count = Object.values(removed).reduce((a, b) => a + b, 0);
  if (args.includes('--check')) process.exitCode = count ? 1 : 0;
  else if (count) writeFileSync(file, `${JSON.stringify(data, null, 1)}\n`);
  console.log(`${args.includes('--check') ? 'Duplicate rows' : 'Removed duplicate rows'}: ${JSON.stringify(removed)}`);
}
