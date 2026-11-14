"""Contract tests for EvalHarness, --no-trace gate policies, and pluggable Target implementations."""

from __future__ import annotations

import json
from pathlib import Path

from cfeval.cli import build_harness, main
from cfeval.config import Settings
from cfeval.golden import load_golden
from cfeval.pipeline import EvalHarness, EvaluationHarness
from cfeval.sinks import JsonlSink
from cfeval.targets import get_target, list_targets

ROOT = Path(__file__).resolve().parents[2]
SMOKE_YAML = ROOT / "data" / "golden" / "contoso-smoke.yaml"


def test_evaluation_harness_alias() -> None:
    assert EvaluationHarness is EvalHarness


def test_no_trace_uses_without_engine_evidence_gates_in_both_backends(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"OUTPUT_DIR={tmp_path}\n", encoding="utf-8")

    rc = main(
        [
            "--env",
            str(env_file),
            "run",
            "--mock",
            "--profile",
            "tuned",
            "--option",
            "both",
            "--no-trace",
            "--no-publish",
            "--golden",
            str(SMOKE_YAML),
            "--run-id",
            "run-notrace-both",
        ]
    )
    assert rc == 0

    sink = JsonlSink(tmp_path / "run-notrace-both")
    results = sink.read("EvalResult")
    native = [r for r in results if r["Backend"] == "fabric-native"]
    foundry = [r for r in results if r["Backend"] == "foundry"]
    assert len(native) > 0 and len(native) == len(foundry)

    for row in native:
        assert row["TraceStatus"] == "disabled"
        assert row["Verdict"] == "PASS", f"Expected PASS under --no-trace for {row['QuestionId']}, got {row['Verdict']}"

    for row in foundry:
        assert row["TraceStatus"] == "disabled"
        assert row["Verdict"] == "PASS", (
            f"Foundry expected PASS under --no-trace for {row['QuestionId']}, got {row['Verdict']}"
        )


def test_targets_registry_and_cli_listing(capsys, tmp_path: Path) -> None:
    registered = {t["name"]: t for t in list_targets()}
    for expected in ("copilot-chat", "transcript-import", "mcp-agent", "fabric-data-agent"):
        assert expected in registered

    assert registered["mcp-agent"]["supports_engine_trace"] is True
    assert registered["transcript-import"]["supports_engine_trace"] is False
    assert registered["fabric-data-agent"]["experimental"] is True

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    rc = main(["--env", str(env_file), "targets"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "copilot-chat" in captured
    assert "transcript-import" in captured
    assert "mcp-agent" in captured
    assert "fabric-data-agent" in captured


def test_mcp_agent_and_data_agent_targets_conformance(tmp_path: Path) -> None:
    questions = load_golden(SMOKE_YAML)[:3]
    settings = Settings(output_dir=str(tmp_path))

    mcp_harness = build_harness(
        settings,
        option="fabric-native",
        mock=True,
        publish=False,
        profile="tuned",
        questions=questions,
        target_name="mcp-agent",
        run_id="run-mcp-conformance",
        log=lambda *_: None,
    )
    mcp_outcome = mcp_harness.run()
    assert mcp_outcome.run_row["Target"] == "mcp-agent"
    assert mcp_outcome.metrics["error"] == 0
    non_abstention = [
        r
        for r in mcp_outcome.results
        if r["QuestionId"] in {q.id for q in questions if q.case_type not in ("abstention", "negative")}
    ]
    assert non_abstention
    assert all(r["RoutingEvidence"] == "tool_call" for r in non_abstention)
    mcp_queries = JsonlSink(mcp_outcome.folder).read("FabricIqQuery")
    assert len(mcp_queries) >= len(non_abstention)

    da_harness = build_harness(
        settings,
        option="fabric-native",
        mock=True,
        publish=False,
        profile="tuned",
        questions=questions,
        target_name="fabric-data-agent",
        run_id="run-da-conformance",
        log=lambda *_: None,
    )
    da_outcome = da_harness.run()
    assert da_outcome.run_row["Target"] == "fabric-data-agent"
    assert da_outcome.metrics["error"] == 0
    assert len(da_outcome.results) == len(questions)


def test_transcript_import_target_conformance(tmp_path: Path) -> None:
    questions = load_golden(SMOKE_YAML)[:2]
    transcript_path = tmp_path / "transcript.jsonl"
    records = []
    for q in questions:
        records.append(
            {
                "id": q.id,
                "question": q.question,
                "answer": q.expected_answer or f"The answer is {q.expected_value}.",
                "citations": [{"name": q.expected_artifact, "kind": "powerbi_report"}] if q.expected_artifact else [],
                "latency_ms": 120.0,
            }
        )
    transcript_path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    tgt = get_target("transcript-import", transcript_path=transcript_path, questions=questions)
    assert tgt.name == "transcript-import"
    assert tgt.supports_engine_trace is False

    env_file = tmp_path / ".env"
    env_file.write_text(f"OUTPUT_DIR={tmp_path}\n", encoding="utf-8")
    q_filter = ",".join(q.id for q in questions)
    rc = main(
        [
            "--env",
            str(env_file),
            "run",
            "--target",
            "transcript-import",
            "--transcript",
            str(transcript_path),
            "--golden",
            str(SMOKE_YAML),
            "--questions",
            q_filter,
            "--no-publish",
            "--run-id",
            "run-transcript-conformance",
        ]
    )
    assert rc == 0
    results = JsonlSink(tmp_path / "run-transcript-conformance").read("EvalResult")
    assert len(results) == len(questions)
    assert all(r["Verdict"] == "PASS" for r in results)
