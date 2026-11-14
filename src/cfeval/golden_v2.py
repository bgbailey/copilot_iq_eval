"""Golden Set Schema v2 validation, loading, linting, and CSV-to-YAML conversion."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .golden import GoldenQuestion, GoldenSetError

SCHEMA_URI = "cfeval.golden/v2"

VALID_CASE_TYPES = frozenset(
    {
        "scalar",
        "numeric",
        "number",
        "ranked_list",
        "set",
        "table",
        "record",
        "abstention",
        "negative",
        "refusal",
        "clarification",
        "direction",
        "citation_only",
        "categorical",
        "text",
        "facts",
    }
)

VALID_UNITS = frozenset(
    {
        "",
        "currency",
        "percent",
        "%",
        "pp",
        "percentage points",
        "bps",
        "basis points",
        "count",
        "number",
        "units",
        "orders",
        "customers",
        "days",
        "hours",
        "headcount",
        "employees",
        "items",
        "ratio",
        "x",
        "usd",
        "eur",
        "gbp",
    }
)

VALID_CURRENCIES = frozenset({"", "USD", "EUR", "GBP", "$", "\u20ac", "\u00a3"})
VALID_CRITICALITIES = frozenset({"standard", "critical", "advisory"})
VALID_GATES = frozenset({"value", "artifact", "model", "why", "judge_answer"})

_TIME_RELATIVE_RE = re.compile(
    r"\b(?:this\s+(?:year|quarter|month|week)|current\s+(?:year|quarter|month)|"
    r"last\s+(?:month|week)|latest|today|yesterday|ytd|mtd|qtd)\b",
    re.I,
)


class GoldenValidationError(GoldenSetError):
    """Raised when a Golden v1/v2 document fails schema or semantic validation."""


def _default_schema_path() -> Path:
    repo_candidate = Path(__file__).resolve().parents[2] / "schemas" / "golden.schema.json"
    if repo_candidate.exists():
        return repo_candidate
    return Path(__file__).resolve().parent / "resources" / "golden.schema.json"


def load_golden_schema(schema_path: str | Path | None = None) -> dict[str, Any]:
    """Load the Draft 2020-12 JSON Schema for golden question suites."""
    path = Path(schema_path) if schema_path is not None else _default_schema_path()
    if not path.exists():
        raise GoldenValidationError(f"golden schema file not found: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise GoldenValidationError(f"invalid golden schema root in {path}")
    return loaded


def _extract_artifact_ref(ref: Any) -> tuple[str, str, list[str]]:
    if ref is None:
        return "", "", []
    if isinstance(ref, str):
        return ref.strip(), "", []
    if isinstance(ref, Mapping):
        name = str(ref.get("name") or "").strip()
        item_id = str(ref.get("id") or "").strip()
        aliases = [str(a).strip() for a in (ref.get("aliases") or []) if str(a).strip()]
        return name, item_id, aliases
    return "", "", []


def _to_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [x.strip() for x in re.split(r"[;|,]", val) if x.strip()]
    if isinstance(val, Sequence):
        out: list[str] = []
        for item in val:
            if isinstance(item, Mapping):
                s = str(item.get("name") or item.get("id") or "").strip()
            else:
                s = str(item).strip()
            if s:
                out.append(s)
        return out
    return []


def _parse_case_to_question(
    raw_case: Mapping[str, Any],
    defaults: Mapping[str, Any],
    errors: list[str],
    index: int,
) -> GoldenQuestion | None:
    qid = str(raw_case.get("id") or "").strip()
    label = qid or f"case[{index}]"
    q_text = str(raw_case.get("question") or "").strip()

    if not qid:
        errors.append(f"{label}: field 'id' is required and must be non-empty")
    if not q_text:
        errors.append(f"{label}: field 'question' is required and must be non-empty")

    exp_block = raw_case.get("expectation") or raw_case.get("expect")
    exp_map: dict[str, Any] = dict(exp_block) if isinstance(exp_block, Mapping) else {}

    raw_ct = raw_case.get("case_type") or exp_map.get("type") or "scalar"
    case_type = str(raw_ct).strip().lower()
    if case_type not in VALID_CASE_TYPES:
        errors.append(f"{label}: invalid case_type {case_type!r}; must be one of {sorted(VALID_CASE_TYPES)}")

    norm_ct = "scalar" if case_type in ("numeric", "number") else case_type

    raw_unit = (
        raw_case.get("unit")
        if raw_case.get("unit") is not None
        else exp_map.get("unit", defaults.get("unit", "number" if norm_ct == "scalar" else ""))
    )
    unit = str(raw_unit or "").strip().lower()
    if unit not in VALID_UNITS:
        errors.append(f"{label}: invalid unit {unit!r}")

    raw_cur = (
        raw_case.get("currency")
        if raw_case.get("currency") is not None
        else exp_map.get("currency", defaults.get("currency", ""))
    )
    currency = str(raw_cur or "").strip().upper()
    if currency in ("$", "\u20ac", "\u00a3"):
        currency = {"$": "USD", "\u20ac": "EUR", "\u00a3": "GBP"}[currency]
    if currency not in VALID_CURRENCIES:
        errors.append(f"{label}: invalid currency {currency!r}")

    def _float_field(field_name: str, val: Any, fallback: float | None) -> float | None:
        if val is None or val == "":
            return fallback
        if isinstance(val, bool):
            errors.append(f"{label}: field '{field_name}' must be a number, got bool")
            return fallback
        try:
            f = float(val)
        except (TypeError, ValueError):
            errors.append(f"{label}: field '{field_name}' must be numeric, got {val!r}")
            return fallback
        if not math.isfinite(f):
            errors.append(f"{label}: field '{field_name}' must be finite, got {val!r}")
            return fallback
        return f

    rel_tol = (
        _float_field(
            "rel_tol",
            raw_case.get("rel_tol", exp_map.get("rel_tol")),
            float(defaults.get("rel_tol", 0.005)),
        )
        or 0.005
    )
    abs_tol_val = _float_field(
        "abs_tol",
        raw_case.get("abs_tol", exp_map.get("abs_tol")),
        float(defaults["abs_tol"]) if defaults.get("abs_tol") is not None else 0.0,
    )
    abs_tol = 0.0 if abs_tol_val is None else abs_tol_val
    display_tol = _float_field(
        "display_tol",
        raw_case.get("display_tol", exp_map.get("display_tol")),
        float(defaults.get("display_tol", 0.01)),
    )
    if display_tol is None:
        display_tol = 0.01

    for t_name, t_val in (("rel_tol", rel_tol), ("abs_tol", abs_tol), ("display_tol", display_tol)):
        if t_val < 0:
            errors.append(f"{label}: field '{t_name}' must be >= 0, got {t_val}")

    raw_exp_val = raw_case.get("expected_value")
    if raw_exp_val is None and "expected" in raw_case and isinstance(raw_case.get("expected"), (int, float)):
        raw_exp_val = raw_case.get("expected")
    if raw_exp_val is None and isinstance(exp_map.get("value"), (int, float)):
        raw_exp_val = exp_map.get("value")

    expected_value: float | None = None
    if raw_exp_val is not None and raw_exp_val != "":
        expected_value = _float_field("expected_value", raw_exp_val, None)

    # Validate expectation-specific requirements
    if norm_ct == "scalar" and expected_value is None and "expected_value" not in raw_case and not exp_map:
        # Allowed only for v1 reference-answer/unscored cases; require value if expectation block exists
        if "expectation" in raw_case or "case_type" in raw_case:
            errors.append(f"{label}: scalar/numeric case requires a numeric 'expected_value' or 'expectation.value'")
    elif norm_ct in ("ranked_list", "set"):
        items = exp_map.get("items")
        if not isinstance(items, list) or len(items) == 0:
            errors.append(f"{label}: {norm_ct} case requires non-empty 'expect.items' list")
    elif norm_ct == "table":
        rows = exp_map.get("rows")
        if not isinstance(rows, list) or len(rows) == 0:
            errors.append(f"{label}: table case requires non-empty 'expect.rows' list")
    elif norm_ct == "record":
        fields = exp_map.get("fields")
        if not isinstance(fields, Mapping) or len(fields) == 0:
            errors.append(f"{label}: record case requires non-empty 'expect.fields' mapping")
    elif norm_ct == "direction":
        d_val = str(exp_map.get("direction") or raw_case.get("expected") or "").strip().lower()
        if d_val not in ("up", "down", "flat"):
            errors.append(f"{label}: direction case requires 'expect.direction' in ('up', 'down', 'flat')")
    elif norm_ct == "categorical":
        cat_val = exp_map.get("value") if exp_map.get("value") is not None else raw_case.get("expected")
        if not cat_val and not exp_map.get("aliases"):
            errors.append(f"{label}: categorical case requires 'expect.value' or 'expected'")

    criticality = str(raw_case.get("criticality") or defaults.get("criticality") or "standard").strip().lower()
    if criticality not in VALID_CRITICALITIES:
        errors.append(f"{label}: invalid criticality {criticality!r}")

    raw_routing = raw_case.get("routing")
    routing: dict[str, Any] = dict(raw_routing) if isinstance(raw_routing, Mapping) else {}
    r_model_name, _, _ = _extract_artifact_ref(routing.get("expected_model"))
    expected_model = str(raw_case.get("expected_model") or r_model_name or "").strip()

    expected_artifact = str(raw_case.get("expected_artifact") or "").strip()
    expected_artifact_id = str(raw_case.get("expected_artifact_id") or "").strip()
    aliases_list = _to_str_list(raw_case.get("artifact_aliases")) + _to_str_list(routing.get("aliases"))

    if routing.get("expected_artifact") is not None:
        ra_name, ra_id, ra_aliases = _extract_artifact_ref(routing.get("expected_artifact"))
        expected_artifact = expected_artifact or ra_name
        expected_artifact_id = expected_artifact_id or ra_id
        aliases_list.extend(ra_aliases)

    if isinstance(routing.get("expected_artifacts"), list) and routing["expected_artifacts"]:
        first_art = routing["expected_artifacts"][0]
        fa_name, fa_id, fa_aliases = _extract_artifact_ref(first_art)
        expected_artifact = expected_artifact or fa_name
        expected_artifact_id = expected_artifact_id or fa_id
        aliases_list.extend(fa_aliases)
        for extra_art in routing["expected_artifacts"][1:]:
            ea_name, _, ea_aliases = _extract_artifact_ref(extra_art)
            if ea_name:
                aliases_list.append(ea_name)
            aliases_list.extend(ea_aliases)

    decoys_list = _to_str_list(raw_case.get("decoys")) + _to_str_list(routing.get("decoys"))
    gates_list = _to_str_list(raw_case.get("gates") if "gates" in raw_case else defaults.get("gates"))
    for g in gates_list:
        if g not in VALID_GATES:
            errors.append(f"{label}: invalid gate {g!r}; must be one of {sorted(VALID_GATES)}")

    paraphrases_raw = raw_case.get("paraphrases") or []
    paraphrases: list[str] = []
    if isinstance(paraphrases_raw, list):
        for p in paraphrases_raw:
            ps = str(p or "").strip()
            if not ps:
                errors.append(f"{label}: paraphrase entries must be non-empty strings")
            else:
                paraphrases.append(ps)
    elif paraphrases_raw:
        errors.append(f"{label}: 'paraphrases' must be a list of strings")

    tags_list = _to_str_list(raw_case.get("tags"))
    persona = str(raw_case.get("persona") or defaults.get("persona") or "").strip()
    intent_raw = raw_case.get("intent")
    intent = dict(intent_raw) if isinstance(intent_raw, Mapping) else None

    repeats_raw = raw_case.get("repeats", defaults.get("repeats"))
    repeats: int | None = None
    if repeats_raw is not None:
        if isinstance(repeats_raw, bool) or not isinstance(repeats_raw, int) or repeats_raw < 1:
            errors.append(f"{label}: 'repeats' must be an integer >= 1")
        else:
            repeats = repeats_raw

    expected_answer = str(raw_case.get("expected_answer") or exp_map.get("reference_answer") or "").strip()
    reference_dax = str(raw_case.get("reference_dax") or exp_map.get("reference_dax") or "").strip()

    if errors:
        return None

    return GoldenQuestion(
        id=qid,
        question=q_text,
        category=str(raw_case.get("category") or "").strip(),
        expected_artifact=expected_artifact,
        artifact_aliases="; ".join(dict.fromkeys(aliases_list)),
        expected_model=expected_model,
        decoys="; ".join(dict.fromkeys(decoys_list)),
        expected_value=expected_value,
        unit=unit or ("number" if norm_ct == "scalar" else ""),
        rel_tol=rel_tol,
        abs_tol=abs_tol,
        expected_answer=expected_answer,
        reference_dax=reference_dax,
        criticality=criticality,
        notes=str(raw_case.get("notes") or "").strip(),
        expected_artifact_id=expected_artifact_id,
        case_type=norm_ct,
        display_tol=display_tol,
        currency=currency,
        expect=exp_map if exp_map else None,
        persona=persona,
        tags=tags_list,
        intent=intent,
        gates=gates_list,
        paraphrases=paraphrases,
        repeats=repeats,
    )


def _lint_questions(questions: Sequence[GoldenQuestion], as_of: str = "") -> list[str]:
    warnings: list[str] = []
    if len(questions) < 20:
        warnings.append(f"suite has {len(questions)} cases (recommended >= 20 for stable intervals)")

    seen_norm_q: dict[str, str] = {}
    for q in questions:
        if q.case_type == "scalar" and not q.reference_dax:
            warnings.append(f"{q.id}: missing reference_dax for scalar expectation")
        if q.expected_artifact and not q.expected_artifact_id:
            warnings.append(f"{q.id}: name-only routing expectation without expected_artifact_id")
        if _TIME_RELATIVE_RE.search(q.question) and not as_of and not (q.intent or {}).get("as_of"):
            warnings.append(f"{q.id}: time-relative wording in question without 'as_of' date")
        if q.criticality == "critical" and q.repeats is not None and q.repeats < 3:
            warnings.append(f"{q.id}: critical case has repeats={q.repeats} (recommended >= 3)")
        nq = " ".join(re.sub(r"[^0-9a-z]+", " ", q.question.lower()).split())
        if nq in seen_norm_q:
            warnings.append(f"{q.id}: near-duplicate question text with {seen_norm_q[nq]}")
        else:
            seen_norm_q[nq] = q.id
    return warnings


def validate_golden_dict(
    data: Any,
    *,
    source: str = "<memory>",
    raise_on_error: bool = True,
) -> dict[str, Any]:
    """Validate an in-memory Golden v1/v2 dictionary or list against JSON Schema and semantic rules."""
    errors: list[str] = []

    schema_path = _default_schema_path()
    if not schema_path.exists():
        errors.append(f"golden schema file not found: {schema_path}")
    else:
        try:
            import jsonschema  # type: ignore[import-untyped]

            schema = load_golden_schema(schema_path)
            validator = jsonschema.Draft202012Validator(schema)
            for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
                loc = ".".join(str(p) for p in err.path) or "<root>"
                # Include case ID if error occurred inside cases/questions[idx]
                case_prefix = ""
                path_list = list(err.path)
                if (
                    len(path_list) >= 2
                    and path_list[0] in ("cases", "questions")
                    and isinstance(path_list[1], int)
                    and isinstance(data, Mapping)
                ):
                    arr = data.get(str(path_list[0]))
                    idx_1 = path_list[1]
                    if isinstance(arr, list) and 0 <= idx_1 < len(arr) and isinstance(arr[idx_1], Mapping):
                        cid = arr[idx_1].get("id")
                        if cid:
                            case_prefix = f"{cid} ({loc})"
                elif len(path_list) >= 1 and isinstance(path_list[0], int) and isinstance(data, list):
                    idx = path_list[0]
                    if 0 <= idx < len(data) and isinstance(data[idx], Mapping) and data[idx].get("id"):
                        case_prefix = f"{data[idx]['id']} ({loc})"
                errors.append(f"{case_prefix or loc}: {err.message}")
        except ImportError:
            pass

    defaults: dict[str, Any] = {}
    as_of = ""
    raw_cases: list[Any] = []

    if isinstance(data, list):
        raw_cases = data
    elif isinstance(data, Mapping):
        if "cases" in data and "questions" in data:
            errors.append("<root>: specify either 'cases' or 'questions', not both")
        cases_val = data.get("cases") if "cases" in data else data.get("questions")
        if not isinstance(cases_val, list) or len(cases_val) == 0:
            errors.append("<root>: golden suite must contain a non-empty 'cases' or 'questions' list")
        else:
            raw_cases = cases_val
        if isinstance(data.get("defaults"), Mapping):
            defaults = dict(data["defaults"])
        as_of = str(data.get("as_of") or "").strip()
    else:
        errors.append(f"{source}: golden root must be an object or non-empty list")

    questions: list[GoldenQuestion] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(raw_cases):
        if not isinstance(item, Mapping):
            errors.append(f"case[{idx}]: each entry must be a mapping/object")
            continue
        qid = str(item.get("id") or "").strip()
        if qid:
            if qid in seen_ids:
                errors.append(f"{qid}: duplicate question id {qid!r}")
            seen_ids.add(qid)
        case_errors: list[str] = []
        q = _parse_case_to_question(item, defaults, case_errors, idx)
        errors.extend(case_errors)
        if q is not None:
            for p_idx, _ in enumerate(q.paraphrases, start=1):
                pid = f"{q.id}__p{p_idx}"
                if pid in seen_ids:
                    errors.append(f"{q.id}: expanded paraphrase id {pid!r} collides with an existing id")
                seen_ids.add(pid)
            questions.append(q)

    warnings = _lint_questions(questions, as_of=as_of) if not errors else []

    if errors and raise_on_error:
        raise GoldenValidationError(f"Invalid golden set ({source}): " + "; ".join(errors))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "count": len(questions),
        "questions": questions,
    }


def validate_golden_file(path: str | Path, *, raise_on_error: bool = True) -> dict[str, Any]:
    """Validate a `.yaml`, `.yml`, `.json`, or `.csv` golden file."""
    file_path = Path(path)
    if not file_path.exists():
        msg = f"golden set not found: {file_path}"
        if raise_on_error:
            raise GoldenValidationError(msg)
        return {"valid": False, "errors": [msg], "warnings": [], "count": 0, "questions": []}

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        from .golden import _load_golden_csv

        try:
            qs = _load_golden_csv(file_path)
            warnings = _lint_questions(qs)
            return {"valid": True, "errors": [], "warnings": warnings, "count": len(qs), "questions": qs}
        except GoldenSetError as exc:
            if raise_on_error:
                raise GoldenValidationError(str(exc)) from exc
            return {"valid": False, "errors": [str(exc)], "warnings": [], "count": 0, "questions": []}

    raw_text = file_path.read_text(encoding="utf-8")
    try:
        if suffix == ".json":
            parsed = json.loads(raw_text)
        elif suffix in (".yaml", ".yml"):
            import yaml

            parsed = yaml.safe_load(raw_text)
        else:
            raise GoldenValidationError(f"unsupported golden file extension {suffix!r} for {file_path}")
    except GoldenValidationError:
        if raise_on_error:
            raise
        return {
            "valid": False,
            "errors": [f"unsupported extension: {suffix}"],
            "warnings": [],
            "count": 0,
            "questions": [],
        }
    except Exception as exc:
        msg = f"failed to parse {file_path}: {exc}"
        if raise_on_error:
            raise GoldenValidationError(msg) from exc
        return {"valid": False, "errors": [msg], "warnings": [], "count": 0, "questions": []}

    return validate_golden_dict(parsed, source=str(file_path), raise_on_error=raise_on_error)


def expand_question_paraphrases(questions: Sequence[GoldenQuestion]) -> list[GoldenQuestion]:
    """Expand each question's `paraphrases` into additional `GoldenQuestion` items (`<id>__p1`, ...)."""
    expanded: list[GoldenQuestion] = []
    for q in questions:
        expanded.append(q)
        for idx, para in enumerate(q.paraphrases, start=1):
            expanded.append(
                replace(
                    q,
                    id=f"{q.id}__p{idx}",
                    question=para,
                    paraphrases=[],
                    paraphrase_of=q.id,
                )
            )
    return expanded


