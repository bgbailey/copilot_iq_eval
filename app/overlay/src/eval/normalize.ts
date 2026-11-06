// Turns raw rows (sample JSON with SQL column names, or connector rows with entity property
// names) into typed rows. Pure: no imports at runtime, so it is unit-tested with node --test.
import type { ColumnMap } from './generated/contract';

export type RawRow = Record<string, unknown>;

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function toDate(value: unknown): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  let text = String(value);
  // SQL endpoints can return datetime2 without a zone: the telemetry is UTC.
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text)) text = text.replace(' ', 'T') + 'Z';
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : d;
}

function toText(value: unknown, dynamic: boolean): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value;
  return dynamic ? JSON.stringify(value) : String(value);
}

/** Normalize rows for one entity. Accepts either SQL column names or entity property names. */
export function normalizeRows<T>(rows: readonly RawRow[], columns: ColumnMap): T[] {
  const entries = Object.entries(columns);
  return rows.map((raw) => {
    const out: Record<string, unknown> = {};
    for (const [prop, [column, type]] of entries) {
      const value = prop in raw ? raw[prop] : raw[column];
      if (type === 'int' || type === 'real') out[prop] = toNumber(value);
      else if (type === 'datetime') out[prop] = toDate(value);
      else out[prop] = toText(value, type === 'dynamic');
    }
    return out as T;
  });
}
