# Use with the Microsoft 365 Copilot Evaluations CLI

`cfeval` is designed to **complement**—not replace—Microsoft's official [`@microsoft/m365-copilot-eval`](https://github.com/microsoft/m365-copilot-eval) CLI (`runevals`) and **Work IQ Dev Tools** (preview; see [Evaluations CLI overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview) and [Evaluators reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-evaluators)).

* **Pinned interoperability contract**: `cfeval`'s exporter and importer target **`@microsoft/m365-copilot-eval` v2 preview (schema `2.0`)** while also accepting legacy v1 (`runevals`) result payloads during import (`src/cfeval/interop.py`).

## When to Use Each Tool

| Capability | `@microsoft/m365-copilot-eval` + Work IQ Dev Tools (Preview) | `cfeval` (This Repository) |
|---|---|---|
| **Primary focus** | Evaluating custom declarative/custom-engine M365 Copilot agents and broad prompt batches with built-in AI quality/citation evaluators. | Verifying **Fabric IQ numerical accuracy, display rounding, decoy avoidance, and engine DAX execution** alongside Work IQ workplace citations. |
| **Execution runner** | Node-based `runevals` batch runner against Copilot Chat and declarative agents. | Python `Target` runner (`copilot-chat`, `fabric-iq-mcp`, `fabric-data-agent`, `transcript-import`, `mock`) with post-run KQL trace correlation. |
| **Scoring strengths** | Built-in prose similarity, groundedness, and citation presence graders. | Unit/scale-aware numeric tolerance (`$12.8M` vs `12,840,000`), structured table/rank/set checks, `SemanticModelLogs` DAX verification, `pass^k`, Wilson 95% CI, and exact paired McNemar $p$-values. |
| **Best combined workflow** | Export your YAML golden set from `cfeval`, execute turns with `runevals`, and import `results.json` back into `cfeval` for deterministic numeric/routing gates and HTML/Eventhouse scorecards. | Use directly end to end whenever you need Workspace Monitoring DAX correlation (`engine+citations`) or multi-trial `pass^k` gating. |

See [Glossary and Microsoft Vocabulary Mapping](../reference/glossary.md) for how `cfeval` fields map to Microsoft's evaluation terminology.

## Round-Trip Workflow

### 1. Export a Golden Suite to `@microsoft/m365-copilot-eval` Format

Convert any `cfeval` v2 YAML golden suite into an `@microsoft/m365-copilot-eval` schema `2.0` evaluation input file:

```bash
cfeval golden export \
  --golden data/golden/contoso-smoke.yaml \
  --format m365-copilot-eval \
  --out evals.json
```

Each golden question's `id`, `question` (`prompt`), expected reference summary, and metadata tags are emitted in the v2 preview JSON structure expected by `runevals`.

### 2. Execute Prompts with `@microsoft/m365-copilot-eval`

Run `runevals` in your isolated demo tenant (`eval.tester@contoso.com`) according to the [Evaluations CLI documentation](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview) to produce `results.json`.

### 3. Import Results into `cfeval` for Deterministic Grading

Score the `runevals` output against your original YAML golden suite (`expected` scalars, `rel_tol`/`display_tol`, `expected_artifact`, `decoys`, `abstention` rules) and emit standard `cfeval` artifacts:

```bash
cfeval run \
  --target import \
  --from-m365-copilot-eval results.json \
  --golden data/golden/contoso-smoke.yaml \
  --run-id from-m365-eval \
  --no-publish
```

Then generate reports or enforce CI gates identically to native runs:

```bash
cfeval report runs/from-m365-eval --out report.html
cfeval gate runs/from-m365-eval --junit junit.xml --summary-md summary.md
```

> **Evidence tier note**: Imported `runevals` JSON carries answer text and Graph citations (`RoutingEvidence = citations-only`). If Fabric Workspace Monitoring was active during the `runevals` execution window and turn timestamps are present in `results.json`, pass `--trace` (with `.env` monitoring KQL settings) or run `cfeval rescore` to attach `SemanticModelLogs` DAX evidence.

## Related Pages

* [Glossary and Microsoft Vocabulary Mapping](../reference/glossary.md)
* [Platform Status](../reference/platform-status.md)
* [Compare Runs and Gate CI](./compare-runs-and-gate-ci.md)
