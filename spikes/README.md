# Phase 0 spikes

Short, standalone scripts that answer the open questions in PLAN §14 **before** any harness code depends on the answer. Each spike ends in an ADR in [`docs/decisions/`](../docs/decisions/README.md), and confirmed contracts move into [`config/contracts.yaml`](../config/contracts.yaml).

| Spike | Question | Script | ADR |
|---|---|---|---|
| S1 | Does the Copilot Chat API trigger Fabric IQ / Power BI answering? | [`s1_chat_api.py`](s1_chat_api.py) | ADR-001 |
| S2 | What does a Copilot-issued query look like in the engine log, and how fast is it ingested? | [`s2_engine_logs.py`](s2_engine_logs.py) | ADR-002 |
| S3 | Can the Agent Evaluations CLI run headless as different personas, and what does its JSON contain? | [`s3_cli_probe.sh`](s3_cli_probe.sh) / [`.ps1`](s3_cli_probe.ps1) | ADR-003 |
| S4 | Can Copilot Studio evaluation test an agent that uses the Fabric IQ MCP or data agent tool? | Manual | ADR-004 |
| S5 | Do Purview audit and Interaction Export show Fabric usage per access point? | Manual | ADR-005 |
| S6 | Fabric IQ MCP from our own client: what are the exact tool argument names? | [`s6_fabriciq_mcp.py`](s6_fabriciq_mcp.py) | ADR-006 |
| S7 | Foundry path only: does our Foundry project run the evaluation design end to end (errors, version pinning, thresholds, cost)? | [`s7_foundry_eval.py`](s7_foundry_eval.py) | ADR-008 |
| S8 | Which surfaces answer joint Work IQ + Fabric IQ questions, with both sources cited, and how long until seeded documents are found? | [`s8_workiq_grounding.py`](s8_workiq_grounding.py) | ADR-011 |

## Before you run them

1. Deploy the environment ([docs/deployment.md](../docs/deployment.md)): the spikes need the personas, the semantic models and, for S8, the seeded documents.
2. Install their dependencies: `uv sync --extra setup --extra spikes`.
3. Fill in `config/settings.toml`; the spikes read it like the harness does.

Personas sign in with MSAL device code through the `copilot-eval-public` app, once each, with a token cache per persona under `.cache/` (gitignored). S2 and S7 sign in as you, through azure-identity (`az login`).

## Run order

| Order | Spike | Command | Notes |
|---|---|---|---|
| 1 | S6 | `uv run python spikes/s6_fabriciq_mcp.py --persona exec` | Lists the tools and their argument names; add `--call` and `--arguments` for one call |
| 2 | S1 | `uv run python spikes/s1_chat_api.py --case REV-001` | Prints the answer, the attributions, whether the expected value is stated, and the window for S2 |
| 3 | S2 | `uv run python spikes/s2_engine_logs.py --t0 ... --t1 ... --user ...` | Use the window S1 printed; polls until the events arrive |
| 4 | S7 | `uv run python spikes/s7_foundry_eval.py` | Foundry path only; registers the evaluators and scores the seven sample rows |
| 5 | S3 | `spikes/s3_cli_probe.sh --persona exec --agent-id <id>` | Needs the declarative agent (P4.1, P4.2) and Node 24 |
| 6 | S8 | `uv run python spikes/s8_workiq_grounding.py --search` | A day after `evals deploy workiq`; `--surface workiq` needs Work IQ enabled (T21) |

> Outputs go to `spikes/out/`, which is **gitignored**: they contain tenant identifiers and user names. Summarise findings in the ADR and commit only sanitised examples.
