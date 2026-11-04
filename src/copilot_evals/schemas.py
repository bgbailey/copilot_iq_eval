"""Data contracts for the evaluation harness (PLAN §5.1 and §9.1).

Every record the harness reads or writes is defined here as a pydantic v2 model, so the golden
set, the runner, the evaluation backends and the results sink share one vocabulary:

* Golden-set models (PLAN §5): ``Case`` and its parts, ``Persona``, ``SemanticModelRef`` and
  ``DocumentRef``. They are loaded from ``evals/golden/*.yaml`` by ``copilot_evals.golden``.
* Run-time records (PLAN §9.1): ``Attempt`` and ``Evidence`` (what the runner collected),
  ``EvalItem`` (one row of the evaluation dataset), ``EvaluatorResult`` (one evaluator's verdict,
  from either backend) and ``CaseResult`` (the gate's aggregate). Their fields
  mirror the Delta tables in ``lh_eval`` so the OneLake sink (P8.1) can write them without mapping.

Every verdict comes from the evaluators in ``evals/evaluators/``, run by Microsoft Foundry
Evaluations or by the local backend (ADR-007, ADR-009): nothing in this module scores an answer.

Conventions (see .github/copilot-instructions.md):

* Numbers that are compared are ``decimal.Decimal``, never ``float``.
* Timestamps are timezone-aware and normalised to UTC.
* Models reject unknown fields, so a typo in a YAML file fails validation instead of being ignored,
  and instances are immutable once validated.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

# ---------------------------------------------------------------------------------------------
# Constrained identifiers
# ---------------------------------------------------------------------------------------------

#: Stable golden-case identifier such as ``REV-001``. IDs are never reused (CONTRIBUTING.md).
CaseId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,5}-\d{3}$")]

#: Lower snake_case key that refers to an entry in personas.yaml or models.yaml, or names an intent.
Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]

#: Lower-case, hyphenated tag such as ``single-model`` or ``fiscal-time``.
Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]

#: A fact stated in a seeded Microsoft 365 document: ``<document key>.<fact key>`` (PLAN §4.4).
FactRef = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")]

#: Surfaces a golden case can target (PLAN §9.3). ``ui_<appClass>`` surfaces are created at run
#: time by the Interaction Export harvester (P6.2) and are never listed in a case.
CaseSurface = Literal["ref_mcp", "agent_cli", "chat_api", "copilot_studio", "data_agent", "ui_export"]


class _Contract(BaseModel):
    """Base class for every contract: unknown fields are errors and instances are immutable."""

    # protected_namespaces=() allows field names such as ``model_key`` and ``model_url``.
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


# ---------------------------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------------------------


class Behavior(StrEnum):
    """What a correct response does (PLAN §5.1 ``expect.behavior``, scored per §9.6.4)."""

    ANSWER = "answer"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    NO_ACCESS = "no_access"


class RouteMode(StrEnum):
    """How observed semantic models are compared with the expected ones (PLAN §9.6.2).

    ``exclusive``: exactly the expected models were queried. ``includes``: every expected model was
    queried, others are allowed. ``any_of``: at least one expected model was queried.
    """

    EXCLUSIVE = "exclusive"
    INCLUDES = "includes"
    ANY_OF = "any_of"


class CitationRequirement(StrEnum):
    """Whether the answer must name its source model or report (PLAN §9.6.3)."""

    REQUIRED = "required"
    OPTIONAL = "optional"


class Unit(StrEnum):
    """Unit of an expected value; drives candidate selection in numeric extraction (PLAN §9.6.1)."""

    CURRENCY_USD = "currency_usd"
    COUNT = "count"
    PERCENT = "percent"
    RATIO = "ratio"
    HOURS = "hours"


class Criticality(StrEnum):
    """``critical`` cases must pass k of k attempts; ``standard`` cases need the suite pass rate."""

    CRITICAL = "critical"
    STANDARD = "standard"


class TableMatch(StrEnum):
    """How keyed (table) answers are compared (PLAN §5.1)."""

    ALL_KEYS = "all_keys"
    TOP_N = "top_n"


class DocumentRole(StrEnum):
    """What a seeded Microsoft 365 document is for in the tests (PLAN §4.4)."""

    SOURCE = "source"  # a work source Copilot should use, and cite, for what it states (targets, objectives)
    DECOY = "decoy"  # an unofficial document Copilot must never use, such as a draft


class Endorsement(StrEnum):
    """Power BI endorsement of a semantic model (PLAN §4.2)."""

    CERTIFIED = "certified"
    PROMOTED = "promoted"
    NONE = "none"


class Layer(StrEnum):
    """Evaluation layer (PLAN §3.1). ``L1-DA`` holds Fabric data agent diagnostics (P7.2)."""

    L0 = "L0"
    L1 = "L1"
    L1_DA = "L1-DA"
    L2 = "L2"
    L3 = "L3"


class AttemptStatus(StrEnum):
    """Transport-level status of one surface call. Anything but ``ok`` makes the attempt INCONCLUSIVE."""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    THROTTLED = "throttled"


class EvidenceSource(StrEnum):
    """Where a piece of routing evidence came from (PLAN §9.1 ``eval_evidence.source``)."""

    ENGINE_LOG = "engine_log"
    ATTRIBUTION = "attribution"
    CITATION = "citation"
    TOOL_TRACE = "tool_trace"
    AUDIT = "audit"
    EXPORT = "export"


class Outcome(StrEnum):
    """Verdict of one evaluator result, or of an attempt (PLAN §9.6.7).

    Both backends map an evaluator's result the same way: passed -> PASS, failed -> FAIL, errored
    (the evaluator raised) -> INCONCLUSIVE.
    An evaluator errors on purpose when it cannot decide (incomplete evidence, surface error).
    INCONCLUSIVE never passes a gate and never counts as a regression.
    """

    PASS = "PASS"  # noqa: S105  # a verdict, not a password
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


# ---------------------------------------------------------------------------------------------
# Golden set (PLAN §5)
# ---------------------------------------------------------------------------------------------


class Tolerance(_Contract):
    """Numeric tolerance for comparing an extracted value with the expected value (PLAN §9.6.1).

    The allowed error is ``max(abs, rel * |expected|)``. With ``display_aware`` it widens to half
    the precision step the answer was displayed with, and ``max_display_rel`` fails answers that
    are rounded too coarsely to be checked at all.
    """

    rel: Decimal = Field(default=Decimal(0), ge=0)
    abs: Decimal = Field(default=Decimal(0), ge=0)
    display_aware: bool = False
    max_display_rel: Annotated[Decimal, Field(gt=0, le=1)] | None = None


class ValueExpectation(_Contract):
    """Expected scalar value (PLAN §5.1 ``expect.value``).

    Ground truth is computed live, before each case, by one of:

    * ``reference_dax``: a DAX query run as the persona against the first model in
      ``expect.models`` (PLAN §9.4); or
    * ``composite``: the name of a resolver in ``ground_truth/composite.py`` (P2.4) that combines
      several reference queries, for questions no single query can answer, such as cross-model
      cases (PLAN Appendix B, ``X-001``).
    """

    reference_dax: str | None = None
    composite: Key | None = None
    unit: Unit
    tolerance: Tolerance = Field(default_factory=Tolerance)

    @model_validator(mode="after")
    def _one_ground_truth_source(self) -> Self:
        if (self.reference_dax is None) == (self.composite is None):
            raise ValueError("set exactly one of 'reference_dax' or 'composite'")
        return self


class TableExpectation(_Contract):
    """Expected keyed values, for example one value per region (PLAN §5.1 ``expect.table``).

    ``reference_dax`` returns ``(key, value)`` rows. ``match: all_keys`` requires every expected key
    in the answer; ``match: top_n`` compares the first ``n`` keys only.
    """

    reference_dax: str
    unit: Unit
    match: TableMatch = TableMatch.ALL_KEYS
    n: Annotated[int, Field(ge=1)] | None = None
    tolerance: Tolerance = Field(default_factory=Tolerance)

    @model_validator(mode="after")
    def _n_only_for_top_n(self) -> Self:
        if (self.match == TableMatch.TOP_N) != (self.n is not None):
            raise ValueError("'n' is required when match is 'top_n' and not allowed otherwise")
        return self


class Expectation(_Contract):
    """Everything a correct response must satisfy (PLAN §3.4 pass rule, §5.1 ``expect``)."""

    behavior: Behavior
    models: list[Key] = Field(default_factory=list)
    route_mode: RouteMode = RouteMode.INCLUDES
    decoys: list[Key] = Field(default_factory=list)
    doc_decoys: list[Key] = Field(default_factory=list)
    citation: CitationRequirement = CitationRequirement.OPTIONAL
    value: ValueExpectation | None = None
    table: TableExpectation | None = None
    work_sources: list[Key] = Field(default_factory=list)  # documents (role source) the answer must cite
    work_facts: list[FactRef] = Field(default_factory=list)  # document facts the answer must state

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.value is not None and self.table is not None:
            raise ValueError("set at most one of 'value' or 'table'")
        if self.behavior == Behavior.ANSWER:
            if self.value is None and self.table is None:
                raise ValueError("behavior 'answer' needs an expected 'value' or 'table'")
            if not self.models:
                raise ValueError("behavior 'answer' needs at least one expected model")
        elif self.value is not None or self.table is not None:
            raise ValueError(f"behavior '{self.behavior}' must not define an expected value or table")
        overlap = sorted(set(self.models) & set(self.decoys))
        if overlap:
            raise ValueError(f"models listed as both expected and decoy: {overlap}")
        if self.work_facts and self.behavior != Behavior.ANSWER:
            raise ValueError("only 'answer' cases can expect work facts")
        overlap = sorted(set(self.work_sources) & set(self.doc_decoys))
        if overlap:
            raise ValueError(f"documents listed as both work source and decoy: {overlap}")
        return self


class Case(_Contract):
    """One golden test case: a prompt, a persona and what a correct response looks like (PLAN §5.1)."""

    id: CaseId
    intent: Key
    prompt: str = Field(min_length=1)
    paraphrases: list[str] = Field(default_factory=list)
    persona: Key
    surfaces: list[CaseSurface] | None = None  # None means every enabled surface
    expect: Expectation
    runs: int = Field(default=3, ge=1, le=10)
    criticality: Criticality = Criticality.STANDARD
    tags: list[Tag] = Field(default_factory=list)
    notes: str | None = None


class Persona(_Contract):
    """An Entra ID test user with a Microsoft 365 Copilot licence and one RLS role (PLAN §4.3).

    ``upn`` is a template: ``{tenant_domain}`` is filled in from settings at run time, so no
    tenant-specific identity is committed to the repository.

    ``rls_role`` and ``regions`` drive the deployment (``evals deploy fabric``): role membership in
    the certified models and the persona's rows in the ``security_user_region`` table. ``rls`` is
    the human-readable summary shown in reports.
    """

    key: Key
    upn: str = Field(pattern=r"^[^@\s]+@(\{tenant_domain\}|[A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
    keyvault_secret: str = Field(pattern=r"^[0-9A-Za-z-]{1,127}$")
    workspaces: list[str] = Field(min_length=1)
    rls: str
    rls_role: Literal["AllRegions", "RegionScope"] | None = None
    regions: list[str] = Field(default_factory=list)
    purpose: str

    @model_validator(mode="after")
    def _regions_match_role(self) -> Self:
        if (self.rls_role == "RegionScope") != bool(self.regions):
            raise ValueError("`regions` is required for rls_role RegionScope and not allowed otherwise")
        return self

    def resolve_upn(self, tenant_domain: str) -> str:
        """Return the persona's user principal name for ``tenant_domain``."""
        return self.upn.replace("{tenant_domain}", tenant_domain)


