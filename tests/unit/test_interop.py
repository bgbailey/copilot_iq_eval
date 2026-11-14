"""Offline unit tests for cfeval.interop transcript loading, Promptfoo YAML export, and Foundry JSONL export."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from cfeval.foundry import FIELDS, code_bundle
from cfeval.interop import export_foundry_jsonl, export_promptfoo, load_transcript_records
from cfeval.sinks import JsonlSink

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TRANSCRIPT = REPO_ROOT / "samples" / "contoso" / "transcript_sample.jsonl"
CONTOSO_GOLDEN = REPO_ROOT / "data" / "golden" / "contoso.yaml"


def test_load_transcript_records_across_jsonl_json_csv_and_markdown(tmp_path: Path) -> None:
    # 1. Sample JSONL
    jsonl_recs = load_transcript_records(SAMPLE_TRANSCRIPT)
    assert len(jsonl_recs) == 8
    assert jsonl_recs[0]["id"] == "Q01"
    assert "12.84M" in jsonl_recs[0]["answer"]
    assert jsonl_recs[0]["citations"][0]["name"] == "Sales Analytics"
    assert "Gross Revenue" in jsonl_recs[0]["why"]

    # 2. JSON object with {"records": [...]}
    json_path = tmp_path / "records.json"
    json_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "QuestionId": "J01",
                        "Prompt": "What is gross margin?",
                        "Response": "Gross margin is 44.2%.",
                        "Artifacts": "Finance Margin; Margin Summary",
                        "queried_model": "Finance Margin",
                        "tool_calls": [{"name": "execute_dax", "arguments": {"query": "EVALUATE {0.442}"}}],
                        "LatencyMs": "920",
                        "why_json": '{"answer": "44.2%"}',
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    j_recs = load_transcript_records(json_path)
    assert len(j_recs) == 1
    assert j_recs[0]["id"] == "J01"
    assert [c["name"] for c in j_recs[0]["citations"]] == ["Finance Margin", "Margin Summary"]
    assert j_recs[0]["dax"] == "EVALUATE {0.442}"
    assert j_recs[0]["latency_ms"] == 920.0
    assert j_recs[0]["why_json"] == {"answer": "44.2%"}

    # 3. CSV
    csv_path = tmp_path / "records.csv"
    csv_link = "[Sales Analytics](https://app.powerbi.com/groups/g/reports/r1)"
    csv_path.write_text(
        "question_id,question,answer_text,citations,model,latency_ms\n"
        f'C01,"Active customers?","There were 312 active customers.","{csv_link}",Sales Analytics,1250\n',
        encoding="utf-8",
    )
    c_recs = load_transcript_records(csv_path)
    assert len(c_recs) == 1
    assert c_recs[0]["id"] == "C01"
    assert c_recs[0]["citations"][0]["name"] == "Sales Analytics"
    assert c_recs[0]["citations"][0]["url"].startswith("https://app.powerbi.com/")

    # 4. GitHub Markdown table (including escaped pipe inside cell)
    md_path = tmp_path / "records.md"
    md_path.write_text(
        "# Evaluation Transcript\n\n"
        "| id | question | answer | citations | dax |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        r"| M01 | Revenue A \| B? | Revenue was $4.2M. | Sales Analytics | EVALUATE {4200000} |"
        "\n",
        encoding="utf-8",
    )
    m_recs = load_transcript_records(md_path)
    assert len(m_recs) == 1
    assert m_recs[0]["id"] == "M01"
    assert m_recs[0]["question"] == "Revenue A | B?"
    assert m_recs[0]["dax"] == "EVALUATE {4200000}"


def test_export_promptfoo_generates_valid_yaml_with_mapped_assertions(tmp_path: Path) -> None:
    out_yaml = tmp_path / "promptfooconfig.yaml"
    returned = export_promptfoo(CONTOSO_GOLDEN, out_yaml)
    assert returned == out_yaml

    cfg = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
    assert cfg["prompts"] == ["{{question}}"]
    assert isinstance(cfg["providers"], list) and len(cfg["providers"]) >= 1
    tests = cfg["tests"]
    assert len(tests) == 42

    # Q01 scalar + expected_artifact + decoy
    q01 = next(t for t in tests if t["vars"]["question_id"] == "Q01")
    assert "gross revenue" in q01["vars"]["question"].lower()
    metrics_q01 = {a.get("metric") for a in q01["assert"]}
    assert {"value_match", "expected_artifact", "no_decoy"} <= metrics_q01

    # Q24 ranked_list
    q24 = next(t for t in tests if t["vars"]["question_id"] == "Q24")
    assert any(a["type"] == "icontains" and a["value"] == "Cloud Platform" for a in q24["assert"])

    # Q33 record
    q33 = next(t for t in tests if t["vars"]["question_id"] == "Q33")
    assert any(a.get("metric") == "record_gross_revenue" for a in q33["assert"])

    # Q38 abstention
    q38 = next(t for t in tests if t["vars"]["question_id"] == "Q38")
    assert any(a.get("metric") == "abstention" for a in q38["assert"])


def test_export_foundry_jsonl_roundtrips_with_foundry_code_bundle(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_export"
    sink = JsonlSink(run_dir)
    t0 = datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)

    sink.write(
        "EvalRun",
        [
            {
                "RunId": "run-exp-01",
                "RunName": "Export Test",
                "StartedUtc": t0,
                "EndedUtc": t0 + timedelta(seconds=10),
                "TraceEnabled": 1,
                "Status": "completed",
            }
        ],
    )
    sink.write(
        "EvalQuestion",
        [
            {
                "RunId": "run-exp-01",
                "QuestionId": "Q01",
                "Question": "What was gross revenue in FY2025?",
                "Category": "named-source",
                "ExpectedArtifact": "Sales Analytics",
                "ExpectedArtifactId": "e084ee51-d06c-5bf0-bfcb-4aede296f141",
                "ExpectedModel": "Sales Analytics",
                "Decoys": "Sales Forecast Legacy",
                "ExpectedValue": 12840000.0,
                "Unit": "currency",
                "RelTol": 0.005,
                "AbsTol": 0.0,
                "CaseType": "scalar",
            }
        ],
    )
    sink.write(
        "EvalAsk",
        [
            {
                "RunId": "run-exp-01",
                "AskId": "run-exp-01:Q01:1",
                "QuestionId": "Q01",
                "Attempt": 1,
                "Question": "What was gross revenue in FY2025?",
                "TestUser": "eval.tester@contoso.com",
                "AskStartUtc": t0,
                "AskEndUtc": t0 + timedelta(seconds=2),
                "Status": "ok",
                "Answer": "Gross revenue in FY2025 was $12.84M.",
                "Why": "Queried Sales Analytics",
                "Artifacts": [
                    {
                        "name": "Sales Analytics",
                        "kind": "powerbi_report",
                        "source": "attribution",
                        "item_id": "e084ee51-d06c-5bf0-bfcb-4aede296f141",
                        "url": "https://app.powerbi.com/groups/g/reports/e084ee51-d06c-5bf0-bfcb-4aede296f141",
                    }
                ],
            }
        ],
    )
    sink.write(
        "FabricIqQuery",
        [
            {
                "RunId": "run-exp-01",
                "AskId": "run-exp-01:Q01:1",
                "QueryTimeUtc": t0 + timedelta(seconds=1),
                "OffsetMs": 1000.0,
                "WorkspaceId": "ws-1",
                "ItemId": "e084ee51-d06c-5bf0-bfcb-4aede296f141",
                "ItemName": "Sales Analytics",
                "ApplicationName": "PowerBI",
                "OperationName": "QueryEnd",
                "DurationMs": 30.0,
                "Dax": 'EVALUATE ROW("Gross Revenue", 12840000)',
                "DaxChars": 38,
                "CorrelationId": "corr-1",
            }
        ],
    )

    out_jsonl = tmp_path / "foundry_dataset.jsonl"
    exported = export_foundry_jsonl(run_dir, out_jsonl)
    assert exported == out_jsonl

    rows = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == set(FIELDS)
    assert row["expected_artifact_id"] == "e084ee51-d06c-5bf0-bfcb-4aede296f141"
    assert row["routing_evidence"] == "engine+citations"

    # Verify exported row grades 1.0 on all 3 Foundry code evaluators
    for check in ("value", "artifact", "model"):
        ns: dict[str, object] = {}
        exec(compile(code_bundle(check), f"<foundry-{check}>", "exec"), ns)
        grade_fn = ns["grade"]
        assert callable(grade_fn)
        assert grade_fn(None, row) == 1.0
