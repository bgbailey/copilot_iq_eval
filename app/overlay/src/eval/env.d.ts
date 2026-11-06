// Scorecard-specific setting (the Rayfin template declares its own VITE_* variables).
interface ImportMetaEnv {
  /** auto (default) | live | sample */
  readonly VITE_EVAL_DATA?: string;
}
