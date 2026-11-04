"""Fabric notebooks: committed .ipynb files match their sources, and the notebooks agree with each other.

Cells tagged ``parameters`` and ``logic`` are plain Python (pandas and numpy for nb_01), so these
tests run them outside Fabric and check, without a tenant:

* nb_01 generates the calibrated figures the seeded documents and nb_03's checks rely on;
* nb_02's model definitions read only tables and columns nb_01 writes;
* every measure and column the golden-set DAX names exists in the model it targets;
* nb_03's validation and snapshot helpers behave as documented.
"""

import functools
import importlib.util
import re
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

pd = pytest.importorskip("pandas", reason="the notebook logic tests need the dev dependencies (uv sync)")

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = ROOT / "fabric" / "notebooks"
SOURCES = NOTEBOOKS / "src"
GOLDEN = ROOT / "evals" / "golden"

EAST_UPN = "eval.east@contoso.example"

_COLUMN_REF = re.compile(r"(?:'([^']+)'|\b([A-Za-z_][A-Za-z0-9_]*))\[([^\]]+)\]")
_MEASURE_REF = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_notebooks", ROOT / "scripts" / "build_notebooks.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _builder()


def _run_logic(name: str, **parameters: Any) -> dict[str, Any]:
    """Run a notebook's parameters and logic cells, with parameter overrides; return its globals."""
    namespace: dict[str, Any] = {"__name__": f"notebook_{name}"}
    for kind, text in BUILDER.parse_cells((SOURCES / f"{name}.py").read_text(encoding="utf-8")):
        if kind in {"parameters", "logic"}:
            exec(compile(text, f"{name}.py", "exec"), namespace)
        if kind == "parameters":
            namespace.update(parameters)
    return namespace


@functools.cache
def _nb01() -> dict[str, Any]:
    """nb_01 at a tenth of its size; the calibrated figures hold at any size."""
    mapping = '{"' + EAST_UPN + '": ["East"]}'
    return _run_logic(
        "nb_01_generate_data", sales_rows=50_000, incident_count=3_000, security_user_region_json=mapping
    )


@functools.cache
def _nb02() -> dict[str, Any]:
    return _run_logic("nb_02_build_models")


def _model_columns(spec: dict[str, Any]) -> dict[str, set[str]]:
    """Model table -> model column names, from the tables nb_01 writes and nb_02's renames."""
    namespace = _nb01()
    data = namespace["sandbox_tables"] if spec["workspace"] == "sandbox" else namespace["gold_tables"]
    rename = _nb02()["model_column"]
    return {table: {rename(column) for column in data[source].columns} for table, source in spec["tables"].items()}


def _references(dax: str) -> tuple[set[tuple[str, str]], set[str]]:
    """Column references ``(table, column)`` and measure references in a DAX expression."""
    columns = {(quoted or bare, column) for quoted, bare, column in _COLUMN_REF.findall(dax)}
    return columns, set(_MEASURE_REF.findall(dax))


# --- build -------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", sorted(SOURCES.glob("nb_*.py")), ids=lambda path: path.stem)
def test_committed_notebook_matches_source(source: Path) -> None:
    committed = NOTEBOOKS / f"{source.stem}.ipynb"

    assert committed.is_file(), f"run: python scripts/build_notebooks.py ({committed.name} is missing)"
    assert committed.read_text(encoding="utf-8") == BUILDER.render(source.stem, source.read_text(encoding="utf-8"))


@pytest.mark.parametrize("source", sorted(SOURCES.glob("nb_*.py")), ids=lambda path: path.stem)
def test_parameters_cell_comes_first(source: Path) -> None:
    kinds = [kind for kind, _ in BUILDER.parse_cells(source.read_text(encoding="utf-8")) if kind != "markdown"]

    assert kinds[0] == "parameters", "Fabric injects run parameters after the first cell tagged 'parameters'"


# --- nb_01: synthetic data ---------------------------------------------------------------------


def test_generator_hits_the_calibrated_figures() -> None:
    namespace = _nb01()
    sales = namespace["fact_sales_cents"]
    fy2025 = sales[namespace["fiscal_year"](sales["Date"]) == "FY2025"]

    assert fy2025.groupby("Region")["GrossCents"].sum().to_dict() == namespace["FY2025_GROSS_REVENUE_CENTS"]
    assert sum(namespace["FY2025_GROSS_REVENUE_CENTS"].values()) == 1_284_000_000
    assert namespace["FY2025_SEV1_MTTR_HOURS"] == 7.2


def test_documents_tell_a_consistent_story() -> None:
    """Approved targets and objectives versus the calibrated actuals: the joint cases depend on it."""
    documents = yaml.safe_load((GOLDEN / "models.yaml").read_text(encoding="utf-8"))["documents"]
    targets = {key: Decimal(str(fact["value"])) for key, fact in documents["fy25_revenue_targets"]["facts"].items()}
    actual = {region: Decimal(cents) / 100 for region, cents in _nb01()["FY2025_GROSS_REVENUE_CENTS"].items()}
    objective = Decimal(str(documents["fy25_service_objectives"]["facts"]["sev1_mttr_objective_hours"]["value"]))
    draft = Decimal(str(documents["fy25_revenue_draft"]["facts"]["draft_revenue"]["value"]))

    regional = sum(value for key, value in targets.items() if key != "gross_revenue_target")
    assert regional == targets["gross_revenue_target"], "regional targets must add up to the company target"
    assert sum(actual.values()) > targets["gross_revenue_target"], "JNT-001 expects the target to be beaten"
    assert actual["East"] > targets["east_gross_revenue_target"]
    assert Decimal("7.2") > objective, "JNT-003 expects the Sev1 objective to be missed"
    assert draft != sum(actual.values()), "the draft decoy must disagree with the certified figure"


