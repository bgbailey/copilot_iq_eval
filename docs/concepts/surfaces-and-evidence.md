# Surfaces and Routing Evidence Tiers

Different Copilot and agent surfaces expose different levels of grounding telemetry. `cfeval` models both dimensions explicitly:

- **`surface`** — The user-facing grounding domain (`fabric-iq`, `work-iq`, `mcp`, `generic`).
- **`routing_evidence_tier`** — How strongly the harness verified which backend artifact or semantic model produced the answer.

## Supported Evaluation Targets

| Target (`--target`) | Typical `surface` | How Answers Are Collected | Primary Use Case |
|---|---|---|---|
| `copilot-chat` | `fabric-iq` or `work-iq` | Microsoft 365 Copilot Chat API (`beta/copilot/conversations`) under a delegated test user | End-to-end M365 Copilot grounding against Power BI reports, semantic models, OneDrive, SharePoint, Teams, and Exchange. |
| `fabric-data-agent` | `fabric-iq` | Fabric Data Agent REST query endpoint | Direct semantic model / lakehouse Q&A evaluation prior to M365 chat orchestration. |
| `mcp-agent` | `mcp` | OpenAI-compatible chat completions loop connected to an MCP tool server | Evaluating custom BI or enterprise MCP servers (`tool_call` inspection). |
| `transcript-import` | Any | Local `.jsonl` or `.csv` file of pre-recorded Q&A turns | Offline scoring of pilot logs, human captures, or third-party assistants. |
| `--mock` | `fabric-iq` / `work-iq` | Deterministic local simulator (`tuned` and `untuned` profiles) | Zero-credential onboarding, CI smoke tests, and notebook walkthroughs. |

## Routing Evidence Tiers

| Tier | Collectors / Targets | Evidence Captured | Gate Behavior |
|---|---|---|---|
| **`engine+citations`** | `copilot-chat` + `kql`, `fabric-data-agent` + `kql`, `--mock` | User-visible report/model citations **plus** correlated `SemanticModelLogs` DAX queries (`DatasetId`, `DatasetName`, `QueryText`, `DurationMs`). | Full `value`, `artifact`, and `model` (including decoy-model avoidance) gates enforced. |
| **`tool_call`** | `mcp-agent` | Structured MCP tool names, JSON arguments, and tool outputs captured directly in-process. | `value` and `artifact` / tool-routing checks enforced from verified tool invocations. |
| **`citations-only`** | `copilot-chat` (`none`), `work-iq`, `transcript-import` (with citations) | Graph/chat attribution metadata (`title`, `webUrl`, `attributionType`) without independent engine query logs. | `value` and `artifact` gates enforced; engine-only `model` checks record `not_applicable` unless `--strict-evidence` is enabled. |
| **`none`** | `transcript-import` (plain text without citations) | Raw answer text only. | `value` (and `abstention`) gates enforced; `artifact` and `model` gates record `not_applicable` unless required. |

## Why This Distinction Matters

A conversational assistant can cite a certified Power BI report link from recent context while quoting a cached or misread figure—or conversely query a certified semantic model without rendering a clickable report link. Recording `routing_evidence_tier` on every `EvalResult` prevents teams from over-interpreting `citations-only` runs as proof of DAX execution while still enabling rapid `citations-only` iteration when Workspace Monitoring is unavailable.
