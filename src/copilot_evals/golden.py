"""Load and check the golden set (PLAN §5).

``load_golden_set`` parses ``cases.yaml``, ``personas.yaml`` and ``models.yaml`` into the typed
contracts in ``copilot_evals.schemas``. ``check_golden_set`` then runs the checks that span files,
which no single model can do on its own: every persona, model and document key must exist, case
IDs must be unique, and a decoy must never be expected.

Both functions are offline (no tenant, network or credentials), so CI runs them on every push via
``evals validate``. Resolving model keys to Fabric ItemIds is an online step added by P2.2.
"""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from copilot_evals.schemas import Case, Criticality, DocumentRef, DocumentRole, Persona, SemanticModelRef

CASES_FILE = "cases.yaml"
PERSONAS_FILE = "personas.yaml"
MODELS_FILE = "models.yaml"

#: Critical cases must pass k of k attempts (PLAN §3.4); fewer than this many runs is too weak a proof.
MIN_CRITICAL_RUNS = 3

_CASES = TypeAdapter(list[Case])
_ENTRIES = TypeAdapter(dict[str, dict[str, Any]])


class _ModelsFile(BaseModel):
    """Top-level shape of ``models.yaml``: semantic models plus seeded documents (work sources and decoys)."""

    model_config = ConfigDict(extra="forbid")

    models: dict[str, dict[str, Any]]
    documents: dict[str, dict[str, Any]] = Field(default_factory=dict)


class GoldenSetError(Exception):
    """A golden-set file is missing, is not valid YAML, or does not match its schema."""


class Severity(StrEnum):
    """Severity of a golden-set finding. Errors fail ``evals validate``; warnings fail it with ``--strict``."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One problem found by ``check_golden_set``."""

    severity: Severity
    where: str
    message: str


@dataclass(frozen=True)
class GoldenSet:
    """The parsed golden set: cases plus the personas, models and documents they refer to."""

    cases: tuple[Case, ...]
    personas: dict[str, Persona]
    models: dict[str, SemanticModelRef]
    documents: dict[str, DocumentRef]


def load_golden_set(golden_dir: Path) -> GoldenSet:
    """Parse the golden-set files in ``golden_dir`` into typed models.

    Args:
        golden_dir: Folder that holds ``cases.yaml``, ``personas.yaml`` and ``models.yaml``.

    Returns:
        The parsed golden set. Cross-file references are not checked here; see ``check_golden_set``.

    Raises:
        GoldenSetError: A file is missing, is not valid YAML, or fails schema validation.
    """
    cases_path = golden_dir / CASES_FILE
    personas_path = golden_dir / PERSONAS_FILE
    models_path = golden_dir / MODELS_FILE

    try:
        cases = tuple(_CASES.validate_python(_read_yaml(cases_path)))
    except ValidationError as exc:
        raise GoldenSetError(f"{cases_path}: {exc}") from exc

    try:
        personas = {
            key: Persona.model_validate({**fields, "key": key})
            for key, fields in _ENTRIES.validate_python(_read_yaml(personas_path)).items()
        }
    except ValidationError as exc:
        raise GoldenSetError(f"{personas_path}: {exc}") from exc

    try:
        models_file = _ModelsFile.model_validate(_read_yaml(models_path))
        models = {
            key: SemanticModelRef.model_validate({**fields, "key": key}) for key, fields in models_file.models.items()
        }
        documents = {
            key: DocumentRef.model_validate({**fields, "key": key}) for key, fields in models_file.documents.items()
        }
    except ValidationError as exc:
        raise GoldenSetError(f"{models_path}: {exc}") from exc

    return GoldenSet(cases=cases, personas=personas, models=models, documents=documents)


