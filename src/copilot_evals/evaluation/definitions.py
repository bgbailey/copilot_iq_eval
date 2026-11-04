"""Load and check the evaluation definitions in ``evals/evaluators/`` (PLAN §9.6, §9.11, §9.12).

One set of evaluators serves both evaluation backends (ADR-009): Microsoft Foundry Evaluations runs
them in the cloud, and the local backend runs the same files in the harness process. This module
never calls a backend and never scores an answer. It loads the catalog and the eval definition and
checks, before anything runs, that:

* every code-based evaluator is a self-contained ``grade(sample, item)`` function that fits the
  Foundry sandbox: under 256 KB, importing only the standard library or the sandbox packages, and
  reading only dataset-row fields that exist and that it declares in ``evaluators.yaml``. The rules
  apply on the local backend too, so every evaluator runs unchanged on either backend;
* every prompt-based evaluator's ``{{variables}}`` match its declared inputs and its data mapping;
* every field a testing criterion or the extraction template reads exists in the item schema;
* no prompt shown to an LLM (the judge or the extraction step) can see the expected answer.

``evals validate`` runs these checks in CI. ``catalog_name`` gives each evaluator the
content-addressed name that the Foundry backend registers and both backends record as its version.
"""

import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from copilot_evals.golden import Finding, Severity

EVALUATORS_FILE = "evaluators.yaml"
DEFINITION_FILE = "eval-definition.yaml"

#: Foundry limit on the code of a code-based evaluator (config/contracts.yaml: foundry_evaluations).
MAX_CODE_BYTES = 256 * 1024

#: Third-party packages in the Foundry code-evaluator sandbox, by import name.
SANDBOX_PACKAGES = frozenset(
    {
        "deepdiff",
        "jsonschema",
        "nltk",
        "numpy",
        "pandas",
        "pydantic",
        "rapidfuzz",
        "rouge_score",
        "scipy",
        "sklearn",
        "sympy",
        "yaml",
    }
)

#: Fields of Foundry's generated sample that evaluators and templates may reference.
SAMPLE_FIELDS = frozenset({"output_text", "output_items"})

EVALUATOR_TYPES = frozenset({"code", "prompt"})

