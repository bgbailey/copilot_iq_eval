"""Evaluation rows and results on disk (PLAN §9.1, §9.11, §9.12).

* ``eval_items.jsonl``: one ``EvalItem`` per line. The runner writes it (P2.6), the Foundry backend
  uploads it as the run's dataset (P2.7), and ``evals score`` reads it back to score it again on
  either backend.
* ``evaluator_results.jsonl`` and ``evaluation_run.json``: what a backend returned, in the same form
  whichever backend produced it.
"""

import json
from collections.abc import Iterable
from pathlib import Path

from copilot_evals.evaluation.backend import EvaluationRun
from copilot_evals.schemas import EvalItem

ITEMS_FILE = "eval_items.jsonl"
RESULTS_FILE = "evaluator_results.jsonl"
RUN_FILE = "evaluation_run.json"


class EvalItemsError(Exception):
    """A file of evaluation rows cannot be read, or one of its rows is not a valid ``EvalItem``."""


def read_eval_items(path: Path) -> list[EvalItem]:
    """Read and validate a JSONL file of evaluation rows. Blank lines are skipped.

    Raises:
        EvalItemsError: The file is empty, or a line is not JSON or not a valid row. The message names
            the file and line.
    """
    items: list[EvalItem] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(EvalItem.model_validate(json.loads(line)))
        except ValueError as exc:  # json.JSONDecodeError and pydantic.ValidationError are both ValueErrors
            raise EvalItemsError(f"{path}:{number}: {exc}") from exc
    if not items:
        raise EvalItemsError(f"{path}: no evaluation rows")
    return items


def write_eval_items(path: Path, items: Iterable[EvalItem]) -> None:
    """Write evaluation rows as JSONL, serialised exactly as the backends receive them."""
    _write_lines(path, (item.model_dump(mode="json") for item in items))


def write_evaluation_run(folder: Path, run: EvaluationRun) -> None:
    """Write a backend's results to ``evaluator_results.jsonl`` and its run metadata to ``evaluation_run.json``."""
    _write_lines(folder / RESULTS_FILE, (result.model_dump(mode="json") for result in run.results))
    metadata = {
        "backend": run.backend.value,
        "run_id": run.run_id,
        "report_url": run.report_url,
        "evaluator_versions": dict(run.evaluator_versions),
        "results": len(run.results),
        "extractions": dict(run.extractions),
    }
    (folder / RUN_FILE).write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_lines(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
