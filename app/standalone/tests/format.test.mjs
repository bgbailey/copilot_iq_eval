import assert from 'node:assert/strict';
import test from 'node:test';

import {
  backendLabel,
  dateTime,
  duration,
  num,
  pct,
  routingEvidenceLabel,
  shortDate,
  stripFences,
  targetLabel,
  truncate,
} from '../../overlay/src/eval/format.ts';

test('backendLabel maps built-in and Foundry backends cleanly', () => {
  assert.equal(backendLabel('fabric-native'), 'Built-in checks (fabric-native)');
  assert.equal(backendLabel('foundry'), 'Azure AI Foundry evaluators');
  assert.equal(backendLabel(null), '–');
  assert.equal(backendLabel(undefined), '–');
  assert.equal(backendLabel(''), '–');
  assert.equal(backendLabel('custom-grader'), 'custom-grader');
});

test('targetLabel maps pluggable target identifiers and handles missing values', () => {
  assert.equal(targetLabel('copilot-chat'), 'Microsoft 365 Copilot Chat');
  assert.equal(targetLabel('m365-copilot-chat-graph'), 'Microsoft 365 Copilot Chat');
  assert.equal(targetLabel('copilot-chat-api'), 'Microsoft 365 Copilot Chat');
  assert.equal(targetLabel('simulated'), 'Simulated tenant');
  assert.equal(targetLabel('transcript-import'), 'Imported transcript');
  assert.equal(targetLabel('import'), 'Imported transcript');
  assert.equal(targetLabel('mcp-agent'), 'Fabric IQ MCP agent');
  assert.equal(targetLabel('fabric-iq-mcp-reference'), 'Fabric IQ MCP agent');
  assert.equal(targetLabel('fabric-data-agent'), 'Fabric Data Agent');
  assert.equal(targetLabel(null), '–');
  assert.equal(targetLabel(undefined), '–');
  assert.equal(targetLabel(''), '–');
  assert.equal(targetLabel('custom-agent'), 'custom-agent');
});

test('routingEvidenceLabel formats all four routing evidence tiers', () => {
  assert.equal(routingEvidenceLabel('engine+citations'), 'Engine + Citations');
  assert.equal(routingEvidenceLabel('citations-only'), 'Citations only');
  assert.equal(routingEvidenceLabel('tool_call'), 'Verified Tool Call');
  assert.equal(routingEvidenceLabel('unverified'), 'Unverified');
  assert.equal(routingEvidenceLabel(null), '–');
  assert.equal(routingEvidenceLabel(undefined), '–');
  assert.equal(routingEvidenceLabel(''), '–');
  assert.equal(routingEvidenceLabel('custom-tier'), 'custom-tier');
});

test('numeric, duration, date, and text helpers handle nulls and boundaries', () => {
  assert.equal(pct(null), '–');
  assert.equal(pct(Number.NaN), '–');
  assert.equal(pct(0.875, 1), '87.5%');
  assert.equal(pct(1, 0), '100%');

  assert.equal(duration(null), '–');
  assert.equal(duration(450.4), '450 ms');
  assert.equal(duration(12500), '12.5 s');
  assert.equal(duration(180000), '3.0 min');

  assert.equal(num(null), '–');
  assert.equal(num(12840000), '12,840,000');

  const d = new Date(2026, 10, 4, 14, 5); // local Nov 4, 14:05
  assert.equal(dateTime(d), 'Nov 4, 14:05');
  assert.equal(shortDate(d), 'Nov 4');
  assert.equal(dateTime(null), '–');
  assert.equal(shortDate(undefined), '–');

  assert.equal(truncate('short', 10), 'short');
  assert.equal(truncate('abcdefghij', 6), 'abcde…');
  assert.equal(stripFences('```json\n{"value": 42}\n```'), '{"value": 42}');
});