def load_golden_v2(path: str | Path, *, expand_paraphrases: bool = False) -> list[GoldenQuestion]:
    """Validate and load a Golden v2 YAML/JSON file into `GoldenQuestion` objects."""
    res = validate_golden_file(path, raise_on_error=True)
    questions: list[GoldenQuestion] = list(res["questions"])
    if expand_paraphrases:
        return expand_question_paraphrases(questions)
    return questions


def lint_golden_file(path: str | Path) -> list[str]:
    """Validate a golden file and return lint warnings."""
    res = validate_golden_file(path, raise_on_error=True)
    return list(res["warnings"])


def convert_csv_to_yaml(csv_path: str | Path, yaml_path: str | Path | None = None) -> str:
    """Convert a v1 CSV golden set into canonical Golden v2 YAML."""
    import yaml

    from .golden import _load_golden_csv

    questions = _load_golden_csv(Path(csv_path))
    cases: list[dict[str, Any]] = []
    for q in questions:
        expectation: dict[str, Any] = {
            "type": "numeric" if q.case_type == "scalar" else q.case_type,
            "value": q.expected_value,
            "unit": q.unit,
            "rel_tol": q.rel_tol,
            "abs_tol": q.abs_tol,
            "display_tol": q.display_tol,
        }
        if q.currency:
            expectation["currency"] = q.currency
        if q.reference_dax:
            expectation["reference_dax"] = q.reference_dax
        if q.expected_answer:
            expectation["reference_answer"] = q.expected_answer

        routing: dict[str, Any] = {
            "expected_model": {"name": q.model or None, "id": None},
            "expected_artifacts": [{"name": q.expected_artifact or None, "id": q.expected_artifact_id or None}]
            if (q.expected_artifact or q.expected_artifact_id)
            else [],
        }
        aliases = _to_str_list(q.artifact_aliases)
        if aliases:
            routing["aliases"] = aliases
        decoys = _to_str_list(q.decoys)
        if decoys:
            routing["decoys"] = [{"name": d} for d in decoys]

        case_entry: dict[str, Any] = {
            "id": q.id,
            "question": q.question,
            "category": q.category,
            "criticality": q.criticality,
            "expectation": expectation,
            "routing": routing,
        }
        if q.notes:
            case_entry["notes"] = q.notes
        cases.append(case_entry)

    doc = {
        "schema": SCHEMA_URI,
        "defaults": {"repeats": 1, "rel_tol": 0.005, "display_tol": 0.01},
        "cases": cases,
    }
    rendered: str = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    if yaml_path is not None:
        Path(yaml_path).write_text(rendered, encoding="utf-8")
    return rendered
