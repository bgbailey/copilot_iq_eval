// Small, dependency-free guards shared by the shell and its offline regression.
export type DataMode = 'auto' | 'live' | 'sample';
export type DataSource = 'live' | 'sample';

export function allowedSource(mode: DataMode, source: DataSource): boolean {
  return mode === 'auto' || mode === source;
}

/** Invalidate a load as soon as its source/window changes, not just when another load finishes. */
export function createLoadGate() {
  let revision = 0;
  return {
    start: () => ++revision,
    invalidate: () => { revision += 1; },
    isCurrent: (request: number) => request === revision,
  };
}
