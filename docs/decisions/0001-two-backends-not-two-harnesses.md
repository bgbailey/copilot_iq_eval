# ADR 0001: Two Scoring Backends, Not Two Harnesses

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Teams adopting `cfeval` fall into two operational camps:

1. **Fabric / Python-first teams** who want zero Azure AI Foundry dependencies, deterministic local checks, instant offline CI execution, and direct Eventhouse / HTML reporting (**Option 1**).
2. **Foundry-standardized AI platform teams** who govern all enterprise AI evaluations through **Azure AI Foundry Evaluations** (`azure-ai-evaluation` / portal run comparison, built-in quality evaluators, and centralized governance) (**Option 2**).

Maintaining two separate orchestration harnesses—one for local Python and one for Foundry—would duplicate target execution (`copilot-chat`, `mcp-agent`, `transcript-import`), Workspace Monitoring DAX correlation, and Eventhouse telemetry schemas, Inevitably causing metric definitions to drift.

## Decision

Keep **one target-collection harness** (`EvalHarness` producing `EvalAsk` + `FabricIqQuery` JSONL) and model Option 1 and Option 2 strictly as **pluggable scoring backends** writing to the exact same normalized `EvalScore` and `EvalResult` tables (`Option = "option1"` vs `"option2"`):

- Because Azure AI Foundry cannot directly drive delegated Microsoft 365 Copilot Chat sessions or poll Fabric Workspace Monitoring KQL logs, `EvalHarness` always executes capture once.
- Both Option 1 and Option 2 consume the identical captured JSONL (`cfeval rescore --option 2`), guaranteeing apples-to-apples comparison on the exact same turns without double-billing or stochastic re-asking.

## Consequences

- **Positive:** Zero duplicate Copilot Chat turns when comparing Option 1 and Option 2 (`--option both`); offline users install minimal dependencies without `azure-ai-evaluation`; Eventhouse and HTML reports render both options with one unified schema.
- **Negative / Trade-off:** Option 2 relies on Azure AI Foundry preview evaluation APIs; when preview service runs fail or time out, `cfeval` records the explicit Foundry error rather than silently substituting Option 1 local grades.
