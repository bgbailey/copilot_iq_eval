# Architecture Guide (Moved)

Documentation follows the Diátaxis layout. Start with the canonical concept and reference pages:

- **[How It Works](concepts/how-it-works.md)** — Five-stage evaluation pipeline (`Target`, `EvidenceSource`, `Scorer`), architecture diagram, and unified source-type evidence matrix.
- **[Evidence Tiers and Verdicts](concepts/evidence-and-verdicts.md)** — What `engine+citations`, `tool_call`, `citations-only`, and `unverified` prove, `CorrelationConfidence` levels, and why `INCONCLUSIVE` / `ERROR` never become `PASS`.
- **[Known Limitations](concepts/limitations.md)** — `/beta` Chat API constraints, time-window correlation under concurrent load, Workspace Monitoring lag, and verified-answers caveats.
- **[Architecture Overview (Detailed)](concepts/architecture.md)** and **[Surfaces & Evidence](concepts/surfaces-and-evidence.md)** — Deep-dive component notes.
- **[Telemetry Schema Reference](reference/telemetry-schema.md)** — Machine-generated column definitions (`src/cfeval/schema.py`).
- **[ADR 0001: Two Backends, Not Two Harnesses](decisions/0001-two-backends-not-two-harnesses.md)**, **[ADR 0002: Deterministic-First Scoring](decisions/0002-deterministic-first-scoring.md)**, **[ADR 0003: Target-Neutral Evidence Tiers](decisions/0003-target-neutral-evidence-tiers.md)**, and **[ADR 0004: Eventhouse Telemetry Store](decisions/0004-eventhouse-telemetry-store.md)** — Design trade-offs and `RowId` idempotency.

