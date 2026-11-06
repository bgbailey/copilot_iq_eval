// Re-exports the connector schema in rayfin/connectors/evals/schema.ts.
// scripts/apply-overlay.mjs rewrites this path for your project; this default points at the
// reference copy in app/connectors/evals so the standalone preview and type checks work.
export { connectorConfig } from '../../../connectors/evals/schema';
export type { EvalsSchema } from '../../../connectors/evals/schema';