def check_golden_set(golden: GoldenSet) -> list[Finding]:
    """Run the cross-file checks on a parsed golden set.

    Args:
        golden: The output of ``load_golden_set``.

    Returns:
        Findings in file order; an empty list means the golden set is consistent.
    """
    findings: list[Finding] = []
    first_index: dict[str, int] = {}
    first_prompt: dict[tuple[str, str], str] = {}

    for index, case in enumerate(golden.cases):
        where = f"{CASES_FILE}[{index}] {case.id}"
        problems = _check_case(case, golden)

        if case.id in first_index:
            problems.append((Severity.ERROR, f"duplicate case id; first used at {CASES_FILE}[{first_index[case.id]}]"))
        else:
            first_index[case.id] = index

        prompt_key = (case.persona, case.prompt.strip().lower())
        if prompt_key in first_prompt:
            problems.append(
                (Severity.WARNING, f"same prompt and persona as {first_prompt[prompt_key]}; merge or vary them")
            )
        else:
            first_prompt[prompt_key] = case.id

        findings.extend(Finding(severity, where, message) for severity, message in problems)

    model_workspaces = {model.workspace for model in golden.models.values()}
    for key, persona in golden.personas.items():
        for workspace in persona.workspaces:
            if workspace not in model_workspaces:
                message = f"workspace '{workspace}' holds none of the models in {MODELS_FILE}"
                findings.append(Finding(Severity.WARNING, f"{PERSONAS_FILE} {key}", message))

    return findings


def _check_case(case: Case, golden: GoldenSet) -> list[tuple[Severity, str]]:
    """Checks that need only one case and the reference files (personas, models, documents)."""
    problems: list[tuple[Severity, str]] = []
    decoy_models = {key for key, model in golden.models.items() if model.decoy}

    if case.persona not in golden.personas:
        problems.append((Severity.ERROR, f"unknown persona '{case.persona}' (not in {PERSONAS_FILE})"))

    for key in [*case.expect.models, *case.expect.decoys]:
        if key not in golden.models:
            problems.append((Severity.ERROR, f"unknown model '{key}' (not in {MODELS_FILE})"))

    for key in case.expect.doc_decoys:
        if key not in golden.documents:
            problems.append((Severity.ERROR, f"unknown document decoy '{key}' (not in {MODELS_FILE} documents)"))
        elif golden.documents[key].role != DocumentRole.DECOY:
            problems.append((Severity.ERROR, f"document '{key}' is a work source, not a decoy"))

    for key in case.expect.work_sources:
        if key not in golden.documents:
            problems.append((Severity.ERROR, f"unknown work source '{key}' (not in {MODELS_FILE} documents)"))
        elif golden.documents[key].role != DocumentRole.SOURCE:
            problems.append((Severity.ERROR, f"document '{key}' is a decoy and can't be a work source"))

    for ref in case.expect.work_facts:
        document, _, fact = ref.partition(".")
        if document not in golden.documents or fact not in golden.documents[document].facts:
            problems.append((Severity.ERROR, f"unknown work fact '{ref}' (not in {MODELS_FILE} documents)"))
        elif document not in case.expect.work_sources:
            problems.append((Severity.ERROR, f"work fact '{ref}' comes from a document missing from work_sources"))

    for key in sorted(set(case.expect.models) & decoy_models):
        problems.append((Severity.ERROR, f"decoy model '{key}' is listed as an expected model"))

    if case.criticality == Criticality.CRITICAL and case.runs < MIN_CRITICAL_RUNS:
        message = f"critical case runs {case.runs} time(s); use at least {MIN_CRITICAL_RUNS} for pass^k"
        problems.append((Severity.WARNING, message))

    for text, count in Counter([case.prompt, *case.paraphrases]).items():
        if count > 1:
            problems.append((Severity.WARNING, f"prompt or paraphrase repeated {count} times: '{text}'"))

    return problems


def _read_yaml(path: Path) -> Any:
    """Read one YAML file, turning missing files and syntax errors into ``GoldenSetError``."""
    if not path.is_file():
        raise GoldenSetError(f"missing golden-set file: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise GoldenSetError(f"{path}: invalid YAML: {exc}") from exc
