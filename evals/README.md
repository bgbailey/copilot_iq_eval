# Evaluation assets

| Path | What it holds | Built by |
|---|---|---|
| [`golden/cases.yaml`](golden/cases.yaml) | The golden test cases: prompt, persona, expected behaviour, models, decoys, reference DAX and tolerance. | Seeded with 14 cases, 4 of them joint Work IQ + Fabric IQ cases; grown to 48 by P1.8 |
| [`golden/personas.yaml`](golden/personas.yaml) | Test personas: UPN template, token-cache secret, workspaces, RLS. | Bootstrap |
| [`golden/models.yaml`](golden/models.yaml) | Semantic models (certified and decoy) and seeded documents (work sources with their facts, and decoys), with owners. | Bootstrap; documents from v1.3 (ADR-010) |
| `golden/expected_snapshot.json` | Expected values frozen at data freeze; a live/frozen mismatch raises `MODEL_CHANGED`. Copy it from `runs/deploy/` after `evals deploy fabric`. | P1.7 |
| [`evaluators/`](evaluators/README.md) | **The evaluators, written once and run on either backend** (Microsoft Foundry Evaluations or local): code-based checks, the AI judge and extraction prompts, the eval definition and sample rows. | Bootstrap; P2.5, P2.7, P2.8 |
| [`judge/`](judge/README.md) | Calibration set for the AI judge (the `behavior_match` evaluator and the extraction prompt). | P10.1 |
| `generated/` | Evaluation datasets, per-attempt CLI datasets and Copilot Studio CSVs. Generated, never committed. | P2.6, P4.3, P7.1 |

Validate the golden set and the evaluator definitions offline, and score the sample rows on the local backend, at any time:

```bash
uv run evals validate --strict
uv run evals score evals/evaluators/samples/eval-items.jsonl
```

It checks every case against the schema in `src/copilot_evals/schemas.py`, then checks the references between files: personas, models, decoys and document decoys must exist, case IDs must be unique, and a decoy can never be an expected model. It also checks the evaluators against the Foundry sandbox rules, which apply on both backends, and against the dataset row schema. CI runs both commands on every push.

## Case categories (PLAN §5.2)

| Category | Purpose | Target | Seeded |
|---|---|---|---|
| Direct single-model | Baseline | 6 | REV-001, FIN-002, OPS-003 |
| Paraphrase groups | Robustness | 8 | (paraphrases on REV-001) |
| Disambiguation | Gross vs net revenue, Sales vs Finance | 4 | REV-002 |
| Decoy avoidance | Sandbox model and draft document | 4 | REV-020 |
| Time intelligence | Fiscal vs calendar, FYTD, prior year, YoY | 6 | TI-004 |
| RLS persona | Same prompt, different persona | 6 | REV-010 |
| Cross-model | Two models combined by the orchestrator | 4 | X-001 |
| Clarification expected | Ambiguous metric or period | 2 | CLR-001 |
| Refuse or out of scope | No model holds the data | 2 | |
| No access | `noaccess` persona | 2 | NOA-001 |