_ITEM_REF = re.compile(r"\{\{\s*item\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_SAMPLE_REF = re.compile(r"\{\{\s*sample\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_TEMPLATE_VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_CATALOG_REF = re.compile(r"^\{catalog:([a-z][a-z0-9_]*)\}$")
_FILE_REF = re.compile(r"^\{file:([^{}]+)\}$")


class DefinitionError(Exception):
    """An evaluation definition file is missing, is not valid YAML, or has the wrong overall shape."""


@dataclass(frozen=True)
class EvaluatorSpec:
    """One entry of ``evaluators.yaml``."""

    key: str
    kind: str  # "code" or "prompt"
    source: Path
    fields: dict[str, Any]

    @property
    def declared(self) -> list[str]:
        """``reads`` for a code-based evaluator, ``inputs`` for a prompt-based one."""
        names = self.fields.get("reads" if self.kind == "code" else "inputs") or []
        return [str(name) for name in names]


@dataclass(frozen=True)
class EvaluationDefinitions:
    """The parsed contents of ``evals/evaluators/``."""

    root: Path
    name_prefix: str
    evaluators: dict[str, EvaluatorSpec]
    definition: dict[str, Any]

    @property
    def item_fields(self) -> set[str]:
        """Field names of the dataset row (``data_source_config.item_schema.properties``)."""
        config = self.definition.get("data_source_config")
        schema = config.get("item_schema") if isinstance(config, dict) else None
        properties = schema.get("properties") if isinstance(schema, dict) else None
        return {str(name) for name in properties} if isinstance(properties, dict) else set()

    @property
    def blind_fields(self) -> set[str]:
        """Fields that must never reach an LLM (``judge_blind_fields``)."""
        return {str(name) for name in self.definition.get("judge_blind_fields") or []}

    @property
    def criteria(self) -> list[dict[str, Any]]:
        """The testing criteria, in file order."""
        criteria = self.definition.get("testing_criteria") or []
        return [criterion for criterion in criteria if isinstance(criterion, dict)]

    def spec_for(self, criterion: dict[str, Any]) -> EvaluatorSpec | None:
        """The catalog entry a testing criterion refers to, or None if its evaluator_name is not a catalog reference."""
        key = _catalog_key(criterion)
        return self.evaluators.get(key) if key else None

    def resolve_file(self, value: str) -> str:
        """The text of the file a ``{file:<path>}`` placeholder names; any other string is returned unchanged."""
        match = _FILE_REF.match(value)
        return (self.root / match.group(1)).read_text(encoding="utf-8") if match else value


def catalog_name(definitions: EvaluationDefinitions, key: str) -> str:
    """The content-addressed name of evaluator ``key``: ``<name_prefix><key>_<first 8 hex digits>``.

    The SHA-256 covers the evaluator's source file and its catalog entry, so changing either gives a
    new name. The Foundry backend registers the evaluator under this name (P2.7), and both backends
    record it as ``EvaluatorResult.evaluator_version``, so results from the two backends can be
    compared version by version. ``.gitattributes`` checks files out with LF line endings, so the name
    is the same on every operating system.
    """
    spec = definitions.evaluators[key]
    digest = hashlib.sha256(spec.source.read_bytes())
    digest.update(json.dumps(spec.fields, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
    return f"{definitions.name_prefix}{key}_{digest.hexdigest()[:8]}"


def load_definitions(root: Path) -> EvaluationDefinitions:
    """Load ``evaluators.yaml`` and ``eval-definition.yaml`` from ``root``.

    Raises:
        DefinitionError: A file is missing, is not valid YAML, or lacks its top-level sections.
    """
    catalog = _read_mapping(root / EVALUATORS_FILE)
    definition = _read_mapping(root / DEFINITION_FILE)
    entries = catalog.get("evaluators")
    if not isinstance(entries, dict) or not entries:
        raise DefinitionError(f"{root / EVALUATORS_FILE}: 'evaluators' must be a non-empty mapping")
    for section in ("data_source_config", "testing_criteria", "run_data_source"):
        if section not in definition:
            raise DefinitionError(f"{root / DEFINITION_FILE}: missing '{section}'")

    evaluators: dict[str, EvaluatorSpec] = {}
    for key, fields in entries.items():
        if not isinstance(fields, dict):
            raise DefinitionError(f"{root / EVALUATORS_FILE}: evaluator '{key}' must be a mapping")
        evaluators[str(key)] = EvaluatorSpec(
            key=str(key), kind=str(fields.get("type")), source=root / str(fields.get("source")), fields=fields
        )
    return EvaluationDefinitions(
        root=root, name_prefix=str(catalog.get("name_prefix") or ""), evaluators=evaluators, definition=definition
    )


def check_definitions(definitions: EvaluationDefinitions) -> list[Finding]:
    """Run every offline check on the parsed definitions.

    Returns:
        Findings in file order; an empty list means the definitions are ready to register.
    """
    findings: list[Finding] = []
    for spec in definitions.evaluators.values():
        where = f"{EVALUATORS_FILE} {spec.key}"
        if spec.kind not in EVALUATOR_TYPES:
            findings.append(Finding(Severity.ERROR, where, f"type must be one of {sorted(EVALUATOR_TYPES)}"))
        elif not spec.source.is_file():
            findings.append(Finding(Severity.ERROR, where, f"source file not found: {spec.source}"))
        else:
            check = _check_code if spec.kind == "code" else _check_prompt_source
            findings += [Finding(Severity.ERROR, where, message) for message in check(spec, definitions)]

    findings += _check_criteria(definitions)
    findings += _check_run_data_source(definitions)
    return findings


def item_keys_read(tree: ast.AST) -> set[str]:
    """String keys that code reads from ``item``, as ``item.get("x")`` or ``item["x"]``."""
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "item"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "item"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _check_code(spec: EvaluatorSpec, definitions: EvaluationDefinitions) -> list[str]:
    """Sandbox and data-contract checks for one code-based evaluator."""
    code = spec.source.read_bytes()
    if len(code) >= MAX_CODE_BYTES:
        return [f"source is {len(code)} bytes; Foundry accepts less than {MAX_CODE_BYTES}"]
    try:
        tree = ast.parse(code, filename=str(spec.source))
    except SyntaxError as exc:
        return [f"source does not parse: {exc}"]

    problems: list[str] = []
    grade = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "grade"]
    if not grade:
        problems.append("source must define a top-level function grade(sample, item)")
    elif [argument.arg for argument in grade[0].args.args] != ["sample", "item"]:
        problems.append("grade() must take exactly two parameters: (sample, item)")

    for name in sorted(_disallowed_imports(tree)):
        problems.append(f"import not available in the Foundry sandbox: {name}")

    declared = set(spec.declared)
    for key in sorted(item_keys_read(tree) - declared):
        problems.append(f"reads '{key}' but does not declare it in 'reads'")
    for key in sorted(declared - definitions.item_fields - {"sample"}):
        problems.append(f"declares '{key}', which is not in the item schema")
    return problems


def _disallowed_imports(tree: ast.AST) -> set[str]:
    """Top-level module names imported by the code that the sandbox does not provide."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
    allowed = set(sys.stdlib_module_names) | SANDBOX_PACKAGES
    return {module for module in modules if module.startswith(".") or module.split(".")[0] not in allowed}


def _check_prompt_source(spec: EvaluatorSpec, definitions: EvaluationDefinitions) -> list[str]:
    """The prompt's {{variables}} must be exactly the declared inputs, and none may be a blind field."""
    variables = set(_TEMPLATE_VAR.findall(spec.source.read_text(encoding="utf-8")))
    declared = set(spec.declared)
    problems = [f"prompt uses {{{{{name}}}}} but 'inputs' does not declare it" for name in sorted(variables - declared)]
    problems += [f"declares input '{name}', which the prompt never uses" for name in sorted(declared - variables)]
    for name in sorted(declared & definitions.blind_fields):
        problems.append(f"input '{name}' would show the expected answer to the judge")
    return problems


def _check_criteria(definitions: EvaluationDefinitions) -> list[Finding]:
    """Each testing criterion must name a catalog evaluator and map only fields that exist."""
    findings: list[Finding] = []
    names: set[str] = set()
    for index, criterion in enumerate(definitions.criteria):
        where = f"{DEFINITION_FILE} testing_criteria[{index}] {criterion.get('name')}"

        def error(message: str, where: str = where) -> None:
            findings.append(Finding(Severity.ERROR, where, message))

        name = str(criterion.get("name"))
        if name in names:
            error("duplicate criterion name")
        names.add(name)
        if criterion.get("type") != "azure_ai_evaluator":
            error("type must be 'azure_ai_evaluator'")

        match = _CATALOG_REF.match(str(criterion.get("evaluator_name")))
        spec = definitions.evaluators.get(match.group(1)) if match else None
        if spec is None:
            error("evaluator_name must be '{catalog:<key>}' with a key from evaluators.yaml")
            continue

        parameters = criterion.get("initialization_parameters") or {}
        threshold = "pass_threshold" if spec.kind == "code" else "threshold"
        for required in ("deployment_name", threshold):
            if required not in parameters:
                error(f"initialization_parameters needs '{required}' for a {spec.kind}-based evaluator")

        mapping = {str(key): str(value) for key, value in (criterion.get("data_mapping") or {}).items()}
        if spec.kind == "prompt" and set(mapping) != set(spec.declared):
            error(f"data_mapping keys must be the prompt inputs {sorted(spec.declared)}")
        for target in mapping.values():
            for message in _check_template_refs(target, definitions, llm_facing=spec.kind == "prompt"):
                error(message)

    used = {_catalog_key(criterion) for criterion in definitions.criteria}
    for key in sorted(set(definitions.evaluators) - used):
        findings.append(Finding(Severity.WARNING, f"{EVALUATORS_FILE} {key}", "evaluator is not used by any criterion"))
    return findings


def _check_run_data_source(definitions: EvaluationDefinitions) -> list[Finding]:
    """The extraction template may read only existing, non-blind fields; referenced files must exist."""
    findings: list[Finding] = []
    where = f"{DEFINITION_FILE} run_data_source"
    for text in _strings_in(definitions.definition.get("run_data_source")):
        file_ref = _FILE_REF.match(text)
        if file_ref:
            path = definitions.root / file_ref.group(1)
            if not path.is_file():
                findings.append(Finding(Severity.ERROR, where, f"file not found: {path}"))
                continue
            text = path.read_text(encoding="utf-8")
        for message in _check_template_refs(text, definitions, llm_facing=True):
            findings.append(Finding(Severity.ERROR, where, message))
    return findings


def _check_template_refs(text: str, definitions: EvaluationDefinitions, *, llm_facing: bool) -> list[str]:
    """Problems with the {{item.x}} and {{sample.x}} references in one template string."""
    item_refs = set(_ITEM_REF.findall(text))
    problems = [f"unknown item field '{name}'" for name in sorted(item_refs - definitions.item_fields)]
    problems += [f"unknown sample field '{name}'" for name in sorted(set(_SAMPLE_REF.findall(text)) - SAMPLE_FIELDS)]
    if llm_facing:
        for name in sorted(item_refs & definitions.blind_fields):
            problems.append(f"'{name}' would show the expected answer to an LLM")
    return problems


def _catalog_key(criterion: dict[str, Any]) -> str | None:
    """The evaluators.yaml key a criterion refers to, or None if its evaluator_name is not a catalog reference."""
    match = _CATALOG_REF.match(str(criterion.get("evaluator_name")))
    return match.group(1) if match else None


def _strings_in(value: Any) -> list[str]:
    """Every string nested anywhere in a YAML value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _strings_in(child)]
    if isinstance(value, list):
        return [text for child in value for text in _strings_in(child)]
    return []


def _read_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file whose top level must be a mapping."""
    if not path.is_file():
        raise DefinitionError(f"missing evaluation definition file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DefinitionError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DefinitionError(f"{path}: the top level must be a mapping")
    return data
