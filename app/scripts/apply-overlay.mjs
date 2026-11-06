#!/usr/bin/env node
// Apply the evaluation scorecard to a Rayfin (Fabric Apps) project created with
// `npm create @microsoft/rayfin@latest`. Copies src/eval and the sample data, points
// src/eval/connectorSchema.ts at rayfin/connectors/<connector>/schema.ts, replaces App.tsx
// (the original is kept as App.template.tsx). Metadata and app columns must pass preflight
// before any project file is written.
//
//   node <accelerator>/app/scripts/apply-overlay.mjs --project <your Rayfin app> [--connector evals] [--keep-app]
import { cpSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { prepareGeneration, writeGeneration } from './generate-entities.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const OVERLAY = resolve(HERE, '..', 'overlay');

export function findFrontend(project) {
  for (const candidate of [join(project, 'packages', 'frontend'), join(project, 'frontend'), project]) {
    if (existsSync(join(candidate, 'src'))) return candidate;
  }
  throw new Error(`No frontend src/ folder found under ${project}`);
}

export function apply({ project, connector = 'evals', keepApp = false, log = console.log }) {
  const root = resolve(project);
  if (connector !== 'evals') throw new Error('The scorecard client uses connector name evals. Add the connector with --name evals.');
  if (!existsSync(join(root, 'rayfin', 'rayfin.yml'))) throw new Error(`${root} has no rayfin/rayfin.yml: is this a Rayfin project?`);
  const frontend = findFrontend(root);
  const src = join(frontend, 'src');
  if (!existsSync(join(src, 'App.tsx'))) throw new Error(`No React App.tsx found in ${src}; use the actual React scaffold entry before applying the overlay.`);
  const plan = prepareGeneration({ project: root, connector });
  cpSync(join(OVERLAY, 'src', 'eval'), join(src, 'eval'), { recursive: true });
  mkdirSync(join(frontend, 'public', 'sample-data'), { recursive: true });
  cpSync(join(OVERLAY, 'public', 'sample-data'), join(frontend, 'public', 'sample-data'), { recursive: true });
  let rel = relative(join(src, 'eval'), join(root, 'rayfin', 'connectors', connector, 'schema')).split(sep).join('/');
  if (!rel.startsWith('.')) rel = `./${rel}`;
  writeFileSync(join(src, 'eval', 'connectorSchema.ts'), [
    `// Re-exports the connector schema generated in rayfin/connectors/${connector}/schema.ts (written by apply-overlay.mjs).`,
    `export { connectorConfig } from '${rel}';`,
    `export type { ${connector.charAt(0).toUpperCase()}${connector.slice(1)}Schema as EvalsSchema } from '${rel}';`,
    '',
  ].join('\n'));
  if (!keepApp) {
    const app = join(src, 'App.tsx');
    const backup = join(src, 'App.template.tsx');
    if (existsSync(app) && !existsSync(backup) && !readFileSync(app, 'utf8').includes('./eval/EvalApp')) renameSync(app, backup);
    cpSync(join(OVERLAY, 'src', 'App.tsx'), app);
  }
  log(`Scorecard copied into ${relative(process.cwd(), src) || src}`);
  writeGeneration(plan, log);
  return { frontend, schemaImport: rel };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const argv = process.argv.slice(2);
  const get = (name) => {
    const i = argv.indexOf(`--${name}`);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  try {
    apply({ project: get('project') ?? process.cwd(), connector: get('connector') ?? 'evals', keepApp: argv.includes('--keep-app') });
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }
}
