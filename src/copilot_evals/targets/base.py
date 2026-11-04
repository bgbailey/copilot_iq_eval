"""The contract every surface adapter implements (PLAN §9.3).

The runner (P2.6) schedules case x persona x surface x k attempts and talks to surfaces only through
``Target``. An adapter's job is narrow: send one prompt as one persona, measure the attempt window
(t0, t1) precisely, and return what the surface said. It does not correlate engine logs or compute
ground truth (``evidence`` and ``ground_truth`` do), and it never scores the answer: the evaluators
in ``evals/evaluators/`` do, on the Foundry or the local backend (ADR-007, ADR-009).

Rules for adapters (from .github/copilot-instructions.md):

* Read endpoints, scopes, headers and field names from ``config/contracts.yaml``, never from memory.
* Use timeouts and retries (tenacity, honouring ``Retry-After``); log as structured JSON with
  attempt_id, case_id, persona and surface.
* Report transport problems through ``AttemptResult.status`` instead of raising, so the runner can
  record the attempt as INCONCLUSIVE and move on.
"""

from typing import Any, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from copilot_evals.schemas import AttemptStatus, Case, Citation, Layer, Persona, ToolCall


class AttemptResult(BaseModel):
    """What a surface adapter returns for one attempt.

    The runner turns it into a ``schemas.Attempt`` by adding the run, case and persona identifiers,
    and into a ``schemas.EvalItem`` (the evaluation row) by adding the expectation and evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer_text: str | None
    t0_utc: AwareDatetime
    t1_utc: AwareDatetime
    status: AttemptStatus = AttemptStatus.OK
    citations: list[Citation] = Field(default_factory=list)
    tool_trace: list[ToolCall] = Field(default_factory=list)
    surface_scores: dict[str, Any] = Field(default_factory=dict)  # secondary signals, e.g. CLI ExactMatch
    usage: dict[str, int] = Field(default_factory=dict)  # token or credit usage, when the surface reports it
    error: str | None = None


class Target(Protocol):
    """A Copilot surface under test.

    Attributes:
        name: Surface name used in results and in ``Case.surfaces``, for example ``ref_mcp``.
        layer: Evaluation layer the surface belongs to (PLAN §3.1).
    """

    name: str
    layer: Layer

    async def attempt(self, case: Case, persona: Persona, i: int, variant: str = "default") -> AttemptResult:
        """Send ``case.prompt`` to the surface as ``persona``.

        Args:
            case: The golden case to run.
            persona: The identity to run it as; RLS applies to everything the surface does.
            i: Attempt number, 1-based, within the case's k runs.
            variant: Surface-specific variant, for example ``policy_context`` for the Chat API.

        Returns:
            The answer and its timing window, with ``status`` set instead of raising on transport errors.
        """
        ...
