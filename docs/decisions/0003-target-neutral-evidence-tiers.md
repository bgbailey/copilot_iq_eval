# ADR 0003: Target-Neutral Routing Evidence Tiers

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Originally, the harness assumed every evaluation run targeted Microsoft 365 Copilot Chat backed by Fabric Workspace Monitoring (`SemanticModelLogs`). Expanding `cfeval` to support **Work IQ** (M365 documents, emails, meeting recaps), **MCP tool servers**, **Fabric Data Agents**, **chat-only tenants without Workspace Monitoring**, and **offline imported transcripts** meant that backend DAX logs are available for some surfaces and structurally non-existent for others.

Treating missing DAX logs as a blanket `FAIL` blocked legitimate `work-iq` and `transcript-import` evaluations; conversely, treating a chat citation link as equivalent to `SemanticModelLogs` overstated routing certainty.

## Decision

Introduce an explicit four-level **`routing_evidence_tier`** recorded on every scored result:

- `engine+citations` — Correlated backend engine query telemetry (`SemanticModelLogs`) + user-facing citations.
- `tool_call` — Verified in-process MCP / agent tool invocation payloads.
- `citations-only` — User-facing attributions / links without engine query telemetry.
- `none` — Plain answer text only.

Gate evaluation respects `routing_evidence_tier`: `model` gates requiring engine telemetry evaluate normally under `engine+citations`, mark `not_applicable` under `citations-only` / `none` by default, and fail explicitly when the operator passes `--strict-evidence`.

## Consequences

- **Positive:** Users can adopt `cfeval` incrementally—starting offline with `transcript-import` (`citations-only`), moving to live `copilot-chat` (`citations-only`), and enabling Workspace Monitoring (`engine+citations`) for certified BI models—while scorecards always state the exact strength of routing proof.
- **Negative / Trade-off:** Reports and downstream KQL queries must display `routing_evidence_tier` prominently so stakeholders do not compare `citations-only` and `engine+citations` pass rates without noting the tier difference.
