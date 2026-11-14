# Copilot × IQ Evaluation Harness (`cfeval`)

Reproducible evaluation harness for **Microsoft 365 Copilot Chat**, **Fabric IQ** semantic models, **Work IQ** workplace grounding, **Fabric IQ MCP**, and **imported transcripts**.

`cfeval` sends versioned golden test sets (`version: 2`), grades answers with deterministic unit-aware and structured assertions (`scalar`, `ranked_list`, `set`, `table`, `record`, `direction`, `citation_only`, `abstention`), correlates Fabric Workspace Monitoring (`SemanticModelLogs`) engine DAX queries, computes multi-trial reliability (`pass@1`, `pass^k`, Wilson 95% CI, exact paired McNemar `p`), and emits HTML/JUnit/JSONL scorecards plus idempotent Fabric Eventhouse telemetry.

![Simplified architecture](docs/architecture/simplified-architecture.svg)

> Community accelerator released under the [MIT License](LICENSE). Provided as-is; not an official Microsoft product. Review [Platform Status](docs/reference/platform-status.md), [Cost & Limits](docs/get-started/cost-and-limits.md), [Threat Model](docs/responsible-use/threat-model.md), and [Transparency FAQ](TRANSPARENCY_FAQ.md) before running in a live demo tenant.

## 60-Second Offline Quickstart (Zero Cloud Credentials)

```bash
python -m pip install -e ".[dev]"

# 1. Run untuned vs tuned simulated baselines on the 8-case Contoso smoke suite
python -m cfeval run --mock --profile untuned --golden data/golden/contoso-smoke.yaml --run-id demo-untuned --no-publish
python -m cfeval run --mock --profile tuned   --golden data/golden/contoso-smoke.yaml --run-id demo-tuned   --no-publish

# 2. Compare paired runs (discordant pairs, Wilson 95% CIs, exact McNemar p-value) & render HTML report
python -m cfeval compare --baseline runs/demo-untuned --candidate runs/demo-tuned
python -m cfeval report --run-dir runs/demo-tuned --out runs/demo-tuned/report.html

# 3. Score a pre-captured JSONL transcript offline
python -m cfeval run --target transcript-import --transcript samples/contoso/transcript_sample.jsonl --golden data/golden/contoso-smoke.yaml --no-publish
```

## How This Relates to Microsoft's Evaluation Tools

| Tool / Capability | Primary Role | How `cfeval` Fits In |
|---|---|---|
| **`@microsoft/m365-copilot-eval` & Work IQ Dev Tools** *(Preview)* | Node CLI (`runevals`) batch-running M365 Copilot prompts with built-in AI prose/citation graders. | Round-trips via `cfeval golden export --format m365-copilot-eval` and `cfeval run --target import --from-m365-copilot-eval` to add unit-aware numeric tolerances, decoy gates, and DAX correlation ([guide](docs/how-to/use-with-the-evaluations-cli.md)). |
| **Fabric Data Agent Evaluation SDK** *(Preview)* | Notebook SDK (`fabric-data-agent-sdk`) evaluating standalone Fabric data agents on `F2+` capacity. | Evaluates cross-model **M365 Copilot Chat + Fabric IQ** routing, correlates `SemanticModelLogs` DAX, and optionally wraps `fabric-data-agent` as a `Target`. |
| **Microsoft Foundry Evaluations** *(GA / Custom Code Preview)* | Cloud evaluation portal, agent evaluators, and LLM judges. | Exports pure-stdlib (<256 KB) custom code scorers and optional calibrated Layer 5 judge workflows (`--option foundry`). |

## Platform Status (Last Verified: 2026-11-13)