class SemanticModelRef(_Contract):
    """A semantic model the tests route to or away from (PLAN §4.2, ``models.yaml``).

    ``report_url`` and ``model_url`` are tenant-specific. Leave them empty in the repository; they
    are resolved at run time through the Fabric REST API (P2.2).
    """

    key: Key
    display_name: str
    workspace: str
    owner: str
    endorsement: Endorsement
    decoy: bool = False
    report: str | None = None
    domains: list[str] = Field(default_factory=list)
    report_url: str | None = None
    model_url: str | None = None


class DocumentFact(_Contract):
    """A figure a seeded document states, such as an approved target (PLAN §4.4)."""

    value: Decimal
    unit: Unit
    label: str = Field(min_length=1)  # how the document describes it, for people reading the golden set


class DocumentRef(_Contract):
    """A seeded Microsoft 365 document the tests depend on (PLAN §4.2, §4.4).

    A ``source`` document holds facts Copilot should use and cite, such as approved targets; the
    actual figures still come from the certified semantic models. A ``decoy`` must never be used.
    ``match`` holds case-insensitive fragments compared with citation titles, URLs and the answer.
    """

    key: Key
    title: str
    location: str
    role: DocumentRole = DocumentRole.DECOY
    match: list[str] = Field(min_length=1)
    facts: dict[Key, DocumentFact] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------------------
