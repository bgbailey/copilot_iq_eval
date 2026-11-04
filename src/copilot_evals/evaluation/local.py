"""The local evaluation backend: run the evaluators in the harness process (PLAN §9.12, ADR-009).

Use it when there is no Microsoft Foundry project, when preview services are not an option, or to try
an evaluator change before it reaches Foundry. It reads the same ``evals/evaluators/`` definitions as
the Foundry backend and applies them the same way:

* **Code-based evaluators.** Each file is executed as standalone code, as the Foundry sandbox runs it,
  and ``grade(sample, item)`` is called once per dataset row with a fresh copy of the row. A score at
  or above the criterion's ``pass_threshold`` passes. An exception, a score outside 0-1, or a call
  slower than the sandbox's two-minute limit is an error, so the result is INCONCLUSIVE, as on Foundry.
* **Prompt-based evaluators (the AI judge).** The prompt is filled from the criterion's
  ``data_mapping`` and sent to the judge deployment as one user message. The reply must hold
  ``{"result": ..., "reason": ...}``, and a result at or above ``threshold`` passes. Without a judge,
  these results are INCONCLUSIVE.
* **Expected-blind extraction** (``run_data_source`` in ``eval-definition.yaml``). For each ``answer``
  row, the definition's developer and user messages go to the judge deployment, and the reply reaches
  the code-based evaluators as ``item["sample"]["output_text"]``, where Foundry puts it. Other rows
  skip the call: no evaluator reads an extraction for them.

Results carry the same evaluator names and content-addressed versions as on Foundry, so the gate, the
results sink and the scorecard cannot tell the two backends apart. The local backend does not sandbox
evaluators at run time; ``evals validate`` keeps every evaluator within the sandbox rules statically,
so the same file always runs on Foundry as well.
"""

import copy
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

from copilot_evals.evaluation.backend import BackendName, EvaluationRun
from copilot_evals.evaluation.definitions import DefinitionError, EvaluationDefinitions, EvaluatorSpec, catalog_name
from copilot_evals.schemas import EvalItem, EvaluatorResult, Outcome

#: Foundry stops a code-based evaluator call after two minutes (config/contracts.yaml: foundry_evaluations).
SANDBOX_SECONDS_PER_CALL = 120.0

#: Rows scored in parallel when a judge is configured; judge calls dominate the run time.
DEFAULT_MAX_WORKERS = 8

Row = Mapping[str, Any]
Grade = Callable[[dict[str, Any], dict[str, Any]], float]

