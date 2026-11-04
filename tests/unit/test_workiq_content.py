"""Work IQ content pack: workiq/content.yaml, the golden documents and the committed .docx files agree.

The joint cases (PLAN §4.4) only work if the documents say exactly what the golden set expects, so
these tests fail when a fact, a title, a site's readers or a built document drifts.
"""

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from copilot_evals.golden import load_golden_set
from copilot_evals.schemas import DocumentFact, Unit
from copilot_evals.setup.rest import SetupError
from copilot_evals.setup.workiq import (
    CONTENT_FILE,
    DOCUMENTS_DIR,
    Block,
    ContentPack,
    check_content_pack,
    docx_text,
    format_fact,
    load_content_pack,
    render_document,
)


def _raw_pack(repo_root: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((repo_root / CONTENT_FILE).read_text(encoding="utf-8"))
    return data


def _problems(repo_root: Path, golden_dir: Path, raw: dict[str, Any]) -> list[str]:
    return check_content_pack(ContentPack.model_validate(raw), load_golden_set(golden_dir))


def test_content_pack_matches_the_golden_set(repo_root: Path, golden_dir: Path) -> None:
    pack = load_content_pack(repo_root / CONTENT_FILE, load_golden_set(golden_dir))

    assert set(pack.documents) == {"fy25_revenue_targets", "fy25_service_objectives", "fy25_revenue_draft"}


def test_committed_documents_match_the_content_pack(repo_root: Path, golden_dir: Path) -> None:
    golden = load_golden_set(golden_dir)
    pack = load_content_pack(repo_root / CONTENT_FILE, golden)

    for key, content in pack.documents.items():
        document = render_document(key, content, golden)
        path = repo_root / DOCUMENTS_DIR / document.file_name
        assert path.is_file(), f"run: python scripts/build_workiq_documents.py ({path.name} is missing)"
        assert docx_text(path) == document.plain_text().split("\n"), f"{path.name} is stale: rebuild it"


def test_documents_state_the_golden_figures(repo_root: Path) -> None:
    def text(name: str) -> str:
        return "\n".join(docx_text(repo_root / DOCUMENTS_DIR / name))

    targets = text("FY2025 Revenue Targets - APPROVED.docx")
    assert "The company target for FY2025 is $12,500,000 of gross revenue" in targets
    assert "East\n$4,000,000" in targets
    assert "Sev1\n6 hours" in text("FY2025 Service Level Objectives.docx")
    assert "$13,600,000" in text("FY2025 revenue - DRAFT.docx")


def test_source_documents_are_hidden_from_personas_without_data_access(repo_root: Path, golden_dir: Path) -> None:
    raw = _raw_pack(repo_root)
    leaky = copy.deepcopy(raw)
    leaky["sites"]["planning"]["readers"].append("noaccess")

    assert _problems(repo_root, golden_dir, raw) == []
    assert any("is a source, but ['noaccess'] can read it" in p for p in _problems(repo_root, golden_dir, leaky))


def test_check_reports_facts_titles_and_missing_documents(repo_root: Path, golden_dir: Path) -> None:
    raw = copy.deepcopy(_raw_pack(repo_root))
    blocks = raw["documents"]["fy25_service_objectives"]["blocks"]
    blocks[0]["title"] = "Service objectives"
    blocks.append({"paragraph": "Sev5 objective: {sev5_mttr_objective_hours}."})
    raw["documents"]["fy25_revenue_draft"]["blocks"] = [{"title": "FY2025 revenue - DRAFT"}, {"meta": "DRAFT"}]
    del raw["documents"]["fy25_revenue_targets"]

    problems = _problems(repo_root, golden_dir, raw)

    assert "document fy25_revenue_targets has no content in workiq/content.yaml" in problems
    assert any("fy25_service_objectives: title block" in p for p in problems)
    assert "document fy25_service_objectives: unknown fact {sev5_mttr_objective_hours}" in problems
    assert "document fy25_revenue_draft: fact draft_revenue is never stated" in problems


def test_load_raises_on_any_problem(tmp_path: Path, repo_root: Path, golden_dir: Path) -> None:
    raw = _raw_pack(repo_root)
    raw["sites"]["planning"]["readers"] = ["exec", "ghost"]
    content_file = tmp_path / "content.yaml"
    content_file.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(SetupError, match="unknown persona ghost"):
        load_content_pack(content_file, load_golden_set(golden_dir))
    with pytest.raises(SetupError, match="content.yaml"):
        content_file.write_text("version: 2\nsites: {}\ndocuments: {}\n", encoding="utf-8")
        load_content_pack(content_file, load_golden_set(golden_dir))


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("12500000", Unit.CURRENCY_USD, "$12,500,000"),
        ("1234.5", Unit.CURRENCY_USD, "$1,234.50"),
        ("6", Unit.HOURS, "6 hours"),
        ("1", Unit.HOURS, "1 hour"),
        ("7.25", Unit.HOURS, "7.25 hours"),
        ("0.125", Unit.PERCENT, "12.5%"),
        ("1500", Unit.COUNT, "1,500"),
    ],
)
def test_format_fact(value: str, unit: Unit, expected: str) -> None:
    assert format_fact(DocumentFact(value=Decimal(value), unit=unit, label="x")) == expected


def test_block_sets_exactly_one_kind() -> None:
    assert Block(heading="Purpose").kind == "heading"
    with pytest.raises(ValueError, match="exactly one"):
        Block(title="A", paragraph="B")