def test_security_table_comes_from_the_parameter() -> None:
    table = _nb01()["security_user_region"]

    assert table.to_dict(orient="records") == [{"UserPrincipalName": EAST_UPN, "Region": "East"}]
    with pytest.raises(ValueError, match="unknown region"):
        _nb01()["build_security_user_region"]('{"someone@contoso.example": ["Atlantis"]}')


def test_decoy_snapshot_is_stale_and_inflated() -> None:
    namespace = _nb01()
    snapshot = namespace["sandbox_tables"]["fact_sales_snapshot_2025q1"]
    certified = namespace["gold_tables"]["fact_sales"]
    before = certified[certified["Date"] <= pd.Timestamp("2025-03-31")]

    assert snapshot["Date"].max() <= pd.Timestamp("2025-03-31")
    assert snapshot["GrossAmount"].sum() > before["GrossAmount"].sum()


# --- nb_02: semantic models --------------------------------------------------------------------


@pytest.mark.parametrize("model", ["Sales Analytics", "Finance", "Service Operations", "Sales Sandbox"])
def test_model_reads_only_generated_columns(model: str) -> None:
    spec = _nb02()["MODELS"][model]
    columns = _model_columns(spec)

    for from_table, from_column, to_table, to_column in spec["relationships"]:
        assert from_column in columns[from_table], f"{model}: {from_table}[{from_column}]"
        assert to_column in columns[to_table], f"{model}: {to_table}[{to_column}]"
    measures = {name for _, name, *_ in spec["measures"]}
    for table, name, expression, _, description in spec["measures"]:
        assert table in columns and description, f"{model}: [{name}] needs a home table and a description"
        referenced_columns, referenced_measures = _references(expression)
        for ref_table, ref_column in referenced_columns:
            assert ref_column in columns.get(ref_table, set()), f"{model}: [{name}] reads {ref_table}[{ref_column}]"
        assert referenced_measures <= measures, f"{model}: [{name}] uses {referenced_measures - measures}"


def test_row_level_security_reads_the_security_table() -> None:
    namespace = _nb02()
    referenced, _ = _references(namespace["REGION_SCOPE_FILTER"])

    assert referenced == {("Region", "Region"), ("security_user_region", "Region"),
                          ("security_user_region", "UserPrincipalName")}
    for spec in namespace["MODELS"].values():
        assert spec["rls"] == ("security_user_region" in spec["tables"])


def test_golden_dax_names_only_what_the_target_model_has() -> None:
    models = yaml.safe_load((GOLDEN / "models.yaml").read_text(encoding="utf-8"))["models"]
    cases = yaml.safe_load((GOLDEN / "cases.yaml").read_text(encoding="utf-8"))
    specs = _nb02()["MODELS"]
    checked = 0
    for case in cases:
        expect = case.get("expect", {})
        dax = (expect.get("value") or expect.get("table") or {}).get("reference_dax")
        if not dax:
            continue
        spec = specs[models[expect["models"][0]]["display_name"]]
        columns = _model_columns(spec)
        measures = {name for _, name, *_ in spec["measures"]}
        referenced_columns, referenced_measures = _references(dax)
        for table, column in referenced_columns:
            assert column in columns.get(table, set()), f"{case['id']}: {table}[{column}] is not in the model"
        assert referenced_measures <= measures, f"{case['id']}: unknown measures {referenced_measures - measures}"
        checked += 1

    assert checked >= 10


def test_role_member_parameters_split_on_commas() -> None:
    assert _nb02()["members"](" a@contoso.example, ,b@contoso.example ") == ["a@contoso.example", "b@contoso.example"]


# --- nb_03: validation and snapshot ------------------------------------------------------------


def test_validation_checks_match_the_generator() -> None:
    checks = {check["check"]: Decimal(check["expected"]) for check in _run_logic("nb_03_validate_and_snapshot")[
        "CALIBRATED_CHECKS"]}
    cents = _nb01()["FY2025_GROSS_REVENUE_CENTS"]

    assert checks["FY2025 gross revenue, all regions"] == Decimal(sum(cents.values())) / 100
    assert checks["FY2025 gross revenue, East only (row-level security)"] == Decimal(cents["East"]) / 100
    assert checks["FY2025 Sev1 mean time to resolve, hours"] == Decimal(str(_nb01()["FY2025_SEV1_MTTR_HOURS"]))


def test_check_result_and_snapshot_entries() -> None:
    namespace = _run_logic("nb_03_validate_and_snapshot")
    check = namespace["CALIBRATED_CHECKS"][0]
    scalar = pd.DataFrame({"[v]": [12_840_000.004]})
    table = pd.DataFrame({"Region[Region]": ["East", "West"], "[v]": [3, 4]})

    assert namespace["check_result"](check, 12_840_000.004) is None
    assert "expected 12840000.00, got 12839999.00" in namespace["check_result"](check, 12_839_999)
    assert "got 0.00" in namespace["check_result"](check, None)
    assert namespace["snapshot_entry"](scalar) == {"value": "12840000.004"}
    assert namespace["snapshot_entry"](table) == {"table": {"East": "3", "West": "4"}}
