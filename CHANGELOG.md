# Changelog

All notable changes to the **Copilot x IQ Evaluation Accelerator** (`cfeval`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-13

### Added

- **Target-neutral v2 architecture (`cfeval.targets`)**: Pluggable target protocol and registry supporting
  `copilot-chat` (Microsoft Graph Copilot Chat API and offline simulator), `transcript-import` (CSV/JSONL transcripts
  and Microsoft 365 Copilot Evaluations CLI interoperability), `mcp-agent` (Fabric IQ MCP control-arm reference agent
  with verified `tool_call` routing evidence), and optional `fabric-data-agent` execution.
- **Golden suite schema v2 & Work IQ starter pack**: JSON Schema validation (`schemas/golden.schema.json`), `golden-lint`
  diagnostics, expanded `data/golden/contoso.yaml` analytics suite, `data/golden/contoso-work.yaml` enterprise-search
  document suite, multi-persona row-level security (`config/personas.yaml`), and `categorical`, `set`, `facts`,
  `refusal`, and `clarification` expectation scorers.
- **Value extraction v2 & grader corpus**: Ordered extraction cascade (`first` deterministic parser, `explicit`
  verified follow-up value, and `llm_extract` span verification) with locale-aware parsing, ratio-to-percent matching,
  configurable `display_tol`, and a labelled grader corpus asserting zero false passes.
- **Configurable gate policies (`config/gates.yaml`)**: Explicit `with_engine_evidence` (`value`, `artifact`, `model`)
  and `without_engine_evidence` (`value`, `artifact` with `routing_evidence=citations-only`) policies, release gates,
  and JUnit XML / Markdown CI summaries.
- **Statistical rigor & judge calibration**: Standard-library `cfeval.stats` and matching TypeScript scorecard helpers
  for `pass@k`, `pass^k`, Wilson 95% confidence intervals, exact two-sided McNemar paired regression testing
  (`cfeval compare`), and multi-pass judge calibration (`calibrate-judge`) reporting Cohen's kappa, recall, and precision.
- **Standalone reporting & observability**: Self-contained offline HTML reports (`cfeval report`), deterministic `RowId`
  idempotent telemetry across all five tables, and optional OpenTelemetry GenAI span export.
- **Scorecard app tests & duplicate guard**: Native `node:test` suites (`metrics`, `format`, `dedupe`, `entities`),
  defensive in-app row deduplication, and five-table `app/scripts/dedupe-sample.mjs --check` verification.
- **Supply-chain & developer experience**: SHA-pinned GitHub Actions workflows for cross-OS CI (`ci.yml`), CodeQL
  analysis (`codeql.yml`), and provenance-attested package releases (`release.yml`), plus `.devcontainer`, `Makefile`,
  `.pre-commit-config.yaml`, and Contributor Covenant 2.1 governance docs.

### Changed

- **Scorecard latency semantics**: Removed additive residual calculations so answer round-trip latency, follow-up
  latency, and overlapping SemanticModelLogs DAX durations are always reported as independent measurements.
- **Scorecard labels & Node compatibility**: Clarified backend, target, and routing-evidence labels in the React
  scorecard and relaxed standalone preview engine support to `>=22.0.0`.
- **Architecture assets**: Replaced the multi-megabyte architecture exports with an accessible `14 KB` vector
  `docs/architecture/simplified-architecture.svg` (`role="img"`, `<title>`, `<desc>`) and `< 120 KB` raster `.png`.

### Fixed

- Prevented duplicate sample or re-published Eventhouse rows across `EvalRun`, `EvalQuestion`, `EvalResult`,
  `FabricIqQuery`, and `EvalEvent` from inflating or skewing scorecard KPIs and stage timing distributions.

## [0.1.0] - 2026-11-06

### Added

- Initial evaluation accelerator for Microsoft 365 Copilot Chat over Fabric IQ / Power BI semantic models.
- Deterministic value, cited-artifact, and semantic-model routing gates paired with optional judge and Azure AI Foundry
  evaluation backends.
- Fabric workspace monitoring (`SemanticModelLogs`) DAX correlation, KQL setup scripts, Eventhouse ingestion, and
  offline simulated tenant (`--mock`).
- Fabric Apps (Rayfin) React scorecard overlay, connector entity code generator, and standalone sample-data preview.
