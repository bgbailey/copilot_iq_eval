"""End-to-end offline integration tests for Pipeline v2, CLI v2, and deterministic demo-data."""

from __future__ import annotations

import json
from pathlib import Path

from cfeval.cli import main
from cfeval.sinks import JsonlSink

ROOT = Path(__file__).resolve().parents[2]
CONTOSO_YAML = ROOT / "data" / "golden" / "contoso.yaml"
CONTOSO_WORK_YAML = ROOT / "data" / "golden" / "contoso-work.yaml"
CONTOSO_SMOKE_YAML = ROOT / "data" / "golden" / "contoso-smoke.yaml"
CALIBRATION_JSONL = ROOT / "data" / "judge_calibration" / "answers.jsonl"


def _write_env(tmp_path: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(f"OUTPUT_DIR={tmp_path / 'runs'}\nPAUSE_SECONDS=0\n", encoding="utf-8")
    return env_file


def test_full_contoso_v2_suite_offline(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)
    html_out = tmp_path / "contoso_report.html"
    otel_out = tmp_path / "contoso_otel.json"

    rc = main(
        [
            "--env",
            str(env_file),
            "run",
            "--mock",
            "--profile",
            "tuned",
            "--golden",
            str(CONTOSO_YAML),
            "--no-publish",
            "--strict",
            "--run-id",
            "run-contoso-42",
            "--html",
            str(html_out),
            "--otel-out",
            str(otel_out),
        ]
    )
    assert rc == 0
    run_dir = tmp_path / "runs" / "run-contoso-42"
    sink = JsonlSink(run_dir)
    run_rows = sink.read("EvalRun")
    assert len(run_rows) == 1
    run_row = run_rows[0]
    assert run_row["QuestionCount"] == 42
    assert run_row["AskCount"] == 42
    assert run_row["PassRate"] == 1.0
    assert run_row["SchemaVersion"] == 2
    assert run_row["K"] == 1
    assert run_row["PassPowK"] == 1.0
    assert 0.90 <= run_row["WilsonLow"] <= 1.0
    assert run_row["WilsonHigh"] == 1.0
    assert run_row["JudgePromptHash"]
    assert run_row["GatePolicyHash"]

    q_rows = sink.read("EvalQuestion")
    case_types = {q["CaseType"] for q in q_rows}
    for expected_ct in ("scalar", "ranked_list", "set", "table", "record", "abstention", "direction"):
        assert expected_ct in case_types

    iq_rows = sink.read("FabricIqQuery")
    assert len(iq_rows) > 0
    assert all(r.get("OperationId") for r in iq_rows)
    assert all(r.get("ApplicationContext") for r in iq_rows)

    summary_md = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "## Known measurement limitations" in summary_md
    assert "Wilson 95% CI" in summary_md
    assert html_out.is_file()
    assert otel_out.is_file()


def test_work_iq_suite_offline_no_trace(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)
    rc = main(
        [
            "--env",
            str(env_file),
            "run",
            "--mock",
            "--profile",
            "tuned",
            "--golden",
            str(CONTOSO_WORK_YAML),
            "--no-trace",
            "--no-publish",
            "--strict",
            "--run-id",
            "run-work-iq-22",
        ]
    )
    assert rc == 0
    run_dir = tmp_path / "runs" / "run-work-iq-22"
    sink = JsonlSink(run_dir)
    results = sink.read("EvalResult")
    assert len(results) == 22
    assert all(r["Verdict"] == "PASS" for r in results)
    assert sink.read("FabricIqQuery") == []


def test_option_both_backends_agree_under_no_trace(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)
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
            str(CONTOSO_SMOKE_YAML),
            "--run-id",
            "run-both-smoke",
        ]
    )
    assert rc == 0
    results = JsonlSink(tmp_path / "runs" / "run-both-smoke").read("EvalResult")
    by_backend: dict[str, dict[str, str]] = {"fabric-native": {}, "foundry": {}}
    for r in results:
        by_backend[r["Backend"]][r["QuestionId"]] = r["Verdict"]
    assert by_backend["fabric-native"] == by_backend["foundry"]
    assert all(v == "PASS" for v in by_backend["fabric-native"].values())


def test_compare_runs_and_regression_exit_code(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)
    assert (
        main(
            [
                "--env",
                str(env_file),
                "run",
                "--mock",
                "--profile",
                "baseline",
                "--golden",
                str(CONTOSO_SMOKE_YAML),
                "--no-publish",
                "--run-id",
                "run-base",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--env",
                str(env_file),
                "run",
                "--mock",
                "--profile",
                "tuned",
                "--golden",
                str(CONTOSO_SMOKE_YAML),
                "--no-publish",
                "--run-id",
                "run-tuned",
            ]
        )
        == 0
    )

    base_dir = tmp_path / "runs" / "run-base"
    tuned_dir = tmp_path / "runs" / "run-tuned"
    cmp_json = tmp_path / "compare.json"
    cmp_md = tmp_path / "compare.md"

    rc_improve = main(
        [
            "--env",
            str(env_file),
            "compare",
            "--baseline",
            str(base_dir),
            "--candidate",
            str(tuned_dir),
            "--max-regressions",
            "0",
            "--json-out",
            str(cmp_json),
            "--md-out",
            str(cmp_md),
        ]
    )
    assert rc_improve == 0
    cmp_data = json.loads(cmp_json.read_text(encoding="utf-8"))
    assert cmp_data["delta_pass_rate"] > 0
    assert cmp_data["b"] == 0
    assert cmp_md.is_file()

    rc_regress = main(
        [
            "--env",
            str(env_file),
            "compare",
            "--baseline",
            str(tuned_dir),
            "--candidate",
            str(base_dir),
            "--max-regressions",
            "0",
        ]
    )
    assert rc_regress == 1