# Run-time records (PLAN §9.1)
# ---------------------------------------------------------------------------------------------


class Citation(_Contract):
    """A source the surface cited or attributed. ``kind`` is powerbi, sharepoint, web or other."""

    title: str | None = None
    url: str | None = None
    kind: str = "other"


class ToolCall(_Contract):
    """One tool call in a reference-orchestrator trace (PLAN §9.3.1, P3.3)."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    duration_ms: Annotated[int, Field(ge=0)] | None = None
    output_preview: str | None = None


class Attempt(_Contract):
    """One call to one surface for one case, persona and attempt number (PLAN §9.1 attempt record)."""

    attempt_id: UUID
    run_id: UUID
    case_id: CaseId
    surface: str
    variant: str = "default"
    persona: Key
    persona_upn: str
    attempt_no: int = Field(ge=1)
    t0_utc: AwareDatetime
    t1_utc: AwareDatetime
    latency_ms: int = Field(ge=0)
    status: AttemptStatus
    answer_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    tool_trace: list[ToolCall] = Field(default_factory=list)
    surface_scores: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @field_validator("t0_utc", "t1_utc")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> Self:
        if self.t1_utc < self.t0_utc:
            raise ValueError("t1_utc must not be earlier than t0_utc")
        return self


class Evidence(_Contract):
    """One piece of routing or citation evidence attached to an attempt (PLAN §9.1 ``eval_evidence``)."""

    attempt_id: UUID
    source: EvidenceSource
    item_id: str | None = None
    item_name: str | None = None
    model_key: Key | None = None
    url: str | None = None
    kind: str | None = None
    is_expected: bool = False
    is_decoy: bool = False
    event_text_hash: str | None = None
    application_name: str | None = None
    ts_utc: AwareDatetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ExpectedRow(_Contract):
    """One expected (key, value) pair of a table answer, for example one region's Sev1 count."""

    key: str
    value: Decimal


