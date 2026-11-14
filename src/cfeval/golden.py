"""Golden question set: the prompts and what a correct answer looks like (v1 CSV + v2 YAML/JSON)."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

UNITS = (
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
    "",
)
COLUMNS = (
    "id",
    "question",
    "category",
    "expected_artifact",
    "artifact_aliases",
    "expected_model",
    "decoys",
    "expected_value",
    "unit",
    "rel_tol",
    "abs_tol",
    "expected_answer",
    "reference_dax",
    "criticality",
    "notes",
)


@dataclass
class GoldenQuestion:
    id: str
    question: str
    category: str = ""
    expected_artifact: str = ""
    artifact_aliases: str = ""
    expected_model: str = ""
    decoys: str = ""
    expected_value: float | None = None
    unit: str = "number"
    rel_tol: float = 0.005
    abs_tol: float = 0.0
    expected_answer: str = ""
    reference_dax: str = ""
    criticality: str = "standard"
    notes: str = ""
    # v2 additive fields (trailing with defaults to preserve v1 positional arguments)
    expected_artifact_id: str = ""
    case_type: str = "scalar"
    display_tol: float = 0.01
    currency: str = ""
    expect: dict[str, Any] | None = None
    persona: str = ""
    tags: list[str] = field(default_factory=list)
    intent: dict[str, Any] | None = None
    gates: list[str] = field(default_factory=list)
    paraphrases: list[str] = field(default_factory=list)
    paraphrase_of: str = ""
    repeats: int | None = None

    @property
    def model(self) -> str:
        return self.expected_model or self.expected_artifact

    @property
    def expected(self) -> float | None:
        return self.expected_value

    def to_row(self, run_id: str) -> dict[str, Any]:
        return {
            "RunId": run_id,
            "QuestionId": self.id,
            "Question": self.question,
            "Category": self.category,
            "ExpectedArtifact": self.expected_artifact,
            "ArtifactAliases": self.artifact_aliases,
            "ExpectedModel": self.model,
            "Decoys": self.decoys,
            "ExpectedValue": self.expected_value,
            "Unit": self.unit,
            "RelTol": self.rel_tol,
            "AbsTol": self.abs_tol,
            "ExpectedAnswer": self.expected_answer,
            "ReferenceDax": self.reference_dax,
            "Criticality": self.criticality,
            "ExpectedArtifactId": self.expected_artifact_id,
            "CaseType": self.case_type,
            "Persona": self.persona,
            "Tags": "; ".join(self.tags) if self.tags else "",
            "Intent": json.dumps(self.intent, sort_keys=True) if self.intent else "",
            "Gates": "; ".join(self.gates) if self.gates else "",
            "Paraphrase": self.paraphrase_of,
        }


class GoldenSetError(ValueError):
    pass


def sample_golden_path() -> Path:
    """The Contoso sample golden set shipped inside the package."""
    from importlib import resources

    return Path(str(resources.files("cfeval").joinpath("sample/golden_questions.csv")))


def resolve_golden_path(configured: str | Path | None, log: Callable[..., Any] = print) -> Path:
    """The configured golden set, or the bundled sample when the default path does not exist."""
    path = Path(configured) if configured else None
    if path is not None and path.exists():
        return path
    if configured and str(configured) not in ("data/golden/golden_questions.csv", "data\\golden\\golden_questions.csv"):
        raise GoldenSetError(f"golden set not found: {configured}")
    log("Using the bundled Contoso sample golden set (set GOLDEN_SET to use your own).")
    return sample_golden_path()


def _num(value: str | None, name: str, row_id: str, default: float | None = None) -> float | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return default
    try:
        return float(cleaned.replace(",", ""))
    except ValueError as exc:
        raise GoldenSetError(f"{row_id}: {name} must be a number, got {cleaned!r}") from exc


def _load_golden_csv(path: Path) -> list[GoldenQuestion]:
    if not path.exists():
        raise GoldenSetError(f"golden set not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"id", "question"} - set(reader.fieldnames or [])
        if missing:
            raise GoldenSetError("golden set is missing columns: " + ", ".join(sorted(missing)))
        questions: list[GoldenQuestion] = []
        seen: set[str] = set()
        for raw in reader:
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            qid = row.get("id", "")
            if not qid and not row.get("question"):
                continue
            if not qid or not row.get("question"):
                raise GoldenSetError(f"every row needs an id and a question (row {qid or '?'})")
            if qid in seen:
                raise GoldenSetError(f"duplicate id: {qid}")
            seen.add(qid)
            unit = (row.get("unit") or "number").lower()
            if unit not in UNITS:
                raise GoldenSetError(f"{qid}: unit must be one of {', '.join(u for u in UNITS if u)}")
            rel_tol = _num(row.get("rel_tol"), "rel_tol", qid, 0.005)
            abs_tol = _num(row.get("abs_tol"), "abs_tol", qid, 0.0)
            disp_tol = _num(row.get("display_tol"), "display_tol", qid, 0.01)
            tags = [t.strip() for t in row.get("tags", "").split(";") if t.strip()]
            gates = [g.strip() for g in row.get("gates", "").split(";") if g.strip()]
            paraphrases = [p.strip() for p in row.get("paraphrases", "").split("|") if p.strip()]
            questions.append(
                GoldenQuestion(
                    id=qid,
                    question=row["question"],
                    category=row.get("category", ""),
                    expected_artifact=row.get("expected_artifact", ""),
                    artifact_aliases=row.get("artifact_aliases", ""),
                    expected_model=row.get("expected_model", ""),
                    decoys=row.get("decoys", ""),
                    expected_value=_num(row.get("expected_value"), "expected_value", qid),
                    unit=unit,
                    rel_tol=0.005 if rel_tol is None else rel_tol,
                    abs_tol=0.0 if abs_tol is None else abs_tol,
                    expected_answer=row.get("expected_answer", ""),
                    reference_dax=row.get("reference_dax", ""),
                    criticality=row.get("criticality", "") or "standard",
                    notes=row.get("notes", ""),
                    expected_artifact_id=row.get("expected_artifact_id", ""),
                    case_type=(row.get("case_type") or "scalar").lower(),
                    display_tol=0.01 if disp_tol is None else disp_tol,
                    currency=(row.get("currency") or "").upper(),
                    persona=row.get("persona", ""),
                    tags=tags,
                    gates=gates,
                    paraphrases=paraphrases,
                )
            )
    if not questions:
        raise GoldenSetError(f"golden set has no questions: {path}")
    return questions


def load_golden(path: str | Path | None = None, *, expand_paraphrases: bool = False) -> list[GoldenQuestion]:
    """Load and validate a `.csv`, `.yaml`, `.yml`, or `.json` golden set."""
    resolved = sample_golden_path() if path is None else Path(path)
    if not resolved.exists():
        raise GoldenSetError(f"golden set not found: {resolved}")

    suffix = resolved.suffix.lower()
    if suffix in (".yaml", ".yml", ".json"):
        from .golden_v2 import load_golden_v2

        return load_golden_v2(resolved, expand_paraphrases=expand_paraphrases)

    questions = _load_golden_csv(resolved)
    if expand_paraphrases:
        from .golden_v2 import expand_question_paraphrases

        return expand_question_paraphrases(questions)
    return questions


def validate_golden_file(path: str | Path, *, raise_on_error: bool = True) -> dict[str, Any]:
    """Validate a v1/v2 golden question file."""
    from .golden_v2 import validate_golden_file as _validate_v2

    return _validate_v2(path, raise_on_error=raise_on_error)


def golden_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def write_golden(questions: list[GoldenQuestion], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for q in questions:
            d = asdict(q)
            w.writerow({c: ("" if d.get(c) is None else d.get(c)) for c in COLUMNS})
