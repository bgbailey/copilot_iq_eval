"""The contract every evaluation backend implements (PLAN §9.11, §9.12, ADR-009).

The runner (P2.6) hands a backend one ``EvalItem`` per attempt and gets back one ``EvaluatorResult``
per attempt and testing criterion. It never needs to know which backend it is talking to.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from copilot_evals.schemas import EvalItem, EvaluatorResult


class BackendName(StrEnum):
    """Where the evaluators run. Selected per run with ``--backend`` or ``settings.evaluation.backend``."""

    FOUNDRY = "foundry"  # Microsoft Foundry Evaluations (ADR-007), the default
    LOCAL = "local"  # in the harness process, with no Foundry project (ADR-009)


@dataclass(frozen=True)
class EvaluationRun:
    """What a backend returns for one batch of evaluation rows.

    Attributes:
        backend: The backend that produced the results.
        results: One result per attempt and testing criterion, in row order, then criterion order.
        evaluator_versions: Testing-criterion name -> content-addressed evaluator name
            (``definitions.catalog_name``), identical on both backends for the same source.
        extractions: Attempt ID -> the expected-blind extraction text generated for that row, kept
            for diagnosis on the scorecard. Empty when no extraction ran.
        report_url: The run's report page in the Foundry portal; None on the local backend.
        run_id: The Foundry evaluation run ID; None on the local backend.
    """

    backend: BackendName
    results: tuple[EvaluatorResult, ...]
    evaluator_versions: Mapping[str, str]
    extractions: Mapping[str, str] = field(default_factory=dict)
    report_url: str | None = None
    run_id: str | None = None


class EvaluationBackend(Protocol):
    """Scores evaluation rows with the evaluators in ``evals/evaluators/``."""

    @property
    def name(self) -> BackendName:
        """Which backend this is."""
        ...

    def evaluate(self, items: Sequence[EvalItem]) -> EvaluationRun:
        """Apply every testing criterion to every row and return the results.

        An evaluator that cannot decide yields an INCONCLUSIVE result rather than an exception, so
        one bad row never hides the results of the others.
        """
        ...
