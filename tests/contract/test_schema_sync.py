"""Contract tests ensuring KQL, TypeScript/JSON app contracts, and RowId invariants stay in sync."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from cfeval.kqlgen import setup_script
from cfeval.schema import SCHEMA_VERSION, TABLES
from cfeval.sinks import coerce_row

ROOT = Path(__file__).resolve().parents[2]
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_gen_app_contract():
    spec = importlib.util.spec_from_file_location("gen_app_contract", ROOT / "tools" / "gen_app_contract.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_kql_setup_matches_generated_script() -> None:
    setup_path = ROOT / "kql" / "setup.kql"
    assert setup_path.is_file()
    assert setup_path.read_text(encoding="utf-8") == setup_script()


def test_app_contract_files_match_generator() -> None:
    gen = _load_gen_app_contract()
    expected = gen.outputs()
    contract_ts_path = ROOT / "app" / "overlay" / "src" / "eval" / "generated" / "contract.ts"
    metadata_json_path = ROOT / "app" / "connectors" / "evals" / "metadata.example.json"
    assert contract_ts_path in expected
    assert metadata_json_path in expected
    assert contract_ts_path.read_text(encoding="utf-8") == expected[contract_ts_path]
    assert metadata_json_path.read_text(encoding="utf-8") == expected[metadata_json_path]


def test_latency_breakdown_omits_non_additive_subtraction() -> None:
    functions_kql = (ROOT / "src" / "cfeval" / "kql" / "functions.kql").read_text(encoding="utf-8")
    match = re.search(r"LatencyBreakdown\([^)]*\)\s*\{([^}]*)\}", functions_kql, re.DOTALL)
    assert match is not None, "LatencyBreakdown function definition not found in functions.kql"
    body = match.group(1)
    assert "NonDaxMs" not in body
    assert "LatencyMs - DaxTotalMs" not in body


def test_coerce_row_populates_rowid_and_schema_v2() -> None:
    sample_rows = {
        "EvalRun": {
            "RunId": "run-contract-01",
            "RunName": "Contract check",
            "StartedUtc": "2026-11-01T09:00:00Z",
            "EndedUtc": "2026-11-01T09:05:00Z",
            "Status": "completed",
            "SchemaVersion": SCHEMA_VERSION,
        },
        "EvalQuestion": {
            "RunId": "run-contract-01",
            "QuestionId": "Q01",
            "Question": "What was revenue?",
            "CaseType": "scalar",
        },
        "EvalAsk": {
            "RunId": "run-contract-01",
            "AskId": "run-contract-01-Q01-1",
            "QuestionId": "Q01",
            "Attempt": 1,
            "AskStartUtc": "2026-11-01T09:00:01Z",
            "AskEndUtc": "2026-11-01T09:00:03Z",
            "Status": "ok",
        },
        "FabricIqQuery": {
            "RunId": "run-contract-01",
            "AskId": "run-contract-01-Q01-1",
            "QueryTimeUtc": "2026-11-01T09:00:02Z",
            "WorkspaceId": "00000000-0000-0000-0000-000000000001",
            "ItemId": "00000000-0000-0000-0000-000000000002",
            "ItemName": "Contoso Finance Model",
            "DurationMs": 42.5,
            "Dax": 'EVALUATE ROW("Result", 1)',
            "CorrelationId": "corr-01",
        },
        "EvalScore": {
            "RunId": "run-contract-01",
            "AskId": "run-contract-01-Q01-1",
            "QuestionId": "Q01",
            "Backend": "fabric-native",
            "Check": "value",
            "Score": 1.0,
            "Outcome": "PASS",
            "ScoredUtc": "2026-11-01T09:05:00Z",
        },
        "EvalResult": {
            "RunId": "run-contract-01",
            "AskId": "run-contract-01-Q01-1",
            "QuestionId": "Q01",
            "Attempt": 1,
            "Backend": "fabric-native",
            "Verdict": "PASS",
            "ScoredUtc": "2026-11-01T09:05:00Z",
        },
        "EvalEvent": {
            "RunId": "run-contract-01",
            "EventTimeUtc": "2026-11-01T09:00:03Z",
            "Stage": "copilot.ask",
            "AskId": "run-contract-01-Q01-1",
            "DurationMs": 2000.0,
            "Status": "ok",
        },
    }

    assert set(sample_rows) == set(TABLES)
    assert len(TABLES) == 7

    for table, raw in sample_rows.items():
        coerced_1 = coerce_row(table, raw)
        coerced_2 = coerce_row(table, raw)
        row_id = coerced_1.get("RowId")
        assert isinstance(row_id, str) and HEX64_RE.match(row_id), f"{table} produced invalid RowId: {row_id!r}"
        assert coerced_1["RowId"] == coerced_2["RowId"]

    eval_run_coerced = coerce_row("EvalRun", {"RunId": "run-contract-default"})
    assert eval_run_coerced["SchemaVersion"] == 2


def test_bundled_package_resources_match_repo_files(monkeypatch, tmp_path: Path) -> None:
    import pytest

    from cfeval import golden_v2
    from cfeval.golden_v2 import GoldenValidationError, validate_golden_dict

    pkg_dir = ROOT / "src" / "cfeval"
    pairs = [
        (ROOT / "schemas" / "golden.schema.json", pkg_dir / "resources" / "golden.schema.json"),
        (ROOT / "config" / "gates.yaml", pkg_dir / "resources" / "gates.yaml"),
        (
            ROOT / "data" / "judge_calibration" / "answers.jsonl",
            pkg_dir / "resources" / "judge_calibration_answers.jsonl",
        ),
        (ROOT / "data" / "golden" / "contoso.yaml", pkg_dir / "sample" / "contoso.yaml"),
        (ROOT / "data" / "golden" / "contoso-smoke.yaml", pkg_dir / "sample" / "contoso-smoke.yaml"),
        (ROOT / "data" / "golden" / "contoso-work.yaml", pkg_dir / "sample" / "contoso-work.yaml"),
    ]
    for repo_file, bundled_file in pairs:
        assert bundled_file.is_file(), f"Missing bundled wheel resource: {bundled_file}"
        assert bundled_file.read_bytes() == repo_file.read_bytes(), (
            f"Bundled resource {bundled_file} drifted from {repo_file}"
        )

    monkeypatch.setattr(golden_v2, "_default_schema_path", lambda: tmp_path / "missing.schema.json")
    report = validate_golden_dict({"version": 2, "cases": []}, raise_on_error=False)
    assert report["valid"] is False
    assert any("golden schema file not found" in e for e in report["errors"])
    with pytest.raises(GoldenValidationError):
        validate_golden_dict({"version": 2, "cases": []}, raise_on_error=True)


def test_live_contract_file_uses_current_public_apis() -> None:
    live_src = (ROOT / "tests" / "live" / "test_live_contracts.py").read_text(encoding="utf-8")
    assert "Settings.from_env" not in live_src
    assert "Settings.load()" in live_src
    assert "DelegatedAuth.from_settings(" in live_src
    assert "MONITORING_QUERY_URI" in live_src
    assert "MCP_SERVER_COMMAND" in live_src
