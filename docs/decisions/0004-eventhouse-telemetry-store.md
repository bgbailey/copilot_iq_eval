# ADR 0004: Dual Local JSONL and Fabric Eventhouse Telemetry Store with Deterministic `RowId` Idempotency

* **Status**: Accepted
* **Date**: 2026-11-13
* **Deciders**: `cfeval` maintainers

## Context

`cfeval` must serve two operating environments equally well:

1. **Zero-cloud local & CI workflows**: Contributors, GitHub Actions gates, and air-gapped reviewers need reproducible, inspectable artifacts (`cfeval run --mock`, `cfeval rescore`, `cfeval compare`, `cfeval report`, `cfeval gate`) with zero Fabric capacity or Kusto dependencies.
2. **Enterprise multi-run scorecards**: Analytics teams running recurring live benchmarks in a demo or pre-production Fabric tenant need durable cross-run trends, paired comparisons, DAX drill-downs, and OneLake compatibility without standing up custom PostgreSQL or Cosmos DB infrastructure.

At the same time, Kusto / Fabric Eventhouse ingestion is **append-oriented**: network retries, `cfeval publish` replays, or `cfeval rescore` updates will append duplicate records unless deduplicated deterministically. Furthermore, Fabric Workspace Monitoring retains raw `SemanticModelLogs` for only **30 days** by default (`R9`), so engine evidence attached to historic milestone runs would disappear unless copied into an evaluation-owned table.

## Decision

1. **Single Python schema source (`src/cfeval/schema.py`, `SCHEMA_VERSION = 2`)**:
   * Define all seven telemetry tables (`EvalRun`, `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalScore`, `EvalResult`, `EvalEvent`) once in Python.
   * Generate KQL DDL (`cfeval kql --out kql/setup.kql`), TypeScript scorecard contracts (`tools/gen_app_contract.py`), connector metadata (`app/connectors/evals/metadata.example.json`), and Markdown reference docs (`tools/gen_reference_docs.py`) directly from `src/cfeval/schema.py`, enforced by CI drift checks.
   * Restrict future schema changes to **additive columns only** so existing OneLake Parquet shortcuts and historical JSONL directories remain readable without destructive migrations.
2. **Local JSONL-first execution (`runs/<run_id>/`)**:
   * Every `cfeval run` writes local run artifacts (`EvalRun.jsonl`, `EvalQuestion.jsonl`, `EvalAsk.jsonl`, `FabricIqQuery.jsonl`, `EvalScore.jsonl`, `EvalResult.jsonl`, `EvalEvent.jsonl`, and `summary.json`) first.
   * Publishing to Fabric Eventhouse (`cfeval publish` or inline during live `cfeval run`) is a clean projection of those local files; `--no-publish` skips Kusto entirely with zero behavioral difference in scoring or gating.
3. **Deterministic `RowId` + KQL `arg_max` deduplication**:
   * Every row carries a deterministic SHA-256 `RowId` computed from `ROW_ID_KEYS` (`src/cfeval/schema.py`).
   * Companion KQL functions in `src/cfeval/kql/functions.kql` deduplicate by `RowId` (`summarize arg_max(..., *) by RowId`), and `app/scripts/dedupe-sample.mjs --check` enforces uniqueness in bundled sample JSON.
   * Re-running `cfeval publish` or publishing rescored verdicts after delayed KQL trace arrival is **100% idempotent** at query time without requiring Kusto extent purges or transactional deletes.
4. **Copy correlated `SemanticModelLogs` slices into `FabricIqQuery`**:
   * Only the filtered, turn-correlated `QueryEnd` DAX records for evaluated turns are persisted in `FabricIqQuery`, preserving audit evidence past Workspace Monitoring's 30-day window while keeping storage under a few megabytes per hundred runs.

## Consequences

* **Positive**: Offline workflows (`--mock`, `transcript-import`, `rescore`, `report`, `gate`) require zero cloud services; Eventhouse ingestion retries never double-count pass rates; schema drift between Python, KQL, TypeScript, and docs fails CI immediately.
* **Trade-offs**: Consumers querying Eventhouse directly should always query the `v_Eval*` functions rather than raw base tables so re-published `RowId` revisions are deduplicated automatically.

## Related Documents

* [Telemetry Schema Reference](../reference/telemetry-schema.md)
* [ADR 0001: Two Backends, Not Two Harnesses](./0001-two-backends-not-two-harnesses.md)
* [ADR 0002: Deterministic-First Scoring](./0002-deterministic-first-scoring.md)
* [ADR 0003: Target-Neutral Evidence Tiers](./0003-target-neutral-evidence-tiers.md)
* [Cost and Operational Limits](../get-started/cost-and-limits.md)
