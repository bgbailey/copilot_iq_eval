// Display formatting. Pure: unit-tested with node --test.

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return `${(value * 100).toFixed(digits)}%`;
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '–';
  if (Math.abs(ms) < 1000) return `${Math.round(ms)} ms`;
  if (Math.abs(ms) < 120000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60000).toFixed(1)} min`;
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return value.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "Nov 4, 14:05" in the viewer's local time. */
export function dateTime(d: Date | null | undefined): string {
  if (!d) return '–';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${hh}:${mm}`;
}

export function shortDate(d: Date | null | undefined): string {
  if (!d) return '–';
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

export function truncate(text: string | null | undefined, n: number): string {
  const t = text ?? '';
  return t.length <= n ? t : `${t.slice(0, n - 1)}…`;
}

export function backendLabel(backend: string | null | undefined): string {
  if (backend === 'fabric-native') return 'Option 1 · Fabric-native';
  if (backend === 'foundry') return 'Option 2 · Foundry Evaluations';
  return backend ?? '–';
}

/** Drop markdown code fences around a JSON reply for display. */
export function stripFences(text: string | null | undefined): string {
  return (text ?? '').replace(/^```[a-z]*\s*$/gim, '').trim();
}
