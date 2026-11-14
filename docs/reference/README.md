# Reference Documentation Index

The files in this directory provide authoritative CLI, schema, exit-code, platform-lifecycle, and vocabulary specifications for `cfeval`. Four pages (`cli.md`, `configuration.md`, `golden-schema.md`, `telemetry-schema.md`) are generated deterministically from source code by [`tools/gen_reference_docs.py`](../../tools/gen_reference_docs.py) and checked for drift in CI (`--check`).

## Machine-Generated Reference Pages

| Document | Source of Truth | Contents |
|---|---|---|
| [CLI Reference](cli.md) | `src/cfeval/cli.py` | Subcommands, flags, defaults, and usage examples. |
| [Configuration Reference](configuration.md) | `src/cfeval/config.py` (`.env.example`) | All `CFEVAL_*` environment variables, defaults, types, and secret handling rules. |
| [Golden Schema Reference (v2)](golden-schema.md) | `schemas/golden.schema.json` & `data/golden/*.yaml` | Golden YAML v2 top-level structure, `defaults`, `case_type` schemas, `gates`, `unit` types, and legacy v1 CSV mapping. |
| [Telemetry Schema Reference](telemetry-schema.md) | `src/cfeval/schema.py` (`TABLES`, `SCHEMA_VERSION = 2`) | Exact column names, Kusto types, and deterministic `RowId` keys across JSONL and Eventhouse tables. |

## Curated Reference Specifications

| Document | Contents |
|---|---|
| [CLI Exit Codes](exit-codes.md) | Deterministic exit code contract (`0` pass, `1` failure/regression, `2` gate threshold failed, `3` inconclusive/error evidence, `4` configuration/usage error). |
| [Platform Status](platform-status.md) | GA vs. Preview matrix (**Last verified: 2026-11-13**) with Microsoft Learn links (`R1`–`R17`) covering M365 Copilot Chat API, Fabric IQ, Workspace Monitoring, Evaluations CLI, and Microsoft Foundry. |
| [Glossary](glossary.md) | Mapping between `cfeval` telemetry terms (`golden set`, `question`, `check`, `reference_dax`, `fabric-native`, `foundry`) and Microsoft's published evaluation vocabulary (`test set`, `test case`, `prompt`, `assertion`, `grader`, `quality signal`, `grounding data`). |

## Regenerating Reference Docs

After modifying CLI flags, `Settings` fields, golden schema fields, or `src/cfeval/schema.py`:

```bash
python tools/gen_reference_docs.py
python tools/gen_reference_docs.py --check
```
