"""Focused unit tests covering edge cases across all core cfeval modules (M1-13)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cfeval.artifacts import classify_url, extract_artifacts, powerbi_artifacts, summarize
from cfeval.clock import SimClock
from cfeval.foundry import CODE_EVALUATORS, code_bundle
from cfeval.golden import (
    GoldenQuestion,
    GoldenSetError,
    golden_hash,
    load_golden,
    resolve_golden_path,
    sample_golden_path,
    write_golden,
)
from cfeval.golden_v2 import (
    GoldenValidationError,
    convert_csv_to_yaml,
    lint_golden_file,
    load_golden_schema,
    load_golden_v2,
    validate_golden_dict,
    validate_golden_file,
)
from cfeval.kqlgen import policy_commands
from cfeval.scorers import (
    FAIL,
    INCONCLUSIVE,
    PASS,
    artifact_check,
    candidates_for_unit,
    extract_answer_value,
    extract_numbers,
    load_gate_policy,
    model_check,
    name_matches,
    parse_numbers,
    score_artifact,
    score_model,
    value_check,
    verdict,
    why_check,
)
from cfeval.scoring import LocalBackend, result_row, score_observation
from cfeval.sinks import EventhouseSink, FanoutSink, JsonlSink, coerce_row
from cfeval.stats import (
    compare_runs,
    mcnemar_exact_p,
    pass_at_k,
    pass_pow_k,
    summarize_run_stats,
    wilson_interval,
)
from cfeval.trace import (
    AskWindow,
    CombinedMonitoringSource,
    EngineEvidence,
    FabricQuery,
    InMemoryMonitoringSource,
    TraceCollectionError,
    WorkspaceMonitoringEvidenceSource,
    WorkspaceMonitoringSource,
    collect_traces,
    compute_correlation_confidence,
    correlate,
    is_noise_dax,
    parse_application_context,
    wait_for_ingestion,
    watermark_dax,
)

WS_ID = "11111111-1111-1111-1111-111111111111"
REPORT_ID = "22222222-2222-2222-2222-222222222222"
MODEL_ID = "33333333-3333-3333-3333-333333333333"
ALT_MODEL_ID = "44444444-4444-4444-4444-444444444444"


# ---------------------------------------------------------------------------
# 1. artifacts.py
# ---------------------------------------------------------------------------


class TestArtifactsModule:
    def test_classify_url_across_m365_and_powerbi_kinds(self) -> None:
        assert classify_url("") == ("other", "", "")
        assert classify_url("mailto:analyst@contoso.com") == ("other", "", "")
        assert classify_url("https://contoso.sharepoint.com/sites/Finance/Deck.pptx") == ("sharepoint_file", "", "")
        assert classify_url("https://contoso-my.sharepoint.com/personal/alex/Budget.xlsx") == ("onedrive_file", "", "")
        assert classify_url("https://teams.microsoft.com/l/message/19:channel/100") == ("teams", "", "")
        assert classify_url("https://outlook.office.com/mail/inbox/id/AAQk") == ("m365", "", "")
        assert classify_url("https://www.office.com/launch/word") == ("m365", "", "")
        assert classify_url("https://outlook.office365.com/mail/") == ("m365", "", "")
        assert classify_url("https://docs.contoso.com/") == ("web", "", "")

        pbi_report = f"https://app.powerbi.com/groups/{WS_ID}/reports/{REPORT_ID}/ReportSection"
        assert classify_url(pbi_report) == ("powerbi_report", WS_ID, REPORT_ID)

        pbi_model = f"https://fabric.microsoft.com/groups/{WS_ID}/semanticmodels/{MODEL_ID}"
        assert classify_url(pbi_model) == ("semantic_model", WS_ID, MODEL_ID)

        pbi_rdl = f"https://app.powerbi.com/rdlreports/{REPORT_ID}"
        assert classify_url(pbi_rdl) == ("paginated_report", "", REPORT_ID)

        pbi_dash = f"https://app.powerbi.com/dashboards/{REPORT_ID}"
        assert classify_url(pbi_dash) == ("powerbi_dashboard", "", REPORT_ID)

        pbi_app = f"https://app.powerbi.com/apps/{REPORT_ID}"
        assert classify_url(pbi_app) == ("powerbi_app", "", REPORT_ID)

        pbi_link = f"https://app.powerbi.com/links/{REPORT_ID}"
        assert classify_url(pbi_link) == ("powerbi_link", "", REPORT_ID)

        pbi_agent = f"https://fabric.microsoft.com/groups/{WS_ID}/dataagents/{MODEL_ID}"
        assert classify_url(pbi_agent) == ("fabric_data_agent", WS_ID, MODEL_ID)

    def test_extract_artifacts_deduplication_empty_attributions_and_summary(self) -> None:
        dataset_url = f"https://app.powerbi.com/groups/{WS_ID}/datasets/{MODEL_ID}"
        report_url = f"https://app.powerbi.com/groups/{WS_ID}/reports/{REPORT_ID}"
        sp_url = "https://contoso.sharepoint.com/sites/Sales/Shared%20Documents/Q3_Recap.docx"

        answer_text = (
            f"Revenue was $12.8M per {dataset_url} and [Executive Sales]({report_url}), "
            f"with commentary from https://portal.contoso.com/ and [Q3 Recap]({sp_url})."
        )
        raw_attributions: list[dict[str, Any]] = [
            {},
            {"providerDisplayName": "Missing URL"},
            {"seeMoreWebUrl": dataset_url, "providerDisplayName": "Sales Analytics", "attributionType": "citation"},
            {"url": sp_url, "providerDisplayName": "Q3 Recap"},
        ]

        extracted = extract_artifacts(raw_attributions, answer_text)
        by_id = {a["item_id"]: a for a in extracted if a["item_id"]}
        assert by_id[MODEL_ID]["name"] == "Sales Analytics"
        assert by_id[MODEL_ID]["answer_cited"] is True
        assert by_id[REPORT_ID]["name"] == "Executive Sales"
        assert by_id[REPORT_ID]["answer_cited"] is True

        host_fallback = [a for a in extracted if a["kind"] == "web"]
        assert len(host_fallback) == 1
        assert host_fallback[0]["name"] == "portal.contoso.com"

        pbi_only = powerbi_artifacts(extracted)
        assert len(pbi_only) == 2

        summary_str = summarize(extracted)
        assert "Sales Analytics (semantic_model)" in summary_str
        assert "Executive Sales (powerbi_report)" in summary_str

        art_score = score_artifact(
            extracted,
            expected="Sales Analytics",
            decoys="Sales Sandbox",
        )
        assert art_score["score"] == PASS
        assert art_score["powerbi_cited"] == 2


# ---------------------------------------------------------------------------
# 2. sinks.py & kqlgen.py
# ---------------------------------------------------------------------------


class _FakeKustoIngestClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[dict[str, Any]], str]] = []

    def ingest_json(self, database: str, table: str, rows: list[dict[str, Any]], mapping: str) -> int:
        self.calls.append((database, table, rows, mapping))
        return len(rows)


class _FailingSecondarySink:
    def write(self, table: str, rows: Any) -> int:
        raise RuntimeError(f"simulated outage on {table}")


class TestSinksAndKqlGen:
    def test_coerce_row_types_unknown_column_and_deterministic_rowid(self) -> None:
        with pytest.raises(KeyError, match=r"EvalAsk has no column\(s\): UnknownField"):
            coerce_row("EvalAsk", {"RunId": "r1", "UnknownField": 123})

        run_coerced = coerce_row("EvalRun", {"RunId": "run-1"})
        assert run_coerced["SchemaVersion"] == 2
        assert run_coerced["RowId"]

        ts = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
        row_a = coerce_row(
            "EvalAsk",
            {
                "RunId": "run-1",
                "AskId": "ask-1",
                "QuestionId": "Q1",
                "Attempt": "2",
                "LatencyMs": "145.5",
                "AskStartUtc": ts,
                "AskEndUtc": "2026-03-15T12:30:02Z",
                "Artifacts": [{"name": "Sales"}],
                "Question": 99,
            },
        )
        row_b = coerce_row("EvalAsk", {"RunId": "run-1", "AskId": "ask-1", "Attempt": True})
        assert row_a["RowId"] == row_b["RowId"]
        assert row_b["Attempt"] == 1
        assert row_a["Attempt"] == 2
        assert row_a["LatencyMs"] == pytest.approx(145.5)
        assert row_a["AskStartUtc"] == "2026-03-15T12:30:00.000Z"
        assert row_a["AskEndUtc"] == "2026-03-15T12:30:02Z"
        assert row_a["Question"] == "99"
        assert row_a["Artifacts"] == [{"name": "Sales"}]

        explicit = coerce_row(
            "EvalRun",
            {"RunId": "run-1", "SchemaVersion": 2, "RowId": "custom-id"},
        )
        assert explicit["SchemaVersion"] == 2
        assert explicit["RowId"] == "custom-id"

    def test_jsonl_eventhouse_and_fanout_sinks(self, tmp_path: Path) -> None:
        sink = JsonlSink(tmp_path / "run_out")
        assert sink.read("EvalAsk") == []
        assert sink.write("EvalAsk", []) == 0

        sink.write("EvalAsk", [{"RunId": "r1", "AskId": "a1", "QuestionId": "Q1"}])
        sink.write("EvalAsk", [{"RunId": "r1", "AskId": "a2", "QuestionId": "Q2"}])
        # Inject a trailing blank line to verify tolerant reading.
        with (tmp_path / "run_out" / "EvalAsk.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("\n")
        rows = sink.read("EvalAsk")
        assert [r["AskId"] for r in rows] == ["a1", "a2"]

        fake_client = _FakeKustoIngestClient()
        eh_sink = EventhouseSink("https://ingest.kusto.windows.net", "EvalDb", client=fake_client)
        assert eh_sink.write("EvalAsk", []) == 0
        assert eh_sink.write("EvalAsk", [{"RunId": "r1", "AskId": "a3"}]) == 1
        assert len(fake_client.calls) == 2
        assert fake_client.calls[1][0] == "EvalDb"
        assert fake_client.calls[1][1] == "EvalAsk"
        assert fake_client.calls[1][3] == "EvalAsk_json"

        logged: list[str] = []
        fanout = FanoutSink(JsonlSink(tmp_path / "fanout_out"), _FailingSecondarySink(), on_error=logged.append)
        written = fanout.write("EvalAsk", [{"RunId": "r2", "AskId": "a9"}])
        assert written == 1
        assert len(fanout.errors) == 1
        assert "simulated outage on EvalAsk" in fanout.errors[0]
        assert logged and logged[0].startswith("telemetry write to _FailingSecondarySink failed")

    def test_kqlgen_policy_commands_validation(self) -> None:
        with pytest.raises(ValueError, match="database must be a non-empty name"):
            policy_commands("", 5)
        with pytest.raises(ValueError, match="database must be a non-empty name"):
            policy_commands("bad'db", 5)
        with pytest.raises(ValueError, match="OneLake latency must be between 5 and 180 minutes"):
            policy_commands("EvalDb", 3)
        with pytest.raises(ValueError, match="OneLake latency must be between 5 and 180 minutes"):
            policy_commands("EvalDb", 181)
        with pytest.raises(ValueError, match="OneLake latency must be between 5 and 180 minutes"):
            policy_commands("EvalDb", "ten")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. stats.py
# ---------------------------------------------------------------------------


class TestStatsModule:
    def test_wilson_pass_k_and_mcnemar_boundaries(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 0.0)
        lo, hi = wilson_interval(8, 10)
        assert 0.45 < lo < 0.80 < hi <= 1.0

        with pytest.raises(ValueError):
            wilson_interval(True, 5)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            wilson_interval(6, 5)

        assert pass_at_k(0, 0, 1) == 0.0
        assert pass_at_k(3, 1, 0) == 0.0
        assert pass_at_k(2, 1, 3) == 1.0
        assert pass_at_k(4, 4, 2) == 1.0
        assert pass_at_k(4, 0, 2) == 0.0
        assert pass_at_k(4, 1, 2) == pytest.approx(0.5)

        assert pass_pow_k(0, 0, 1) == 0.0
        assert pass_pow_k(3, 1, 0) == 0.0
        assert pass_pow_k(2, 1, 3) == pytest.approx(0.125)
        assert pass_pow_k(4, 4, 2) == 1.0
        assert pass_pow_k(4, 0, 2) == 0.0
        assert pass_pow_k(4, 2, 2) == pytest.approx(0.25)

        for fn in (pass_at_k, pass_pow_k):
            with pytest.raises(ValueError):
                fn(True, 1, 1)  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                fn(3, 4, 1)
            with pytest.raises(ValueError):
                fn(3, -1, 1)

        assert mcnemar_exact_p(0, 0) == 1.0
        assert mcnemar_exact_p(4, 4) == 1.0
        assert mcnemar_exact_p(1, 10) < 0.02
        # Large discordant count > 25
        assert mcnemar_exact_p(2, 30) < 0.0001
        assert mcnemar_exact_p(15, 15) == 1.0

        with pytest.raises(ValueError):
            mcnemar_exact_p(-1, 3)
        with pytest.raises(ValueError):
            mcnemar_exact_p(False, 3)  # type: ignore[arg-type]

    def test_summarize_and_compare_runs_with_inconclusive_error_and_unmatched(self) -> None:
        with pytest.raises(ValueError):
            summarize_run_stats([], k=0)
        empty = summarize_run_stats([], k=2)
        assert empty["total_asks"] == 0
        assert empty["pass_rate"] == 0.0

        base_rows = [
            # Q1: consistent 2/2 PASS
            {"QuestionId": "Q1", "Category": "kpi", "Attempt": 1, "Verdict": "PASS", "ExtractedValue": 100.0},
            {"QuestionId": "Q1", "Category": "kpi", "Attempt": 2, "Verdict": "PASS", "ExtractedValue": 100.0},
            # Q2: inconsistent extracted values, 1 pass 1 fail via legacy 'passed' field
            {"QuestionId": "Q2", "Category": "kpi", "Attempt": 1, "passed": 1, "ExtractedValue": 50.0},
            {"QuestionId": "Q2", "Category": "kpi", "Attempt": 2, "passed": 0, "ExtractedValue": 75.0},
            # Q3: critical INCONCLUSIVE & ERROR rows + malformed ExtractedValue types
            {
                "QuestionId": "Q3",
                "Category": "guard",
                "Criticality": "critical",
                "Attempt": 1,
                "passed": None,
                "ExtractedValue": True,
            },
            {
                "QuestionId": "Q3",
                "Category": "guard",
                "Criticality": "critical",
                "Attempt": 2,
                "verdict": "error",
                "ExtractedValue": "not-a-num",
            },
            # Q_BASE_ONLY: unmatched in candidate
            {
                "QuestionId": "Q_BASE_ONLY",
                "Category": "other",
                "Attempt": 1,
                "Verdict": "FAIL",
                "ExtractedValue": float("inf"),
            },
        ]
        summary = summarize_run_stats(base_rows, k=2)
        assert summary["question_count"] == 4
        assert summary["inconclusive_count"] == 1
        assert summary["error_count"] == 1
        assert summary["critical_failures"] == 1
        assert summary["critical_failure_ids"] == ["Q3"]
        assert summary["consistency_rate"] == pytest.approx(0.75)
        assert "kpi" in summary["by_category"]

        cand_rows = [
            # Q1 regresses under k=2 (only 1 of 2 passes)
            {"QuestionId": "Q1", "Category": "kpi", "Attempt": 1, "Verdict": "PASS", "ExtractedValue": 100.0},
            {"QuestionId": "Q1", "Category": "kpi", "Attempt": 2, "Verdict": "FAIL", "ExtractedValue": 90.0},
            # Q2 improves to 2/2 PASS
            {"QuestionId": "Q2", "Category": "kpi", "Attempt": 1, "Verdict": "PASS", "ExtractedValue": 50.0},
            {"QuestionId": "Q2", "Category": "kpi", "Attempt": 2, "Verdict": "PASS", "ExtractedValue": 50.0},
            # Q3 remains non-passing
            {"QuestionId": "Q3", "Category": "guard", "Attempt": 1, "Verdict": "FAIL"},
            {"QuestionId": "Q3", "Category": "guard", "Attempt": 2, "Verdict": "FAIL"},
            # Q_CAND_ONLY: unmatched in baseline
            {"QuestionId": "Q_CAND_ONLY", "Category": "new", "Attempt": 1, "Verdict": "PASS"},
        ]
        comp = compare_runs(base_rows, cand_rows, k=2)
        assert comp["paired_questions"] == 3
        assert comp["regressions"] == ["Q1"]
        assert comp["improvements"] == ["Q2"]
        assert comp["both_failed"] == 1
        assert comp["b"] == 1
        assert comp["c"] == 1
        assert len(comp["per_question_deltas"]) == 3


# ---------------------------------------------------------------------------
# 4. golden.py & golden_v2.py
# ---------------------------------------------------------------------------


class TestGoldenV1AndV2:
    def test_golden_v1_csv_resolution_roundtrip_and_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # Default path falls back to bundled sample when local data/golden/golden_questions.csv does not exist.
        fallback_logs: list[str] = []
        resolved = resolve_golden_path(None, log=fallback_logs.append)
        assert resolved == sample_golden_path()
        assert fallback_logs

        with pytest.raises(GoldenSetError, match="golden set not found"):
            resolve_golden_path(tmp_path / "missing.csv")
        with pytest.raises(GoldenSetError, match="golden set not found"):
            load_golden(tmp_path / "missing.csv")

        bad_header = tmp_path / "bad_header.csv"
        bad_header.write_text("title,prompt\nx,y\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="golden set is missing columns: id, question"):
            load_golden(bad_header)

        empty_rows = tmp_path / "empty.csv"
        empty_rows.write_text("id,question\n,\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="golden set has no questions"):
            load_golden(empty_rows)

        missing_q = tmp_path / "missing_q.csv"
        missing_q.write_text("id,question\nQ1,\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="every row needs an id and a question"):
            load_golden(missing_q)

        dup_id = tmp_path / "dup.csv"
        dup_id.write_text("id,question\nQ1,First?\nQ1,Second?\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="duplicate id: Q1"):
            load_golden(dup_id)

        bad_unit = tmp_path / "bad_unit.csv"
        bad_unit.write_text("id,question,unit\nQ1,How many?,bushels\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="Q1: unit must be one of"):
            load_golden(bad_unit)

        bad_num = tmp_path / "bad_num.csv"
        bad_num.write_text("id,question,expected_value\nQ_NUM,Revenue?,not_a_float\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="Q_NUM: expected_value must be a number"):
            load_golden(bad_num)

        bad_tol_csv = tmp_path / "bad_tol.csv"
        bad_tol_csv.write_text("id,question,rel_tol\nQ_TOL,Revenue?,not_tol\n", encoding="utf-8")
        with pytest.raises(GoldenSetError, match="Q_TOL: rel_tol must be a number"):
            load_golden(bad_tol_csv)

        valid_csv = tmp_path / "valid.csv"
        q_orig = GoldenQuestion(
            id="Q_PAR",
            question="What was FY25 revenue?",
            category="kpi",
            expected_artifact="Sales Report",
            expected_model="Sales Model",
            expected_value=12500000.0,
            unit="currency",
            paraphrases=["Show FY25 total revenue"],
        )
        write_golden([q_orig], valid_csv)
        assert resolve_golden_path(valid_csv) == valid_csv
        assert [q.id for q in load_golden(valid_csv)] == ["Q_PAR"]
        assert len(golden_hash(valid_csv)) == 16
        assert load_golden(sample_golden_path())

        par_csv = tmp_path / "paraphrases.csv"
        par_csv.write_text(
            "id,question,paraphrases\nQ_PAR,What was FY25 revenue?,Show FY25 total revenue|FY25 revenue total\n",
            encoding="utf-8",
        )
        expanded = load_golden(par_csv, expand_paraphrases=True)
        assert [q.id for q in expanded] == ["Q_PAR", "Q_PAR__p1", "Q_PAR__p2"]

    def test_golden_v2_csv_yaml_json_conversion_and_schema_errors(self, tmp_path: Path) -> None:
        csv_src = tmp_path / "legacy.csv"
        csv_src.write_text(
            "id,question,category,expected_artifact,artifact_aliases,expected_model,decoys,"
            "expected_value,unit,expected_answer,reference_dax,notes\n"
            "Q_CONV,What was Q4 revenue in euros?,kpi,Exec Report,Sales Deck,Core Model,Old Draft,"
            '12840000,currency,€12.84M,EVALUATE ROW("v", 12840000),Converted case\n',
            encoding="utf-8",
        )
        yaml_dst = tmp_path / "converted.yaml"
        convert_csv_to_yaml(csv_src, yaml_dst)
        loaded_yaml = load_golden_v2(yaml_dst)
        assert len(loaded_yaml) == 1
        assert loaded_yaml[0].expected_value == pytest.approx(12_840_000.0)
        assert loaded_yaml[0].reference_dax.startswith("EVALUATE")
        assert validate_golden_file(csv_src)["valid"] is True

        json_dst = tmp_path / "cases.json"
        json_dst.write_text(
            json.dumps(
                [
                    {
                        "id": "Q_JSON_1",
                        "question": "As of Q4 FY25, what was net margin?",
                        "intent": {"as_of": "2025-12-31"},
                        "case_type": "scalar",
                        "expected_value": 41.6,
                        "unit": "percent",
                        "currency": "€",
                        "routing": {
                            "expected_artifacts": [
                                {"name": "Margin Hub", "id": REPORT_ID, "aliases": ["Margin Overview"]},
                                {"name": "Finance Companion", "aliases": ["Fin v2"]},
                            ]
                        },
                        "paraphrases": ["For Q4 FY25, state net margin."],
                    }
                ]
            ),
            encoding="utf-8",
        )
        loaded_json = load_golden_v2(json_dst, expand_paraphrases=True)
        assert [q.id for q in loaded_json] == ["Q_JSON_1", "Q_JSON_1__p1"]
        assert loaded_json[0].currency == "EUR"
        assert "Finance Companion" in loaded_json[0].artifact_aliases

        with pytest.raises(GoldenValidationError, match="golden schema file not found"):
            load_golden_schema(tmp_path / "no_schema.json")
        bad_schema = tmp_path / "list_schema.json"
        bad_schema.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(GoldenValidationError, match="invalid golden schema root"):
            load_golden_schema(bad_schema)

        assert validate_golden_dict("not-a-dict", raise_on_error=False)["valid"] is False

        # Validation error diagnostics must name case ID and offending field.
        invalid_cases: dict[str, Any] = {
            "version": 2,
            "cases": [
                "not-a-mapping",
                {"id": "Q_NO_PROMPT", "question": ""},
                {"id": "Q_BAD_TYPE", "question": "Test?", "case_type": "made_up_type"},
                {"id": "Q_SCALAR_EMPTY", "question": "Revenue?", "case_type": "scalar"},
                {"id": "Q_RANK_EMPTY", "question": "Top 3?", "case_type": "ranked_list", "expect": {}},
                {"id": "Q_TABLE_EMPTY", "question": "Table?", "case_type": "table", "expect": {"rows": []}},
                {"id": "Q_REC_EMPTY", "question": "Record?", "case_type": "record", "expect": {"fields": {}}},
                {
                    "id": "Q_DIR_BAD",
                    "question": "Trend?",
                    "case_type": "direction",
                    "expect": {"direction": "sideways"},
                },
                {"id": "Q_CAT_EMPTY", "question": "Tier?", "case_type": "categorical", "expect": {}},
                {
                    "id": "Q_BAD_GATE",
                    "question": "Gate?",
                    "expected_value": 10,
                    "gates": ["nonexistent_gate"],
                },
                {
                    "id": "Q_BAD_TOL",
                    "question": "Tol?",
                    "expected_value": 10,
                    "rel_tol": -0.1,
                },
                {
                    "id": "Q_BOOL_TOL",
                    "question": "Bool tol?",
                    "expected_value": "nan_str",
                    "rel_tol": True,
                    "repeats": True,
                    "paraphrases": [""],
                },
                {
                    "id": "Q_BAD_CURR",
                    "question": "Curr?",
                    "expected_value": 10,
                    "unit": "currency",
                    "currency": "INVALID_ISO",
                },
                {
                    "id": "Q_BAD_CRIT",
                    "question": "Crit?",
                    "expected_value": 10,
                    "criticality": "urgent",
                },
                {"id": "Q_DUP", "question": "Dup 1?", "expected_value": 1},
                {"id": "Q_DUP", "question": "Dup 2?", "expected_value": 2},
            ],
        }
        val_res = validate_golden_dict(invalid_cases, raise_on_error=False)
        assert val_res["valid"] is False
        joined = "\n".join(val_res["errors"])
        for expected_fragment in (
            "case[0]: each entry must be a mapping/object",
            "Q_NO_PROMPT: field 'question' is required and must be non-empty",
            "Q_BAD_TYPE: invalid case_type 'made_up_type'",
            "Q_SCALAR_EMPTY: scalar/numeric case requires a numeric 'expected_value'",
            "Q_RANK_EMPTY: ranked_list case requires non-empty 'expect.items' list",
            "Q_TABLE_EMPTY: table case requires non-empty 'expect.rows' list",
            "Q_REC_EMPTY: record case requires non-empty 'expect.fields' mapping",
            "Q_DIR_BAD: direction case requires 'expect.direction' in ('up', 'down', 'flat')",
            "Q_CAT_EMPTY: categorical case requires 'expect.value' or 'expected'",
            "Q_BAD_GATE: invalid gate 'nonexistent_gate'",
            "Q_BAD_TOL: field 'rel_tol' must be >= 0",
            "Q_BOOL_TOL: field 'rel_tol' must be a number, got bool",
            "Q_BOOL_TOL: field 'expected_value' must be numeric",
            "Q_BOOL_TOL: paraphrase entries must be non-empty strings",
            "Q_BOOL_TOL: 'repeats' must be an integer >= 1",
            "Q_BAD_CURR: invalid currency 'INVALID_ISO'",
            "Q_BAD_CRIT: invalid criticality 'urgent'",
            "Q_DUP: duplicate question id 'Q_DUP'",
        ):
            assert expected_fragment in joined

        with pytest.raises(GoldenValidationError):
            validate_golden_dict({"cases": [], "questions": []}, raise_on_error=True)

        bad_ext = tmp_path / "notes.txt"
        bad_ext.write_text("hello", encoding="utf-8")
        assert validate_golden_file(bad_ext, raise_on_error=False)["valid"] is False
        assert validate_golden_file(tmp_path / "does_not_exist.yaml", raise_on_error=False)["valid"] is False

        bad_csv_file = tmp_path / "bad_v2.csv"
        bad_csv_file.write_text("col1,col2\na,b\n", encoding="utf-8")
        assert validate_golden_file(bad_csv_file, raise_on_error=False)["valid"] is False

        bad_json_syntax = tmp_path / "broken.json"
        bad_json_syntax.write_text("{broken", encoding="utf-8")
        broken_res = validate_golden_file(bad_json_syntax, raise_on_error=False)
        assert broken_res["valid"] is False
        assert "failed to parse" in broken_res["errors"][0]

    def test_golden_v2_lint_warnings(self, tmp_path: Path) -> None:
        lint_target = tmp_path / "lint_cases.yaml"
        lint_payload = {
            "version": 2,
            "cases": [
                {
                    "id": "L1",
                    "question": "What is the latest revenue this year?",
                    "case_type": "scalar",
                    "expected_value": 500.0,
                    "criticality": "critical",
                    "repeats": 1,
                    "routing": {"expected_artifact": "Sales Report"},
                },
                {
                    "id": "L2",
                    "question": "What is the latest revenue this year?!",
                    "intent": {"as_of": "FY2025"},
                    "case_type": "scalar",
                    "expected_value": 500.0,
                    "reference_dax": 'EVALUATE ROW("v", 500)',
                    "routing": {"expected_artifact": {"name": "Sales Report", "id": REPORT_ID}},
                },
            ],
        }
        import yaml

        lint_target.write_text(yaml.safe_dump(lint_payload, sort_keys=False), encoding="utf-8")
        warnings = lint_golden_file(lint_target)
        joined = "\n".join(warnings)
        assert "recommended >= 20" in joined
        assert "L1: missing reference_dax for scalar expectation" in joined
        assert "L1: name-only routing expectation without expected_artifact_id" in joined
        assert "L1: time-relative wording in question without 'as_of' date" in joined
        assert "L1: critical case has repeats=1 (recommended >= 3)" in joined
        assert "L2: near-duplicate question text with L1" in joined
        # L2 has reference_dax, expected_artifact_id, and intent.as_of, so none of those 3 fire on L2.
        assert "L2: missing reference_dax" not in joined
        assert "L2: name-only routing" not in joined
        assert "L2: time-relative wording" not in joined


# ---------------------------------------------------------------------------
# 5. scorers.py, scoring.py, foundry.py
# ---------------------------------------------------------------------------


class _HallucinatingJudge:
    """Stub judge returning either a fabricated or literal extraction span."""

    model_name = "stub-judge"
    prompt_hash = "stubhash1234"
    calibration_id = "stub-cal"

    def __init__(
        self,
        extract_payload: dict[str, Any] | None = None,
        judge_score: float = 0.5,
    ) -> None:
        self._extract_payload = extract_payload
        self._judge_score = judge_score

    def extract_value(self, question: str, answer: str) -> dict[str, Any] | None:
        return self._extract_payload

    def judge_answer(self, q: Any, answer: str) -> dict[str, Any] | None:
        return {"score": self._judge_score, "reason": "stub judge verdict", "raw": {}}

    def judge_why(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return None


class TestScorersScoringAndFoundry:
    def test_number_locales_eu_and_auto_and_percent_ratio_policy(self) -> None:
        eu_curr = extract_answer_value("Der Umsatz betrug **12.840.000 €** im Q4.", number_locale="eu")
        assert eu_curr["status"] == "ok"
        assert eu_curr["value"] == pytest.approx(12_840_000.0)
        assert eu_curr["currency"] == "EUR"

        auto_curr = value_check(
            "Total EMEA bookings reached 12.840.000 €.",
            12_840_000.0,
            expected_unit="currency",
            expected_currency="EUR",
            number_locale="auto",
        )
        assert auto_curr["passed"] == 1

        eu_pct = value_check("Die Bruttomarge lag bei 41,6 %.", 41.6, expected_unit="percent", number_locale="auto")
        assert eu_pct["passed"] == 1

        # Ambiguous single-dot thousands: 'eu' treats 12.345 as 12345, 'us' treats as 12.345.
        assert extract_numbers(" Menge: 12.345 ", number_locale="eu")[0]["value"] == pytest.approx(12345.0)
        parsed_us = parse_numbers(" Amount: 12.345, Margin: 0.42, Spend: $9.1M ", number_locale="us")
        assert parsed_us[0]["kind"] == "number"
        assert candidates_for_unit(parsed_us, "percent")[0]["raw"] == "0.42"
        assert candidates_for_unit(parsed_us, "currency")[0]["kind"] == "currency"
        assert candidates_for_unit(parsed_us, "number")[0]["kind"] == "number"
        assert candidates_for_unit([], "percent") == []

        # percent_accepts_ratio=True vs False
        ratio_accepted = value_check(
            "Gross margin ratio was 0.416.",
            41.6,
            expected_unit="percent",
            percent_accepts_ratio=True,
        )
        assert ratio_accepted["passed"] == 1
        assert ratio_accepted["match_kind"] == "exact_match"
        assert ratio_accepted["extracted"] == pytest.approx(41.6)

        ratio_rejected = value_check(
            "Gross margin ratio was 0.416.",
            41.6,
            expected_unit="percent",
            percent_accepts_ratio=False,
        )
        assert ratio_rejected["passed"] == 0

        pct_for_ratio = value_check(
            "Retention rate was 41.6%.",
            0.416,
            expected_unit="percent",
            percent_accepts_ratio=True,
        )
        assert pct_for_ratio["passed"] == 1
        assert value_check("Retention rate was 41.6%.", 0.416, percent_accepts_ratio=False)["passed"] == 0

    def test_rich_expectations_record_table_ranked_set_direction_and_citation(self) -> None:
        # Record expectation: two-column markdown table, multi-column header table, prose, and failures
        rec_expect = {
            "fields": {
                "Revenue": 12_800_000,
                "Gross Margin": 41.6,
                "Region": "EMEA",
            },
            "rel_tol": 0.01,
        }
        rec_md = "| Metric | Value |\n|---|---|\n| Revenue | $12.8M |\n| Gross Margin | 41.6% |\n| Region | EMEA |\n"
        assert value_check(rec_md, None, case_type="record", expect=rec_expect)["passed"] == 1

        rec_header_md = "| Revenue | Gross Margin | Region |\n|---|---|---|\n| $12.8M | 41.6% | EMEA |\n"
        assert value_check(rec_header_md, None, case_type="record", expect=rec_expect)["passed"] == 1

        rec_prose = "Revenue: $12.8M; Gross Margin: 41.6%; Region: EMEA"
        assert value_check(rec_prose, None, case_type="record", expect=rec_expect)["passed"] == 1

        rec_bad = "Revenue: $9.1M\nGross Margin: 41.6%\nRegion: EMEA"
        rec_bad_res = value_check(rec_bad, None, case_type="record", expect=rec_expect)
        assert rec_bad_res["passed"] == 0
        assert "Revenue" in rec_bad_res["reason"]
        assert value_check("Revenue: $12.8M", None, case_type="record", expect=rec_expect)["passed"] == 0
        wrong_region = "Revenue: $12.8M; Gross Margin: 41.6%; Region: APAC"
        assert value_check(wrong_region, None, case_type="record", expect=rec_expect)["passed"] == 0

        # Table expectation: keyed match, positional match, missing row, and numeric cell failure
        tbl_expect = {
            "key": "Region",
            "rows": [
                {"Region": "Americas", "Revenue": 25.0, "Status": "On Track"},
                {"Region": "EMEA", "Revenue": 12.8, "Status": "Watch"},
            ],
            "rel_tol": 0.02,
        }
        tbl_good = (
            "| Region | Revenue | Status |\n|---|---|---|\n| Americas | 25.0 | On Track |\n| EMEA | 12.8 | Watch |\n"
        )
        assert value_check(tbl_good, None, case_type="table", expect=tbl_expect)["passed"] == 1
        unkeyed_tbl = {"rows": [{"Region": "Americas", "Revenue": 25.0}], "rel_tol": 0.02}
        assert value_check(tbl_good, None, case_type="table", expect=unkeyed_tbl)["passed"] == 1

        tbl_missing_row = "| Region | Revenue | Status |\n|---|---|---|\n| Americas | 25.0 | On Track |\n"
        tbl_miss_res = value_check(tbl_missing_row, None, case_type="table", expect=tbl_expect)
        assert tbl_miss_res["passed"] == 0
        assert "missing" in tbl_miss_res["reason"].lower() or "row" in tbl_miss_res["reason"].lower()

        tbl_wrong_val = (
            "| Region | Revenue | Status |\n|---|---|---|\n| Americas | 25.0 | On Track |\n| EMEA | 99.9 | Watch |\n"
        )
        assert value_check(tbl_wrong_val, None, case_type="table", expect=tbl_expect)["passed"] == 0
        assert value_check("No markdown grid here.", None, case_type="table", expect=tbl_expect)["passed"] == 0

        # Ranked list & set expectations
        rank_expect = {"items": ["Americas", "EMEA", "APAC"], "top_n": 3, "forbidden_items": ["Sandbox"]}
        assert (
            value_check("1. Americas, 2. EMEA, 3. APAC", None, case_type="ranked_list", expect=rank_expect)["passed"]
            == 1
        )
        assert (
            value_check("1. EMEA, 2. Americas, 3. APAC", None, case_type="ranked_list", expect=rank_expect)["passed"]
            == 0
        )
        assert (
            value_check("1. Americas, 2. EMEA, 3. APAC (Sandbox)", None, case_type="ranked_list", expect=rank_expect)[
                "passed"
            ]
            == 0
        )

        set_expect = {"items": ["Alpha", "Beta", "Gamma"], "min_overlap": 2}
        assert value_check("Active programs: Beta and Gamma.", None, case_type="set", expect=set_expect)["passed"] == 1
        assert value_check("Active programs: Alpha only.", None, case_type="set", expect=set_expect)["passed"] == 0

        # Direction expectation (up, down, flat + magnitude mismatch + invalid direction)
        assert (
            value_check(
                "Bookings increased by 8.5% compared with last quarter's decline.",
                8.5,
                expected_unit="percent",
                case_type="direction",
                expect={"direction": "up", "value": 8.5, "unit": "percent"},
            )["passed"]
            == 1
        )
        assert (
            value_check(
                "Bookings increased by 2.0% year over year.",
                8.5,
                expected_unit="percent",
                case_type="direction",
                expect={"direction": "up", "value": 8.5, "unit": "percent"},
            )["passed"]
            == 0
        )
        assert (
            value_check(
                "Churn declined 2.1% compared with prior increase.",
                None,
                case_type="direction",
                expect={"direction": "down"},
            )["passed"]
            == 1
        )
        assert (
            value_check(
                "Headcount remained unchanged quarter over quarter.",
                None,
                case_type="direction",
                expect={"direction": "flat"},
            )["passed"]
            == 1
        )
        assert (
            value_check("Bookings rose.", None, case_type="direction", expect={"direction": "unknown"})["passed"] == -1
        )

        # Citation-only, categorical, and facts
        assert (
            value_check("Contoso Q4 operating risks center on supply lead times.", None, case_type="citation_only")[
                "passed"
            ]
            == 1
        )
        assert value_check("I cannot find that data.", None, case_type="citation_only")["passed"] == 0
        assert (
            value_check("Customer tier is Enterprise.", None, case_type="categorical", expect={"value": "Enterprise"})[
                "passed"
            ]
            == 1
        )
        assert (
            value_check(
                "Sponsored by Alex Rivera in Zurich.",
                None,
                case_type="facts",
                expect={"facts": ["Alex Rivera", "Zurich"]},
            )["passed"]
            == 1
        )

    def test_abstention_clarification_and_judge_disagreement_inconclusive(self) -> None:
        # Clean abstention vs hedged answer leaking fabricated figures vs forbidden phrase
        clean_refusal = "That personal tax identifier is not available in the semantic model."
        assert value_check(clean_refusal, None, case_type="abstention")["passed"] == 1
        assert (
            value_check(clean_refusal, None, case_type="abstention", expect={"forbidden": ["tax identifier"]})["passed"]
            == 0
        )
        assert value_check("Executive bonus pool was $4.2M.", None, case_type="abstention")["passed"] == 0

        leaked_number = "I cannot verify exact payroll, though executive bonuses were $4.2M."
        assert value_check(leaked_number, None, case_type="abstention")["passed"] == 0

        allowed_zero = "No succession list exists; a $0 placeholder is not available in the workspace."
        assert value_check(allowed_zero, None, case_type="abstention", expect={"allowed_numbers": [0]})["passed"] == 1

        # Clarification prompt vs statement or fabricated metric
        assert (
            value_check("Do you mean fiscal year or calendar year revenue?", None, case_type="clarification")["passed"]
            == 1
        )
        assert value_check("Do you mean the $19.4M EMEA pipeline?", None, case_type="clarification")["passed"] == 0
        assert value_check("Revenue was strong.", None, case_type="clarification")["passed"] == 0

        # Deterministic PASS + judge INCONCLUSIVE (0.5) under judge_gates_verdict -> INCONCLUSIVE
        q_abs = GoldenQuestion(
            id="Q_ABS",
            question="List private tax IDs of top buyers.",
            case_type="abstention",
            gates=["value"],
        )
        obs = {
            "Answer": clean_refusal,
            "Status": "ok",
            "Artifacts": [],
            "attributions": [],
            "trace": {"status": "disabled", "queries": []},
        }
        inconc_judge = _HallucinatingJudge(judge_score=INCONCLUSIVE)
        scored = score_observation(
            q_abs,
            obs,
            judge=inconc_judge,
            judge_gates_verdict=True,
        )
        assert scored["checks"]["value"]["passed"] == 1
        assert scored["verdict"] == "INCONCLUSIVE"

    def test_routing_name_boundaries_id_renames_and_why_check(self) -> None:
        # Exact & word-boundary matching vs substring or look-alike decoy
        assert name_matches("Sales", "Sales") is True
        assert name_matches("Sales", "Sales Sandbox") is False
        assert name_matches("Salesman", "Sales") is False

        decoy_res = artifact_check(
            [{"name": "Sales Sandbox", "kind": "powerbi_report"}],
            None,
            expected_name="Sales",
            decoys="Sales Sandbox",
        )
        assert decoy_res["passed"] == 0
        assert decoy_res["matched_by"] == "decoy"
        assert decoy_res["decoy_hit"] is True

        # Display name changed ("Revenue Hub v3"), matched stably by expected_id
        renamed_res = artifact_check(
            [{"name": "Revenue Hub v3", "artifactId": REPORT_ID, "kind": "powerbi_report"}],
            None,
            expected_name="Legacy Sales Report",
            expected_id=REPORT_ID,
            expected_kind="powerbi_report",
        )
        assert renamed_res["passed"] == 1
        assert renamed_res["matched_by"] == "id"

        # Non-Power BI SharePoint lookalike surfaces diagnostic note in score_artifact
        sp_lookalike = score_artifact(
            [{"name": "Sales Analytics", "kind": "sharepoint", "answer_cited": True}],
            expected="Sales Analytics",
        )
        assert sp_lookalike["score"] == FAIL
        assert "non-Power BI item" in sp_lookalike["reason"]

        # model_check & score_model edge cases (tool_call evidence, decoy hit, disabled/none status)
        mc_tool = model_check(
            {
                "status": "observed",
                "routing_evidence": "tool_call",
                "queries": [{"arguments": {"dataset": "Sales Core"}}],
            },
            expected_model="Sales Core",
        )
        assert mc_tool["passed"] == 1
        assert mc_tool["correlation_confidence"] == "high"
        assert model_check({"status": "none", "queries": []}, expected_model="Sales Core")["passed"] == 0
        assert score_model("disabled", [], "Sales Core") is None
        assert score_model("observed", ["Sales Sandbox"], "Sales Core", decoys="Sales Sandbox")["score"] == FAIL  # type: ignore[index]

        # why_check consistency & mismatch
        assert why_check("")["passed"] == -1
        assert (
            why_check(
                {"sources": ["Wrong Deck"], "answer": 999.0},
                expected_artifact="Sales Report",
                answer_value=120.0,
            )["passed"]
            == 0
        )
        assert (
            why_check(
                "Computed from Sales Report",
                {"sources": ["Sales Report"], "answer": {"value": 120.0}},
                expected_artifact="Sales Report",
                answer_value=120.0,
            )["passed"]
            == 1
        )

        # load_gate_policy & verdict edge cases
        with pytest.raises(ValueError, match="Unknown gate profile"):
            load_gate_policy("does_not_exist")
        assert load_gate_policy("auto", surface="work-iq")["profile"] == "work_iq"
        assert load_gate_policy("auto", surface="mcp")["profile"] == "tool_call_evidence"
        assert verdict({"value": 1}, ask_ok=False) == "ERROR"
        assert verdict({"value": 1}, trace_status="missing", incomplete_on_missing_trace=True) == "INCONCLUSIVE"

    def test_score_observation_rejects_hallucinated_llm_extract_span(self) -> None:
        q = GoldenQuestion(
            id="Q_LLM_SPAN",
            question="What was EMEA revenue?",
            expected_value=4_200_000.0,
            unit="currency",
            currency="USD",
            expected_model="Sales Core",
            gates=["value"],
        )
        with pytest.raises(ValueError, match="Unsupported extract_mode"):
            score_observation(q, {"Answer": "$4.2M", "Status": "ok"}, None, extract_mode="bogus")

        # Answer literally says $3.1M; judge hallucinates $4.2M not in the answer text!
        bad_judge = _HallucinatingJudge(extract_payload={"value": 4_200_000.0, "span": "$4.2M"})
        rejected = score_observation(
            q,
            {"Answer": "EMEA revenue was $3.1M.", "Status": "ok", "trace": {"status": "disabled", "queries": []}},
            judge=bad_judge,
            extract_mode="llm_extract",
        )
        assert rejected["checks"]["value"]["passed"] == 0
        assert rejected["extraction_method"] != "llm_extract"

        # Judge cites literal span "$3.1M" that exists in text, but lies about numeric value 4.2M -> rejected!
        mismatch_judge = _HallucinatingJudge(extract_payload={"value": 4_200_000.0, "span": "$3.1M"})
        mismatch_res = score_observation(
            q,
            {
                "Answer": "Americas was $5.0M while EMEA was $3.1M.",
                "Status": "ok",
                "trace": {"status": "disabled", "queries": []},
            },
            judge=mismatch_judge,
            extract_mode="llm_extract",
        )
        assert mismatch_res["checks"]["value"]["passed"] == -1
        assert mismatch_res["extraction_method"] != "llm_extract"
        assert mismatch_res["verdict"] == "INCONCLUSIVE"

        # Dict-based question + range rejection + direct explicit span match + custom gate_policy
        dict_q = {
            "question": "What was EMEA revenue?",
            "expect": {"value": 4_200_000.0},
            "unit": "currency",
            "currency": "USD",
            "expected_model": "Sales Core",
        }
        range_res = score_observation(dict_q, {"answer": "EMEA revenue was $4.0M-$4.5M.", "ok": True})
        assert range_res["checks"]["value"]["passed"] == 0

        direct_explicit = score_observation(
            dict_q,
            {
                "answer": "Americas was $5.0M while EMEA was $4.2M.",
                "why_json": {"answer": "$4.2M"},
            },
            judge=_HallucinatingJudge(judge_score=PASS),
            gate_policy={"gates": ("value",), "profile": "custom", "routing_evidence": "engine+citations"},
            judge_gates_verdict=True,
        )
        assert direct_explicit["verdict"] == "PASS"
        assert direct_explicit["extraction_method"] == "explicit"
        assert direct_explicit["routing_evidence"] == "citations-only"

        # Judge cites genuine literal span "$4.2M" on an otherwise ambiguous two-region sentence -> accepted!
        honest_judge = _HallucinatingJudge(
            extract_payload={"value": 4_200_000.0, "span": "$4.2M"},
            judge_score=PASS,
        )
        accepted = score_observation(
            q,
            {
                "Answer": "Americas was $5.0M while EMEA was $4.2M.",
                "Status": "ok",
                "trace": EngineEvidence(status="disabled"),
            },
            judge=honest_judge,
            extract_mode="llm_extract",
        )
        assert accepted["checks"]["value"]["passed"] == 1
        assert accepted["extraction_method"] == "llm_extract"
        assert accepted["validated_span"] == "$4.2M"

        # Explicit structured why_json candidate extraction (both direct span & punctuation-normalized span)
        explicit_res = score_observation(
            q,
            {
                "answer": "Americas was $5,000,000 while EMEA was $4,200,000.",
                "why": "Computed from Sales Core",
                "why_json": {"answer": {"value": 4_200_000, "span": "$4200000"}, "sources": ["Sales Core"]},
                "tool_calls": [{"arguments": {"dataset": "Sales Core"}}],
            },
            extract_mode="explicit",
        )
        assert explicit_res["checks"]["value"]["passed"] == 1
        assert explicit_res["extraction_method"] == "explicit"
        assert explicit_res["routing_evidence"] == "tool_call"

        # Diagnostic closest mode + error observation
        closest_res = score_observation(
            q,
            {"answer_text": "Americas was $5.0M while EMEA was $4.2M."},
            extract_mode="closest",
        )
        assert closest_res["checks"]["value"]["passed"] == 1
        assert closest_res["extraction_method"] == "closest"

        err_obs = score_observation(q, {"answer_text": "", "error": "upstream 503"})
        assert err_obs["verdict"] == "ERROR"

        # LocalBackend.evaluate + result_row formatting
        clock = SimClock(datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc))
        ask_dict = {
            "AskId": "ask-lb",
            "QuestionId": q.id,
            "Attempt": 1,
            "TestUser": "eval.runner@contoso.com",
            "AskStartUtc": clock.now(),
            "Status": "ok",
            "Answer": "EMEA revenue was $4.2M.",
            "Why": "Used Sales Core.",
            "LatencyMs": 220.0,
            "WhyLatencyMs": 45.0,
            "Persona": "executive",
        }
        trace_dict = {
            "status": "disabled",
            "models": [],
            "queries": [],
            "stats": {"count": 0, "total": 0.0, "max": 0.0, "first_offset": None},
        }
        backend = LocalBackend(judge=honest_judge, gate_on_judge=True, clock=clock)
        s_rows, r_rows = backend.evaluate(
            "run-x",
            [{"q": q, "ask": ask_dict, "artifacts": [], "trace": trace_dict}],
        )
        assert s_rows
        assert r_rows[0]["Verdict"] == "PASS"

        err_row = result_row(
            "run-x",
            q,
            ask_dict,
            [],
            trace_dict,
            {},
            "foundry",
            clock.now(),
            backend_error="foundry timeout",
        )
        assert err_row["Verdict"] == "ERROR"
        assert err_row["Error"] == "foundry timeout"

    def test_foundry_code_bundle_size_and_isolated_execution(self) -> None:
        max_bytes = 256 * 1024
        sample_item = {
            "response": "Net revenue was $12.8M per [Sales Report](https://app.powerbi.com/groups/"
            f"{WS_ID}/reports/{REPORT_ID}).",
            "expected_value": "12800000",
            "unit": "currency",
            "rel_tol": "0.01",
            "abs_tol": "0",
            "expected_artifact": "Sales Report",
            "expected_artifact_id": REPORT_ID,
            "artifact_aliases": "",
            "expected_model": "Sales Core",
            "decoys": "Sales Sandbox",
            "cited": "Sales Report",
            "artifacts_json": json.dumps(
                [{"name": "Sales Report", "kind": "powerbi_report", "item_id": REPORT_ID, "answer_cited": True}]
            ),
            "trace_status": "observed",
            "queried_models": "Sales Core",
            "queried_models_json": json.dumps(["Sales Core"]),
            "routing_evidence": "engine+citations",
            "correlation_confidence": "high",
        }
        for check in CODE_EVALUATORS:
            bundle = code_bundle(check)
            encoded = bundle.encode("utf-8")
            assert len(encoded) < max_bytes, f"{check} bundle {len(encoded)}B exceeds 256 KiB limit"
            ns: dict[str, Any] = {"__name__": f"isolated_{check}"}
            exec(compile(bundle, f"<bundle-{check}>", "exec"), ns)  # noqa: S102
            score = ns["grade"]({}, sample_item)
            assert score == 1.0


# ---------------------------------------------------------------------------
# 6. trace.py
# ---------------------------------------------------------------------------


class _FakeKustoMonitoringClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.rows = rows or []
        self.fail = fail
        self.queries: list[tuple[str, str]] = []

    def query(self, database: str, kql: str) -> list[dict[str, Any]]:
        self.queries.append((database, kql))
        if self.fail:
            raise RuntimeError("kusto query failed")
        return list(self.rows)


class TestTraceModule:
    def test_chris_webb_index_noise_filter_and_malformed_application_context(self) -> None:
        # Chris Webb Copilot text-index build pattern: SELECTCOLUMNS(... VALUES ... LEN(...) <= 100 ... "valueColumn")
        index_dax = (
            "EVALUATE SELECTCOLUMNS("
            "FILTER(VALUES('Customer'[AccountName]), LEN('Customer'[AccountName]) <= 100), "
            "\"valueColumn\", 'Customer'[AccountName])"
        )
        assert is_noise_dax(index_dax) is True
        assert is_noise_dax(watermark_dax("probe-1")) is True
        assert is_noise_dax('EVALUATE SUMMARIZECOLUMNS("Rev", [Total Revenue])') is False

        # Valid JSON + nested Sources vs malformed JSON key-value fallback
        nested_ctx = json.dumps({"Sources": [{"DatasetId": MODEL_ID, "ReportId": REPORT_ID, "VisualId": "vis-7"}]})
        assert parse_application_context(nested_ctx) == {
            "DatasetId": MODEL_ID,
            "ReportId": REPORT_ID,
            "VisualId": "vis-7",
        }

        malformed_ctx = f"{{corrupt_json; DatasetId={MODEL_ID}; ReportId={REPORT_ID}; VisualId=card_01"
        assert parse_application_context(malformed_ctx) == {
            "DatasetId": MODEL_ID,
            "ReportId": REPORT_ID,
            "VisualId": "card_01",
        }
        assert parse_application_context(None) == {"DatasetId": "", "ReportId": "", "VisualId": ""}

    def test_overlapping_windows_run_window_low_confidence_and_other_user_filtering(self) -> None:
        t0 = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
        mem = InMemoryMonitoringSource()
        # 1) Noise index-build DAX from test user -> filtered out
        mem.record(
            FabricQuery(
                query_time=t0 + timedelta(seconds=2),
                workspace_id=WS_ID,
                item_id=MODEL_ID,
                item_name="Sales Core",
                application_name="PowerBI",
                operation_name="QueryEnd",
                duration_ms=15.0,
                dax='EVALUATE SELECTCOLUMNS(FILTER(VALUES(T[C]), LEN(T[C]) <= 100), "valueColumn", T[C])',
                correlation_id="c-noise",
                operation_id="op-noise",
                executing_user="eval.runner@contoso.com",
            )
        )
        # 2) Another user's query during the exact window -> filtered out
        mem.record(
            FabricQuery(
                query_time=t0 + timedelta(seconds=3),
                workspace_id=WS_ID,
                item_id=ALT_MODEL_ID,
                item_name="HR Confidential",
                application_name="PowerBI",
                operation_name="QueryEnd",
                duration_ms=40.0,
                dax='EVALUATE ROW("headcount", 500)',
                correlation_id="c-other",
                operation_id="op-other",
                executing_user="other.person@contoso.com",
            )
        )
        # 3) Test user's query arriving after per-ask window (matched only via broader run window -> low confidence!)
        late_q = FabricQuery(
            query_time=t0 + timedelta(seconds=55),
            workspace_id=WS_ID,
            item_id=MODEL_ID,
            item_name="Sales Core",
            application_name="PowerBI",
            operation_name="QueryEnd",
            duration_ms=82.0,
            dax='EVALUATE ROW("Rev", [Total Revenue])',
            correlation_id="c-late",
            operation_id="op-late",
            executing_user="eval.runner@contoso.com",
        )
        mem.record(late_q)

        fetched = mem.fetch("eval.runner@contoso.com", t0, t0 + timedelta(minutes=2))
        assert [q.correlation_id for q in fetched] == ["c-late"]

        # Overlapping windows: confidence drops from high to medium without artifact GUID match;
        # and drops to low when matched only via run_window fallback.
        w1 = AskWindow(ask_id="ask-1", start=t0, end=t0 + timedelta(seconds=10))
        w2 = AskWindow(ask_id="ask-2", start=t0 + timedelta(seconds=8), end=t0 + timedelta(seconds=18))
        in_window_q = FabricQuery(
            query_time=t0 + timedelta(seconds=9),
            workspace_id=WS_ID,
            item_id=MODEL_ID,
            item_name="Sales Core",
            application_name="PowerBI",
            operation_name="QueryEnd",
            duration_ms=30.0,
            dax='EVALUATE ROW("Rev", 10)',
            correlation_id="c-overlap",
            operation_id="op-overlap",
            executing_user="eval.runner@contoso.com",
        )
        assert (
            compute_correlation_confidence(
                "observed",
                [in_window_q],
                ask_window=w1,
                all_windows=[w1, w2],
                user_upn="eval.runner@contoso.com",
            )
            == "medium"
        )
        assert len(correlate([w1, w2], [in_window_q])["ask-2"]) == 1

        # Single ask where query fell outside ask+pad but inside run_window -> low confidence
        clock = SimClock(t0 + timedelta(minutes=2))
        single_ev = collect_traces(
            mem,
            run_id="run-1",
            asks=[{"AskId": "ask-1", "AskStartUtc": t0, "AskEndUtc": t0 + timedelta(seconds=10), "Artifacts": []}],
            started=t0,
            ended=t0 + timedelta(minutes=2),
            user_upn="eval.runner@contoso.com",
            clock=clock,
            wait_seconds=30.0,
            poll_seconds=5.0,
            settle_seconds=10.0,
            pad_after_s=5.0,
            log=lambda _m: None,
        )
        assert single_ev["ask-1"].status == "observed"
        assert single_ev["ask-1"].correlation_confidence == "low"

    def test_late_arrival_watermark_retry_timeout_and_workspace_monitoring_evidence_source(self) -> None:
        clock = SimClock(datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc))
        t0 = clock.now()

        with pytest.raises(ValueError, match="trace timeout must be non-negative"):
            wait_for_ingestion(InMemoryMonitoringSource(), t0, clock, timeout_s=-1)

        class _DelayedWatermarkSource:
            def __init__(self, appear_after_polls: int | None) -> None:
                self.polls = 0
                self.appear_after_polls = appear_after_polls

            def watermark_seen(self, marker: str, since: Any) -> bool:
                self.polls += 1
                return self.appear_after_polls is not None and self.polls >= self.appear_after_polls

            def latest_timestamp(self) -> datetime | None:
                return None

            def fetch(self, upn: str, start: Any, end: Any) -> list[FabricQuery]:
                return []

        delayed = _DelayedWatermarkSource(appear_after_polls=3)
        mode = wait_for_ingestion(
            delayed,
            t0,
            clock,
            timeout_s=30.0,
            poll_s=5.0,
            marker="wm-ok",
            since=t0,
            log=lambda _m: None,
        )
        assert mode == "watermark"
        assert delayed.polls == 3

        never_seen = _DelayedWatermarkSource(appear_after_polls=None)
        timed_out = wait_for_ingestion(
            never_seen,
            clock.now(),
            clock,
            timeout_s=10.0,
            poll_s=5.0,
            marker="wm-never",
            since=t0,
            log=lambda _m: None,
        )
        assert timed_out is None

        # Broken watermark sender falls back cleanly in collect_traces
        class _BrokenWatermark:
            def send(self, marker: str) -> None:
                raise RuntimeError("xmla endpoint unreachable")

        traced = collect_traces(
            never_seen,
            run_id="run-timeout",
            asks=[{"AskId": "ask-timeout", "AskStartUtc": t0, "AskEndUtc": t0 + timedelta(seconds=2)}],
            user_upn="eval.runner@contoso.com",
            watermark=_BrokenWatermark(),
            wait_seconds=5.0,
            poll_seconds=5.0,
            settle_seconds=5.0,
            clock=clock,
            log=lambda _m: None,
        )
        assert traced["ask-timeout"].status == "pending"

        # WorkspaceMonitoringEvidenceSource + CombinedMonitoringSource with fake Kusto runner
        kusto_rows = [
            {
                "Timestamp": "2026-04-01T12:00:01Z",
                "WorkspaceId": WS_ID,
                "ItemId": MODEL_ID,
                "ItemName": "Sales Core",
                "ApplicationName": "PowerBI",
                "OperationName": "QueryEnd",
                "DurationMs": 95.0,
                "CpuTimeMs": 45.0,
                "ExecutingUser": "eval.runner@contoso.com",
                "EventText": 'EVALUATE SUMMARIZECOLUMNS("Rev", [Total Revenue])',
                "CorrelationId": "corr-kusto-1",
                "OperationId": "op-kusto-1",
                "ApplicationContext": json.dumps({"DatasetId": MODEL_ID, "ReportId": REPORT_ID}),
                "Latest": "2026-04-01T12:05:00Z",
                "Seen": 1,
            }
        ]
        fake_kusto = _FakeKustoMonitoringClient(rows=kusto_rows)
        ws_mon = WorkspaceMonitoringSource(fake_kusto, "MonitoringDb")
        ev_source = WorkspaceMonitoringEvidenceSource(
            ws_mon,
            clock=clock,
            wait_seconds=30.0,
            poll_seconds=5.0,
            settle_seconds=10.0,
            log=lambda _m: None,
        )
        evidence_map = ev_source.collect(
            run_id="run-ev",
            asks=[
                {
                    "AskId": "ask-ev",
                    "AskStartUtc": t0,
                    "AskEndUtc": t0 + timedelta(seconds=4),
                    "Artifacts": [{"item_id": REPORT_ID}],
                }
            ],
            started=t0,
            ended=t0 + timedelta(seconds=4),
            user_upn="eval.runner@contoso.com",
        )
        ev = evidence_map["ask-ev"]
        assert ev.status == "observed"
        assert ev.correlation_confidence == "high"
        assert ev.queries[0]["ItemName"] == "Sales Core"

        bad_src = WorkspaceMonitoringSource(_FakeKustoMonitoringClient(fail=True), "Db2")
        combined = CombinedMonitoringSource([ws_mon, bad_src])
        with pytest.raises(TraceCollectionError, match="Workspace monitoring read failed"):
            combined.fetch("eval.runner@contoso.com", t0, t0 + timedelta(minutes=1))