_SCOPED_REF = re.compile(r"\{\{\s*(item|sample)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_VARIABLE_REF = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

logger = logging.getLogger(__name__)


class JudgeClient(Protocol):
    """The chat model deployment behind the AI judge and the extraction step on the local backend.

    Implementations own sign-in, timeouts and retries. P2.8 adds one for the Azure OpenAI v1 API with
    Microsoft Entra ID (``config/contracts.yaml``: ``azure_openai_v1``).
    """

    def complete(self, messages: Sequence[Mapping[str, str]], *, max_output_tokens: int | None = None) -> str:
        """Send ``messages`` (each ``{"role": ..., "content": ...}``) and return the reply text."""
        ...


@dataclass(frozen=True)
class _Criterion:
    """One testing criterion, resolved against the evaluator catalog."""

    name: str
    spec: EvaluatorSpec
    version: str
    threshold: Decimal
    data_mapping: Mapping[str, str]


class LocalBackend:
    """Runs the evaluation definitions in this process. See the module docstring for the semantics.

    Args:
        definitions: The loaded ``evals/evaluators/`` definitions; check them with ``evals validate``.
        judge: The AI judge deployment, or None to run without one.
        max_workers: Rows scored in parallel when a judge is configured.
        seconds_per_call: The time limit for one code-based evaluator call.

    Raises:
        DefinitionError: A testing criterion cannot be resolved, or an evaluator file has no ``grade``.
    """

    def __init__(
        self,
        definitions: EvaluationDefinitions,
        *,
        judge: JudgeClient | None = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        seconds_per_call: float = SANDBOX_SECONDS_PER_CALL,
    ) -> None:
        self._definitions = definitions
        self._judge = judge
        self._max_workers = max(1, max_workers) if judge is not None else 1
        self._seconds_per_call = seconds_per_call
        self._criteria = [self._resolve(criterion) for criterion in definitions.criteria]
        self._grades = {c.spec.key: load_grade(c.spec.source) for c in self._criteria if c.spec.kind == "code"}
        self._prompts = {
            c.spec.key: c.spec.source.read_text(encoding="utf-8") for c in self._criteria if c.spec.kind == "prompt"
        }
        self._extraction = _extraction_messages(definitions)
        self._extraction_max_tokens = _extraction_max_tokens(definitions)

    @property
    def name(self) -> BackendName:
        """Always ``BackendName.LOCAL``."""
        return BackendName.LOCAL

    @property
    def has_judge(self) -> bool:
        """Whether an AI judge is configured."""
        return self._judge is not None

    def evaluate(self, items: Sequence[EvalItem]) -> EvaluationRun:
        """Score validated rows. Each is serialised exactly as it would be uploaded to Foundry."""
        return self.evaluate_rows([item.model_dump(mode="json") for item in items])

    def evaluate_rows(self, rows: Sequence[Row]) -> EvaluationRun:
        """Score rows already serialised as JSON (``EvalItem.model_dump(mode="json")``)."""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            scored = list(pool.map(self._evaluate_row, rows))
        extractions = {
            str(row["attempt_id"]): text for row, (_, text) in zip(rows, scored, strict=True) if text is not None
        }
        return EvaluationRun(
            backend=self.name,
            results=tuple(result for results, _ in scored for result in results),
            evaluator_versions={criterion.name: criterion.version for criterion in self._criteria},
            extractions=extractions,
        )

    # -- One row -----------------------------------------------------------------------------------

    def _evaluate_row(self, row: Row) -> tuple[list[EvaluatorResult], str | None]:
        attempt_id = UUID(str(row["attempt_id"]))
        extraction = self._extract(row, attempt_id)
        sample: dict[str, Any] = {"output_text": extraction} if extraction is not None else {}
        item: dict[str, Any] = {**row, "sample": sample}
        results = [
            self._grade(criterion, sample, item, attempt_id)
            if criterion.spec.kind == "code"
            else self._ask_judge(criterion, item, attempt_id)
            for criterion in self._criteria
        ]
        return results, extraction

    def _grade(
        self, criterion: _Criterion, sample: dict[str, Any], item: dict[str, Any], attempt_id: UUID
    ) -> EvaluatorResult:
        """Call a code-based evaluator; an error is an INCONCLUSIVE result, as Foundry marks the row as errored."""
        grade = self._grades[criterion.spec.key]
        started = time.monotonic()
        try:
            score = float(grade(copy.deepcopy(sample), copy.deepcopy(item)))
        except Exception as exc:  # the evaluator's own way of saying it cannot decide
            return self._result(criterion, attempt_id, Outcome.INCONCLUSIVE, reason=f"{type(exc).__name__}: {exc}")
        elapsed = time.monotonic() - started
        if elapsed > self._seconds_per_call:
            reason = f"took {elapsed:.1f} s; the Foundry sandbox stops a call after {self._seconds_per_call:.0f} s"
            return self._result(criterion, attempt_id, Outcome.INCONCLUSIVE, reason=reason)
        if not 0.0 <= score <= 1.0:  # also catches NaN
            return self._result(criterion, attempt_id, Outcome.INCONCLUSIVE, reason=f"score {score} is outside 0-1")
        value = Decimal(str(score))
        outcome = Outcome.PASS if value >= criterion.threshold else Outcome.FAIL
        return self._result(criterion, attempt_id, outcome, score=value)

    def _ask_judge(self, criterion: _Criterion, item: dict[str, Any], attempt_id: UUID) -> EvaluatorResult:
        """Call a prompt-based evaluator: fill the prompt, ask the judge, and read ``result`` and ``reason``."""
        if self._judge is None:
            reason = "no AI judge is configured for the local backend"
            return self._result(criterion, attempt_id, Outcome.INCONCLUSIVE, reason=reason)
        variables = {name: render(template, item) for name, template in criterion.data_mapping.items()}
        prompt = fill(self._prompts[criterion.spec.key], variables)
        try:
            verdict = parse_json_object(self._judge.complete([{"role": "user", "content": prompt}]))
            result = verdict["result"]
            score = Decimal(int(result)) if isinstance(result, bool) else Decimal(str(result))
            if not score.is_finite():
                raise ValueError(f"result {result!r} is not a finite number")
        except Exception as exc:  # no usable verdict: the judge could not decide this row
            reason = f"judge error: {type(exc).__name__}: {exc}"
            return self._result(criterion, attempt_id, Outcome.INCONCLUSIVE, reason=reason)
        outcome = Outcome.PASS if score >= criterion.threshold else Outcome.FAIL
        return self._result(criterion, attempt_id, outcome, score=score, reason=str(verdict.get("reason") or ""))

    def _extract(self, row: Row, attempt_id: UUID) -> str | None:
        """Run the expected-blind extraction step for an ``answer`` row; None when it does not run or fails."""
        if self._judge is None or not self._extraction or row.get("expected_behavior") != "answer":
            return None
        messages = [{"role": role, "content": render(text, row)} for role, text in self._extraction]
        try:
            return self._judge.complete(messages, max_output_tokens=self._extraction_max_tokens)
        except Exception:  # value_match then relies on its own parsing, as when Foundry's step fails
            logger.warning("extraction failed", extra={"attempt_id": str(attempt_id)}, exc_info=True)
            return None

    # -- Set-up ------------------------------------------------------------------------------------

    def _resolve(self, criterion: dict[str, Any]) -> _Criterion:
        name = str(criterion.get("name"))
        spec = self._definitions.spec_for(criterion)
        if spec is None:
            raise DefinitionError(f"testing criterion '{name}' does not name a catalog evaluator (evals validate)")
        parameters = criterion.get("initialization_parameters") or {}
        threshold = "pass_threshold" if spec.kind == "code" else "threshold"
        if threshold not in parameters:
            raise DefinitionError(f"testing criterion '{name}' has no {threshold} (evals validate)")
        return _Criterion(
            name=name,
            spec=spec,
            version=catalog_name(self._definitions, spec.key),
            threshold=Decimal(str(parameters[threshold])),
            data_mapping={str(key): str(value) for key, value in (criterion.get("data_mapping") or {}).items()},
        )

    @staticmethod
    def _result(
        criterion: _Criterion, attempt_id: UUID, outcome: Outcome, *, score: Decimal | None = None, reason: str = ""
    ) -> EvaluatorResult:
        return EvaluatorResult(
            attempt_id=attempt_id,
            evaluator=criterion.name,
            evaluator_version=criterion.version,
            outcome=outcome,
            score=score,
            threshold=criterion.threshold,
            reason=reason,
        )


def load_grade(path: Path) -> Grade:
    """Execute a code-based evaluator file as standalone code, as the Foundry sandbox does, and return ``grade``.

    Raises:
        DefinitionError: The file does not define a callable ``grade``.
    """
    namespace: dict[str, Any] = {"__name__": f"evaluator_{path.stem}"}
    # Repository code, reviewed like any module. It runs as standalone code rather than as an import,
    # so it behaves exactly as it does in the Foundry sandbox.
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102  # nosec B102
    grade = namespace.get("grade")
    if not callable(grade):
        raise DefinitionError(f"{path}: no grade(sample, item) function")
    return cast(Grade, grade)


def render(template: str, item: Mapping[str, Any]) -> str:
    """Fill the ``{{item.<field>}}`` and ``{{sample.<field>}}`` references in a template from one row.

    Strings are inserted as they are and other values as JSON (``null``, ``true``, lists), in a single
    pass, so text inside an answer is never treated as a template.
    """

    # TODO(spike-S7): match how Foundry renders non-string values, once ADR-008 records it.
    def value(match: re.Match[str]) -> str:
        scope, name = match.group(1), match.group(2)
        source = item.get("sample") if scope == "sample" else item
        found = source.get(name) if isinstance(source, Mapping) else None
        return found if isinstance(found, str) else json.dumps(found)

    return _SCOPED_REF.sub(value, template)


def fill(prompt: str, variables: Mapping[str, str]) -> str:
    """Fill a prompt-based evaluator's ``{{name}}`` variables in a single pass; unknown names stay as written."""
    return _VARIABLE_REF.sub(lambda match: variables.get(match.group(1), match.group(0)), prompt)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the JSON object in a model reply, allowing Markdown code fences or prose around it.

    Raises:
        ValueError: The reply holds no JSON object.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply holds no JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("the reply is not a JSON object")
    return value


def _extraction_messages(definitions: EvaluationDefinitions) -> list[tuple[str, str]]:
    """The extraction step's (role, text) messages from ``run_data_source``, with ``{file:...}`` resolved."""
    source = definitions.definition.get("run_data_source")
    input_messages = source.get("input_messages") if isinstance(source, dict) else None
    template = input_messages.get("template") if isinstance(input_messages, dict) else None
    messages: list[tuple[str, str]] = []
    for message in template if isinstance(template, list) else []:
        content = message.get("content") if isinstance(message, dict) else None
        text = content.get("text") if isinstance(content, dict) else None
        if not isinstance(message, dict) or not isinstance(text, str):
            raise DefinitionError("run_data_source.input_messages.template: every message needs a role and text")
        messages.append((str(message.get("role")), definitions.resolve_file(text)))
    return messages


def _extraction_max_tokens(definitions: EvaluationDefinitions) -> int | None:
    """``max_completion_tokens`` from the extraction step's sampling parameters, if set."""
    source = definitions.definition.get("run_data_source")
    target = source.get("target") if isinstance(source, dict) else None
    sampling = target.get("sampling_params") if isinstance(target, dict) else None
    tokens = sampling.get("max_completion_tokens") if isinstance(sampling, dict) else None
    return tokens if isinstance(tokens, int) else None