class WorkSource(_Contract):
    """A seeded document the answer must cite, with the fragments that identify it (PLAN §9.6.3)."""

    key: Key
    match: list[str] = Field(min_length=1)


class ExpectedFact(_Contract):
    """A figure from a seeded document that the answer must state, such as a target (PLAN §9.6.1)."""

    key: FactRef
    value: Decimal
    unit: Unit


class EvalItem(_Contract):
    """One row of the evaluation dataset: one attempt, its expectation and its evidence.

    The runner builds it (P2.6) after ground truth and evidence correlation. Code-based evaluators run
    without network access (in the Foundry sandbox, and by the same rule on the local backend), so
    everything a check needs must be in the row.
    Field names and types match ``data_source_config.item_schema`` in
    ``evals/evaluators/eval-definition.yaml``; a unit test keeps the two in step. Serialise with
    ``model_dump(mode="json")``, which writes decimals as strings so no precision is lost.

    Fields named in ``judge_blind_fields`` (the expected value, table, facts and tolerance) are read
    only by code-based evaluators; no prompt shown to an LLM may reference them. ``work_sources`` and
    ``expected_facts`` are set only for joint Work IQ + Fabric IQ cases (PLAN §4.4).
    """

    # Identity of the attempt
    attempt_id: UUID
    run_id: UUID
    case_id: CaseId
    intent: Key
    surface: str
    variant: str = "default"
    layer: Layer
    persona: Key
    attempt_no: int = Field(ge=1)
    criticality: Criticality
    status: AttemptStatus
    latency_ms: int = Field(ge=0)
    # What Copilot was asked and said
    query: str
    response: str = ""
    citations: list[Citation] = Field(default_factory=list)
    # What a correct response looks like (golden set + live ground truth from Fabric)
    expected_behavior: Behavior
    expected_shape: Literal["scalar", "table", "none"]
    expected_unit: Unit | None = None
    expected_value: Decimal | None = None
    expected_table: list[ExpectedRow] = Field(default_factory=list)
    table_match: TableMatch | None = None
    table_n: Annotated[int, Field(ge=1)] | None = None
    tolerance: Tolerance | None = None
    expected_models: list[Key] = Field(default_factory=list)
    route_mode: RouteMode = RouteMode.INCLUDES
    decoy_models: list[Key] = Field(default_factory=list)
    doc_decoy_patterns: list[str] = Field(default_factory=list)
    citation_required: bool = False
    expected_sources: list[str] = Field(default_factory=list)
    work_sources: list[WorkSource] = Field(default_factory=list)
    expected_facts: list[ExpectedFact] = Field(default_factory=list)
    # Routing evidence gathered by the runner (PLAN §9.5)
    observed_models: list[str] = Field(default_factory=list)
    observed_by_source: dict[str, list[str]] = Field(default_factory=dict)
    evidence_complete: bool

    @model_validator(mode="after")
    def _expectation_matches_shape(self) -> Self:
        if self.expected_behavior != Behavior.ANSWER:
            if self.expected_shape != "none" or self.expected_value is not None or self.expected_table:
                raise ValueError("only 'answer' rows carry an expected value or table (expected_shape 'none')")
            if self.expected_facts:
                raise ValueError("only 'answer' rows carry expected facts")
            return self
        if self.expected_shape == "scalar" and (self.expected_value is None or self.expected_unit is None):
            raise ValueError("a 'scalar' row needs expected_value and expected_unit")
        if self.expected_shape == "table" and (not self.expected_table or self.table_match is None):
            raise ValueError("a 'table' row needs expected_table and table_match")
        if self.expected_shape == "none":
            raise ValueError("an 'answer' row needs expected_shape 'scalar' or 'table'")
        return self