| Dependency / Surface | Status | Evidence & Constraints |
|---|---|---|
| **Fabric IQ in M365 Copilot Chat** & **Power BI Copilot Q&A** | **GA** | Enforces user RLS/OLS; requires M365 Copilot licence + per-model Copilot enabled; verified answers can be bypassed via Fabric IQ. |
| **Fabric Workspace Monitoring (`SemanticModelLogs`) & Eventhouse** | **GA** | Enables `engine+citations` DAX verification; consumes Fabric capacity CU; 30-day default log retention. |
| **M365 Copilot Chat API (`/beta/copilot/conversations`)** | **Preview** | Delegated user auth only (broad Graph read scopes — **use a dedicated synthetic test account**, never an employee mailbox). |
| **Fabric IQ MCP Server** & **`@microsoft/m365-copilot-eval` (v2)** | **Preview** | Delegated `Item.Read.All` / `Item.Execute.All` (`tool_call` tier); CLI interop pinned to v2 schema `2.0`. |
| **Foundry Custom Code Evaluators** & **Fabric Apps (`app/`)** | **Preview** | Optional extras; core CLI, local HTML reports (`cfeval report`), and standalone Vite preview work 100% offline. |

Full citation matrix (`R1`–`R17`): [Platform Status](docs/reference/platform-status.md). Vocabulary mapping: [Glossary](docs/reference/glossary.md).

## Documentation Map

* **Get Started**: [Prerequisites](docs/get-started/prerequisites.md) · [Offline Quickstart](docs/get-started/quickstart-offline.md) · [First Live Run](docs/get-started/first-live-run.md) · [Cost & Limits](docs/get-started/cost-and-limits.md) · [Transcript Import](docs/get-started/quickstart-transcript-import.md)
* **Concepts**: [How It Works](docs/concepts/how-it-works.md) · [Evidence & Verdicts](docs/concepts/evidence-and-verdicts.md) · [Metrics & Statistics](docs/concepts/metrics.md) · [Limitations](docs/concepts/limitations.md)
* **How-To Guides**: [Author a Golden Set](docs/how-to/author-a-golden-set.md) · [Capture Engine DAX](docs/how-to/capture-dax.md) · [Calibrate the Judge](docs/how-to/calibrate-the-judge.md) · [Compare Runs & Gate CI](docs/how-to/compare-runs-and-gate-ci.md) · [Use with Evaluations CLI](docs/how-to/use-with-the-evaluations-cli.md) · [Add a Target](docs/how-to/add-a-target.md) · [Run a Live Demo](docs/how-to/run-a-live-demo.md) · [Deploy Scorecard App](docs/how-to/deploy-the-scorecard-app.md) · [Troubleshoot](docs/how-to/troubleshoot.md)
* **Reference**: [Reference Index](docs/reference/README.md) · [CLI](docs/reference/cli.md) · [Exit Codes](docs/reference/exit-codes.md) · [Configuration](docs/reference/configuration.md) · [Golden Schema](docs/reference/golden-schema.md) · [Telemetry Schema](docs/reference/telemetry-schema.md) · [Platform Status](docs/reference/platform-status.md) · [Glossary](docs/reference/glossary.md)
* **Responsible Use & Governance**: [Threat Model](docs/responsible-use/threat-model.md) · [Transparency FAQ](TRANSPARENCY_FAQ.md) · [ADRs](docs/decisions/0004-eventhouse-telemetry-store.md) · [Readiness Checklist](docs/validation/public-readiness-checklist.md) · [Security](SECURITY.md) · [Support](SUPPORT.md) · [Contributing](CONTRIBUTING.md)
* **Synthetic Sample Kits**: [`data/golden/`](data/golden/README.md) (`42` Fabric IQ + `22` Work IQ cases) · [`samples/contoso/`](samples/contoso/README.md) · [`samples/work-iq/`](samples/work-iq/README.md) · [`app/`](app/README.md)

## Trademarks

Microsoft, Microsoft 365, Copilot, Microsoft Fabric, Power BI, and Azure are trademarks of the Microsoft group of companies. Contoso (`@contoso.com`) is a fictional organization used exclusively for synthetic evaluation data.