def test_golden_lint_and_calibrate_judge_cli(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)
    assert main(["--env", str(env_file), "golden-lint"]) == 0

    bad_yaml = tmp_path / "invalid_golden.yaml"
    bad_yaml.write_text("version: 2\nquestions:\n  - id: BAD1\n", encoding="utf-8")
    assert main(["--env", str(env_file), "golden-lint", str(bad_yaml)]) == 1

    cal_json = tmp_path / "calibration.json"
    rc_cal = main(
        [
            "--env",
            str(env_file),
            "calibrate-judge",
            "--dataset",
            str(CALIBRATION_JSONL),
            "--mock",
            "--min-kappa",
            "0.70",
            "--json-out",
            str(cal_json),
        ]
    )
    assert rc_cal == 0
    cal_payload = json.loads(cal_json.read_text(encoding="utf-8"))
    assert cal_payload["ok"] is True
    assert cal_payload["kappa"] >= 0.70


def test_demo_data_byte_identical_and_zero_duplicate_rowids(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)
    out_a = tmp_path / "sample_a.json"
    out_b = tmp_path / "sample_b.json"

    for dst in (out_a, out_b):
        rc = main(
            [
                "--env",
                str(env_file),
                "demo-data",
                "--as-of",
                "2026-11-01T12:00:00Z",
                "--app-json",
                str(dst),
            ]
        )
        assert rc == 0

    bytes_a = out_a.read_bytes()
    bytes_b = out_b.read_bytes()
    assert bytes_a == bytes_b, "Two consecutive demo-data invocations with identical --as-of must be byte-identical"
    parsed = json.loads(bytes_a.decode("utf-8"))
    assert parsed["generatedUtc"] == "2026-11-01T12:00:00.000Z"
    assert len(parsed["tables"]) == 5
    for table_name, rows in parsed["tables"].items():
        assert len(rows) > 0, f"Expected non-empty {table_name} in demo-data bundle"
        row_ids = [r["RowId"] for r in rows]
        assert len(row_ids) == len(set(row_ids)), f"Duplicate RowIds detected in {table_name}"


def test_sharding_resume_rescore_export_and_verify(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path)

    for shard_idx in (0, 1):
        rc = main(
            [
                "--env",
                str(env_file),
                "run",
                "--mock",
                "--profile",
                "tuned",
                "--golden",
                str(CONTOSO_SMOKE_YAML),
                "--shard",
                f"{shard_idx}/2",
                "--no-publish",
                "--run-id",
                f"run-shard-{shard_idx}",
            ]
        )
        assert rc == 0

    q_shard_0 = {r["QuestionId"] for r in JsonlSink(tmp_path / "runs" / "run-shard-0").read("EvalAsk")}
    q_shard_1 = {r["QuestionId"] for r in JsonlSink(tmp_path / "runs" / "run-shard-1").read("EvalAsk")}
    assert q_shard_0.isdisjoint(q_shard_1)
    smoke_total = len(JsonlSink(tmp_path / "runs" / "run-shard-0").read("EvalQuestion")) + len(
        JsonlSink(tmp_path / "runs" / "run-shard-1").read("EvalQuestion")
    )
    assert len(q_shard_0 | q_shard_1) == smoke_total

    # Test --max-questions partial run followed by --resume completing the rest
    rc_part = main(
        [
            "--env",
            str(env_file),
            "run",
            "--mock",
            "--profile",
            "tuned",
            "--golden",
            str(CONTOSO_SMOKE_YAML),
            "--max-questions",
            "3",
            "--no-publish",
            "--run-id",
            "run-resume-demo",
        ]
    )
    assert rc_part == 0
    resume_dir = tmp_path / "runs" / "run-resume-demo"
    first_asks = JsonlSink(resume_dir).read("EvalAsk")
    assert len(first_asks) == 3
    first_convs = {a["QuestionId"]: a["ConversationId"] for a in first_asks}

    rc_full = main(
        [
            "--env",
            str(env_file),
            "run",
            "--mock",
            "--profile",
            "tuned",
            "--golden",
            str(CONTOSO_SMOKE_YAML),
            "--resume",
            "--no-publish",
            "--run-id",
            "run-resume-demo",
        ]
    )
    assert rc_full == 0
    resumed_asks = JsonlSink(resume_dir).read("EvalAsk")
    # Only the remaining questions were appended; the initial 3 asks kept their original ConversationIds
    assert len(resumed_asks) == smoke_total
    by_qid = {a["QuestionId"]: a["ConversationId"] for a in resumed_asks}
    for qid, conv in first_convs.items():
        assert by_qid[qid] == conv

    # Offline rescore preserves rich case_type expectations from run.json questions_meta
    rc_rescore = main(
        [
            "--env",
            str(env_file),
            "rescore",
            str(resume_dir),
            "--mock",
            "--no-trace",
            "--no-publish",
        ]
    )
    assert rc_rescore == 0

    # Export Promptfoo YAML and Foundry JSONL
    pf_out = tmp_path / "promptfooconfig.yaml"
    fd_out = tmp_path / "foundry_dataset.jsonl"
    assert (
        main(
            [
                "--env",
                str(env_file),
                "export",
                "--format",
                "promptfoo",
                "--golden",
                str(CONTOSO_SMOKE_YAML),
                "--out",
                str(pf_out),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--env",
                str(env_file),
                "export",
                "--format",
                "foundry",
                "--run-dir",
                str(resume_dir),
                "--out",
                str(fd_out),
            ]
        )
        == 0
    )
    assert pf_out.is_file() and fd_out.is_file()

    # End-to-end verify command
    assert main(["--env", str(env_file), "verify", "--mock", "--golden", str(CONTOSO_SMOKE_YAML), "--strict"]) == 0