class EvaluatorResult(_Contract):
    """One evaluator's verdict on one attempt (PLAN §9.1 ``eval_score``), from either backend.

    The Foundry backend reads ``score``, ``threshold``, ``passed`` and ``reason`` back from the run's
    output items; the local backend produces the same fields itself. Nothing here re-scores the answer.
    """

    attempt_id: UUID
    evaluator: str  # testing-criterion name, for example "routing_match"
    evaluator_version: str | None = None  # content-addressed evaluator name, the same on both backends (§9.11)
    outcome: Outcome
    score: Decimal | None = None
    threshold: Decimal | None = None
    reason: str = ""


class CaseResult(_Contract):
    """Aggregate over the k attempts of one case on one surface for one persona (PLAN §9.6.5).

    The gate computes it from the evaluator results of the k attempts. ``pass_rate`` and
    ``pass_all_k`` are derived from ``passes`` and ``k`` so they can never disagree; the results
    sink writes them as columns of ``eval_case_result``.
    """

    run_id: UUID
    case_id: CaseId
    surface: str
    persona: Key
    k: int = Field(ge=1)
    passes: int = Field(ge=0)
    value_consistent: bool | None = None
    routing_hits: int = Field(default=0, ge=0)
    decoy_hits: int = Field(default=0, ge=0)
    verdict: Outcome

    @model_validator(mode="after")
    def _passes_within_k(self) -> Self:
        if self.passes > self.k:
            raise ValueError("passes cannot exceed k")
        return self

    @property
    def pass_rate(self) -> Decimal:
        """Share of the k attempts that passed."""
        return Decimal(self.passes) / Decimal(self.k)

    @property
    def pass_all_k(self) -> bool:
        """True when every attempt passed (pass^k, required for critical cases)."""
        return self.passes == self.k
