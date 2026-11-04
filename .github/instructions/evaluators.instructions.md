---
applyTo: "evals/evaluators/**"
---

# Evaluators

Every verdict comes from the evaluators in this folder (PLAN §9.6). The same files run on both evaluation backends: Microsoft Foundry Evaluations (the default, ADR-007, PLAN §9.11) and the local backend (ADR-009, PLAN §9.12). Foundry uploads them as they are and the local backend executes them the same way, so they follow Foundry's rules, not the Python package's.

## Code-based evaluators (`code/*.py`)

- One self-contained file per evaluator with a top-level `grade(sample, item) -> float`. Read everything from `item` (the dataset row); the extraction step's output is in `item["sample"]["output_text"]` on both backends.
- Return `1.0` for pass and `0.0` for fail. When the row can't decide the check (a surface error, incomplete engine-log evidence), raise `InconclusiveError`: the backend records an error and the gate reports INCONCLUSIVE, never FAIL. Never return a "partial" score to mean "unsure".
- Standard library only, or the sandbox packages listed in `config/contracts.yaml` (`foundry_evaluations.code_evaluator.packages`). No network, no file access, no imports from `copilot_evals`, no relative imports. Keep each file well under 256 KB and each call well under 2 minutes.
- Never check which backend is running, and never behave differently on one: the verdict for a row must not depend on where it is scored.
- Write for Python 3.10 or later, and don't use `from __future__ import annotations`: dataclasses with string annotations can fail when the file runs as standalone code.
- Every row field the code reads must be declared under `reads` in `evaluators.yaml` and must exist in the item schema in `eval-definition.yaml`. Adding a field means changing `copilot_evals.schemas.EvalItem`, the item schema and the runner together.
- Compare numbers as `decimal.Decimal` built from the row's decimal strings, never as floats.
- Test every evaluator in `tests/unit/` by executing its file the way `tests/unit/test_evaluators.py` does.

## Prompt-based evaluators and the extraction prompt (`prompts/*.md`)

- An LLM must never see the expected answer. Fields in `judge_blind_fields` (`expected_value`, `expected_table`, `tolerance`) may not appear in any prompt, data mapping or template shown to an LLM; `evals validate` fails if they do.
- The judge returns JSON `{"result": ..., "reason": ...}`. Keep the scale and threshold in `evaluators.yaml` and `eval-definition.yaml` in step with the prompt.
- A judge prompt change is a behaviour change: calibrate it against `evals/judge/` on each backend in use before relying on it (PLAN §9.6.6).

## Sample rows (`samples/*.jsonl`)

- Fictional Contoso data only, with placeholder IDs (`00000000-0000-4000-8000-...`). Each line must be a valid `EvalItem`; `tests/unit/test_local_backend.py` checks them.

## Before you finish

`uv run evals validate --strict && uv run pytest tests/unit/test_evaluators.py tests/unit/test_evaluation_definitions.py tests/unit/test_local_backend.py && uv run evals score evals/evaluators/samples/eval-items.jsonl`
