"""Golden question set: the prompts and what a correct answer looks like."""
import csv
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

UNITS = ("currency", "percent", "count", "number")
COLUMNS = (
    "id", "question", "category", "expected_artifact", "artifact_aliases", "expected_model",
    "decoys", "expected_value", "unit", "rel_tol", "abs_tol", "expected_answer",
    "reference_dax", "criticality", "notes",
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
    expected_value: float = None
    unit: str = "number"
    rel_tol: float = 0.005
    abs_tol: float = 0.0
    expected_answer: str = ""
    reference_dax: str = ""
    criticality: str = "standard"
    notes: str = ""

    @property
    def model(self):
        return self.expected_model or self.expected_artifact

    def to_row(self, run_id):
        d = asdict(self)
        return {
            "RunId": run_id, "QuestionId": self.id, "Question": self.question, "Category": self.category,
            "ExpectedArtifact": self.expected_artifact, "ArtifactAliases": self.artifact_aliases,
            "ExpectedModel": self.model, "Decoys": self.decoys,
            "ExpectedValue": d["expected_value"], "Unit": self.unit, "RelTol": self.rel_tol,
            "AbsTol": self.abs_tol, "ExpectedAnswer": self.expected_answer,
            "ReferenceDax": self.reference_dax, "Criticality": self.criticality,
        }


class GoldenSetError(ValueError):
    pass


def sample_golden_path():
    """The Contoso sample golden set shipped inside the package (used when no golden set is configured)."""
    from importlib import resources
    return Path(str(resources.files("cfeval").joinpath("sample/golden_questions.csv")))


def resolve_golden_path(configured, log=print):
    """The configured golden set, or the bundled sample when the default path doesn't exist here."""
    path = Path(configured) if configured else None
    if path is not None and path.exists():
        return path
    if configured and configured != "data/golden/golden_questions.csv":
        raise GoldenSetError("golden set not found: %s" % configured)
    log("Using the bundled Contoso sample golden set (set GOLDEN_SET to use your own).")
    return sample_golden_path()


def _num(value, name, row_id, default=None):
    value = (value or "").strip()
    if not value:
        return default
    try:
        return float(value.replace(",", ""))
    except ValueError:
        raise GoldenSetError("%s: %s must be a number, got %r" % (row_id, name, value))


def load_golden(path):
    """Load and validate the golden set CSV."""
    path = Path(path)
    if not path.exists():
        raise GoldenSetError("golden set not found: %s" % path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"id", "question"} - set(reader.fieldnames or [])
        if missing:
            raise GoldenSetError("golden set is missing columns: %s" % ", ".join(sorted(missing)))
        questions, seen = [], set()
        for raw in reader:
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            qid = row.get("id", "")
            if not qid and not row.get("question"):
                continue
            if not qid or not row.get("question"):
                raise GoldenSetError("every row needs an id and a question (row %s)" % (qid or "?"))
            if qid in seen:
                raise GoldenSetError("duplicate id: %s" % qid)
            seen.add(qid)
            unit = (row.get("unit") or "number").lower()
            if unit not in UNITS:
                raise GoldenSetError("%s: unit must be one of %s" % (qid, ", ".join(UNITS)))
            questions.append(GoldenQuestion(
                id=qid, question=row["question"], category=row.get("category", ""),
                expected_artifact=row.get("expected_artifact", ""),
                artifact_aliases=row.get("artifact_aliases", ""),
                expected_model=row.get("expected_model", ""), decoys=row.get("decoys", ""),
                expected_value=_num(row.get("expected_value"), "expected_value", qid),
                unit=unit, rel_tol=_num(row.get("rel_tol"), "rel_tol", qid, 0.005),
                abs_tol=_num(row.get("abs_tol"), "abs_tol", qid, 0.0),
                expected_answer=row.get("expected_answer", ""),
                reference_dax=row.get("reference_dax", ""),
                criticality=row.get("criticality", "") or "standard", notes=row.get("notes", ""),
            ))
    if not questions:
        raise GoldenSetError("golden set has no questions: %s" % path)
    return questions


def golden_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def write_golden(questions, path):
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for q in questions:
            d = asdict(q)
            w.writerow({c: ("" if d.get(c) is None else d.get(c)) for c in COLUMNS})
