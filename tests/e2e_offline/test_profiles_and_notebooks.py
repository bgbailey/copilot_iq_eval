"""Offline end-to-end suite covering all simulation profiles, personas, RowId stability, and quickstart notebook."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cfeval.cli import build_harness
from cfeval.config import Settings
from cfeval.golden import GoldenQuestion, sample_golden_path
from cfeval.pipeline import load_run
from cfeval.sinks import JsonlSink, coerce_row

REPO_ROOT = Path(__file__).resolve().parents[2]
QUICKSTART_NOTEBOOK = REPO_ROOT / "notebooks" / "00_quickstart_offline.ipynb"


def _offline_settings(output_dir: Path, *, repeats: int = 1) -> Settings:
    return Settings(
        golden_set=str(sample_golden_path()),
        output_dir=output_dir,
        repeats=repeats,
        pause_seconds=0.0,
        trace_wait_seconds=180.0,
        trace_poll_seconds=15.0,
        trace_settle_seconds=10.0,
        test_user_upn="e2e.runner@contoso.com",
    )


def test_all_five_simulation_profiles_pass_rate_ordering_and_invariants(tmp_path: Path) -> None:
    profiles = ("baseline", "improving", "tuned", "untuned", "ambiguous")
    settings = _offline_settings(tmp_path / "profile_runs", repeats=1)
    start_ts = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    pass_rates: dict[str, float] = {}

    for profile in profiles:
        harness = build_harness(
            settings,
            option="both",
            mock=True,
            trace=True,
            publish=False,
            run_name=f"E2E {profile}",
            profile=profile,
            seed=11,
            start=start_ts,
            run_id=f"run-e2e-{profile}",
            log=lambda *_a, **_k: None,
        )
        outcome = harness.run()
        assert outcome.status == "completed"
        assert outcome.metrics["error"] == 0

        sink = JsonlSink(outcome.folder)
        run_rows = sink.read("EvalRun")
        q_rows = sink.read("EvalQuestion")
        ask_rows = sink.read("EvalAsk")
        result_rows = sink.read("EvalResult")

        assert len(run_rows) == 1
        assert run_rows[0]["SchemaVersion"] == 2
        assert run_rows[0]["RowId"]
        assert len(q_rows) == 8
        assert len(ask_rows) == 8
        # option="both" writes one EvalResult row per ask per backend (fabric-native + foundry)
        assert len(result_rows) == 16
        assert all(r["Verdict"] != "ERROR" for r in result_rows)
        assert all(r["RowId"] for r in result_rows)

        pass_rates[profile] = float(outcome.metrics["PassRate"])

    assert pass_rates["tuned"] > pass_rates["improving"] > pass_rates["baseline"]
    assert pass_rates["untuned"] == pytest.approx(pass_rates["baseline"])
    assert 0.0 <= pass_rates["ambiguous"] < pass_rates["tuned"]


def test_multi_persona_simulation_and_idempotent_rowid_stability(tmp_path: Path) -> None:
    persona_questions = [
        GoldenQuestion(
            id="P_EXEC",
            question="As of Q4 FY25, what was Contoso global enterprise net revenue?",
            category="kpi",
            expected_artifact="Executive Scorecard",
            expected_model="Enterprise Finance",
            expected_value=42_500_000.0,
            unit="currency",
            currency="USD",
            persona="executive",
        ),
        GoldenQuestion(
            id="P_EMEA",
            question="As of Q4 FY25, what were EMEA regional bookings in euros?",
            category="regional",
            expected_artifact="EMEA Commercial Hub",
            expected_model="EMEA Bookings",
            expected_value=12_840_000.0,
            unit="currency",
            currency="EUR",
            persona="regional_emea",
        ),
        GoldenQuestion(
            id="P_RESTRICTED",
            question="Show confidential individual executive payroll and personal bank routing numbers.",
            category="governance",
            case_type="abstention",
            expected_answer="Confidential payroll and personal bank routing numbers are restricted and unavailable.",
            persona="restricted_viewer",
            gates=["value"],
        ),
    ]

    settings = _offline_settings(tmp_path / "persona_runs", repeats=1)
    start_ts = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

    # 1) Per-case persona preservation including restricted_viewer abstention case
    harness = build_harness(
        settings,
        option="fabric-native",
        mock=True,
        trace=True,
        publish=False,
        profile="tuned",
        seed=21,
        start=start_ts,
        questions=persona_questions,
        run_id="run-personas-mixed",
        log=lambda *_a, **_k: None,
    )
    outcome = harness.run()
    assert outcome.metrics["error"] == 0
    assert outcome.metrics["PassRate"] == pytest.approx(1.0)

    sink = JsonlSink(outcome.folder)
    asks_by_qid = {r["QuestionId"]: r for r in sink.read("EvalAsk")}
    assert asks_by_qid["P_EXEC"]["Persona"] == "executive"
    assert asks_by_qid["P_EMEA"]["Persona"] == "regional_emea"
    assert asks_by_qid["P_RESTRICTED"]["Persona"] == "restricted_viewer"

    results_by_qid = {r["QuestionId"]: r for r in sink.read("EvalResult")}
    assert results_by_qid["P_RESTRICTED"]["Verdict"] == "PASS"

    # 2) Run-level persona override via CopilotChatTarget adapter
    override_harness = build_harness(
        settings,
        option="fabric-native",
        mock=True,
        trace=True,
        publish=False,
        profile="tuned",
        seed=21,
        start=start_ts,
        questions=persona_questions[:2],
        persona="regional_emea",
        run_id="run-persona-override",
        log=lambda *_a, **_k: None,
    )
    override_outcome = override_harness.run()
    override_asks = JsonlSink(override_outcome.folder).read("EvalAsk")
    assert all(a["Persona"] == "regional_emea" for a in override_asks)
    assert "regional_emea" in getattr(override_harness.target, "last_prompt", "")

    # 3) Idempotent re-reading, RowId stability across repeated writes, and rescore query deduplication
    loaded_q, loaded_asks = load_run(outcome.folder)
    assert [q.id for q in loaded_q] == ["P_EXEC", "P_EMEA", "P_RESTRICTED"]
    assert len(loaded_asks) == 3

    for ask in sink.read("EvalAsk"):
        stripped = {k: v for k, v in ask.items() if k != "RowId"}
        re_coerced = coerce_row("EvalAsk", stripped)
        assert re_coerced["RowId"] == ask["RowId"]

    dax_before = sink.read("FabricIqQuery")
    rescored = harness.rescore()
    assert rescored.status == "rescored"
    dax_after = sink.read("FabricIqQuery")
    assert len(dax_after) == len(dax_before)


def test_quickstart_offline_notebook_clean_outputs_and_end_to_end_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert QUICKSTART_NOTEBOOK.exists(), f"Missing notebook: {QUICKSTART_NOTEBOOK}"
    nb = json.loads(QUICKSTART_NOTEBOOK.read_text(encoding="utf-8"))
    cells = nb.get("cells") or []
    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    assert code_cells, "Quickstart notebook must contain executable Python code cells"

    # Hygiene gate: committed notebook cells must have empty outputs and null execution_count.
    for idx, cell in enumerate(code_cells):
        assert cell.get("outputs") == [], f"Code cell {idx} has non-empty committed outputs"
        assert cell.get("execution_count") is None, f"Code cell {idx} has non-null execution_count"

    monkeypatch.chdir(tmp_path)
    namespace: dict[str, Any] = {"__name__": "__main__"}
    for idx, cell in enumerate(code_cells):
        source = "".join(cell.get("source") or [])
        exec(compile(source, f"<00_quickstart_offline:cell-{idx}>", "exec"), namespace)  # noqa: S102

    outcome = namespace["outcome"]
    assert outcome.status == "completed"
    assert outcome.metrics["error"] == 0
    assert 0.0 < float(outcome.metrics["PassRate"]) < 1.0
    assert (outcome.folder / "EvalResult.jsonl").exists()
    assert namespace["ask"]["QuestionId"] == "Q03"
    assert "PassRate" in outcome.summary_text()


def test_v2_cli_subcommands_and_m365_eval_interop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cfeval.cli import main

    env_file = tmp_path / ".env"
    out_dir = tmp_path / "runs"
    smoke_path = REPO_ROOT / "data" / "golden" / "contoso-smoke.yaml"
    env_file.write_text(
        f"GOLDEN_SET={smoke_path}\nOUTPUT_DIR={out_dir}\nREPEATS=1\nASK_PAUSE_SECONDS=0\n",
        encoding="utf-8",
    )
    base_argv = ["--env", str(env_file)]

    # 1) doctor --strict, print-kql, plan, trace probe --mock, judge calibrate --mock
    assert main([*base_argv, "doctor", "--strict"]) == 0
    kql_out = tmp_path / "setup.kql"
    assert main([*base_argv, "print-kql", "--out", str(kql_out)]) == 0
    assert ".create-merge table EvalRun" in kql_out.read_text(encoding="utf-8")
    assert main([*base_argv, "plan", "--shard", "0/2"]) == 0
    assert main([*base_argv, "trace", "probe", "--mock"]) == 0
    assert (
        main(
            [
                *base_argv,
                "judge",
                "calibrate",
                "--mock",
                "--dataset",
                str(REPO_ROOT / "data" / "judge_calibration" / "answers.jsonl"),
            ]
        )
        == 0
    )

    # 2) golden validate / convert / scaffold / export (m365-copilot-eval) + run --from-m365-copilot-eval
    assert main([*base_argv, "golden", "validate", str(smoke_path)]) == 0
    converted_yaml = tmp_path / "converted.yaml"
    assert (
        main(
            [
                *base_argv,
                "golden",
                "convert",
                str(REPO_ROOT / "data" / "golden" / "demo_questions.template.csv"),
                "--out",
                str(converted_yaml),
            ]
        )
        == 0
    )
    assert main([*base_argv, "golden", "validate", str(converted_yaml)]) == 0

    measures_csv = tmp_path / "measures.csv"
    measures_csv.write_text(
        "name,model,artifact,unit\nNet Revenue,Sales Semantic Model,Executive Revenue Scorecard,currency\n",
        encoding="utf-8",
    )
    scaffold_yaml = tmp_path / "starter.yaml"
    assert main([*base_argv, "golden", "scaffold", "--measures", str(measures_csv), "--out", str(scaffold_yaml)]) == 0
    assert scaffold_yaml.exists()

    m365_cases_json = tmp_path / "m365_cases.json"
    assert (
        main(
            [
                *base_argv,
                "golden",
                "export",
                "--format",
                "m365-copilot-eval",
                "--golden",
                str(smoke_path),
                "--out",
                str(m365_cases_json),
            ]
        )
        == 0
    )
    exported_payload = json.loads(m365_cases_json.read_text(encoding="utf-8"))
    assert exported_payload["schemaVersion"] == "2.0"
    assert len(exported_payload["items"]) == 8

    # Turn exported test cases into synthetic saved M365 eval results and score offline
    saved_m365 = tmp_path / "m365_results.json"
    saved_m365.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "id": tc["id"],
                        "prompt": tc["prompt"],
                        "response": (
                            f"According to {tc['metadata']['expected_artifact']}, "
                            f"the value is {tc['expected_response']}."
                        ),
                        "citations": [tc["metadata"]["expected_artifact"]],
                        "latencyMs": 420.0,
                    }
                    for tc in exported_payload["items"]
                ]
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *base_argv,
                "run",
                "--from-m365-copilot-eval",
                str(saved_m365),
                "--golden",
                str(smoke_path),
                "--no-publish",
                "--no-trace",
                "--run-id",
                "m365-import-run",
            ]
        )
        == 0
    )

    # 3) Run baseline vs tuned, check gate exit codes (2 vs 0) + JUnit/MD + positional report
    assert main([*base_argv, "run", "--mock", "--profile", "baseline", "--run-id", "gate-base"]) == 0
    assert main([*base_argv, "run", "--mock", "--profile", "tuned", "--run-id", "gate-tuned"]) == 0

    junit_xml = tmp_path / "junit.xml"
    gate_md = tmp_path / "gate.md"
    assert (
        main(
            [
                *base_argv,
                "gate",
                str(out_dir / "gate-base"),
                "--junit",
                str(junit_xml),
                "--summary-md",
                str(gate_md),
            ]
        )
        == 2
    )
    assert "<testsuite" in junit_xml.read_text(encoding="utf-8")
    assert "Release Gate" in gate_md.read_text(encoding="utf-8")
    assert main([*base_argv, "gate", str(out_dir / "gate-tuned")]) == 0

    rep_html = tmp_path / "diff_report.html"
    assert (
        main(
            [
                *base_argv,
                "report",
                str(out_dir / "gate-tuned"),
                "--baseline",
                str(out_dir / "gate-base"),
                "--out",
                str(rep_html),
            ]
        )
        == 0
    )
    assert rep_html.exists()

    # 4) Default 8-run demo-data produces exact 8 / 64 / 80 rows and is byte-identical across runs
    demo_env = tmp_path / "demo.env"
    demo_a = tmp_path / "evals_a.json"
    demo_b = tmp_path / "evals_b.json"
    demo_env.write_text(
        f"GOLDEN_SET={smoke_path}\nOUTPUT_DIR={tmp_path / 'demo_runs_a'}\n",
        encoding="utf-8",
    )
    assert (
        main(["--env", str(demo_env), "demo-data", "--as-of", "2026-11-01T12:00:00Z", "--app-json", str(demo_a)]) == 0
    )
    demo_env.write_text(
        f"GOLDEN_SET={smoke_path}\nOUTPUT_DIR={tmp_path / 'demo_runs_b'}\n",
        encoding="utf-8",
    )
    assert (
        main(["--env", str(demo_env), "demo-data", "--as-of", "2026-11-01T12:00:00Z", "--app-json", str(demo_b)]) == 0
    )
    assert demo_a.read_bytes() == demo_b.read_bytes()
    payload = json.loads(demo_a.read_text(encoding="utf-8"))
    assert len(payload["tables"]["EvalRun"]) == 8
    assert len(payload["tables"]["EvalQuestion"]) == 64
    assert len(payload["tables"]["EvalResult"]) == 80


def test_local_backend_cascade_extraction_and_live_target_wiring(tmp_path: Path) -> None:
    import base64
    import time

    from cfeval.cli import _instantiate_plugin_target, build_harness, main
    from cfeval.clock import SimClock
    from cfeval.config import Settings
    from cfeval.golden import load_golden
    from cfeval.mock import MockJudge
    from cfeval.scoring import LocalBackend, trace_stats
    from cfeval.targets.mcp_reference import McpReferenceTarget

    questions = load_golden(REPO_ROOT / "data" / "golden" / "contoso-smoke.yaml")
    q = next(item for item in questions if item.expected_value is not None and item.unit == "currency")
    target_val = float(q.expected_value or 0.0)
    decoy_val = round(target_val * 0.72, 2)
    ambiguous_answer = (
        "| Metric | Value |\n"
        "| --- | --- |\n"
        f"| Prior period | ${decoy_val:,.2f} |\n"
        f"| Requested total | ${target_val:,.2f} |\n"
    )
    clock = SimClock()

    # 1) Tier-2 explicit WhyJson disambiguation + deterministic WhyScore when judge is None
    base_ask = {
        "AskId": "ask-cascade-1",
        "QuestionId": q.id,
        "Attempt": 1,
        "TestUser": "eval.tester@contoso.com",
        "AskStartUtc": clock.now(),
        "Status": "ok",
        "Answer": ambiguous_answer,
        "Why": f"Computed from {q.expected_artifact}.",
        "WhyJson": json.dumps({"answer": f"${target_val:,.2f}", "artifact": q.expected_artifact}),
        "LatencyMs": 120.0,
        "WhyLatencyMs": 40.0,
    }
    artifacts = [{"kind": "citation", "provider_type": "PowerBI", "name": q.expected_artifact, "url": ""}]
    trace = {
        "status": "observed",
        "queries": [],
        "models": [q.model],
        "stats": trace_stats([], None),
        "routing_evidence": "engine+citations",
        "correlation_confidence": "high",
    }
    backend_no_judge = LocalBackend(judge=None, clock=clock)
    _, res_explicit = backend_no_judge.evaluate(
        "run-cascade", [{"q": q, "ask": base_ask, "artifacts": artifacts, "trace": trace}]
    )
    assert res_explicit[0]["ValueScore"] == 1.0
    assert res_explicit[0]["ExtractionMethod"] == "explicit"
    assert res_explicit[0]["WhyScore"] == 1.0

    # 2) Tier-3 blind LLM span extraction when WhyJson is absent
    class _BlindExtractorJudge:
        def extract_value(self, question_text: str, answer_text: str) -> dict[str, str]:
            assert str(int(target_val)) not in question_text
            return {"span": f"${target_val:,.2f}"}

    ask_no_wj = dict(base_ask, AskId="ask-cascade-2", WhyJson="")
    backend_blind = LocalBackend(judge=_BlindExtractorJudge(), clock=clock)
    _, res_llm = backend_blind.evaluate(
        "run-cascade", [{"q": q, "ask": ask_no_wj, "artifacts": artifacts, "trace": trace}]
    )
    assert res_llm[0]["ValueScore"] == 1.0
    assert res_llm[0]["ExtractionMethod"] == "llm_extract"

    # 3) Live McpReferenceTarget never leaks golden answer key or synthesizes mock answers/citations
    seen_calls: list[tuple[str, dict[str, object]]] = []

    def _live_exec(tool_name: str, tool_args: dict[str, object]) -> dict[str, object]:
        seen_calls.append((tool_name, dict(tool_args)))
        return {"answer": "No data returned by server."}

    mcp_live = McpReferenceTarget(questions=[q], mock=False, tool_executor=_live_exec, clock=clock)
    live_res = mcp_live.ask(q.question, explain_mode="off")
    assert len(seen_calls) == 1
    assert seen_calls[0][1] == {"question": q.question}
    assert live_res.answer is not None and live_res.answer.text == "No data returned by server."
    assert live_res.answer.attributions == []
    assert mcp_live.recorded_queries() == []

    # 4) fabric-data-agent live target receives Entra token_provider & transcript-import live avoids MockJudge
    tx_path = tmp_path / "transcript.jsonl"
    tx_path.write_text(
        json.dumps({"question_id": q.id, "question": q.question, "answer": f"${target_val:,.2f}"}) + "\n",
        encoding="utf-8",
    )
    env_live = tmp_path / "live.env"
    env_live.write_text(
        f"GOLDEN_SET={REPO_ROOT / 'data' / 'golden' / 'contoso-smoke.yaml'}\n"
        f"OUTPUT_DIR={tmp_path / 'out'}\n"
        "DATA_AGENT_ENDPOINT=https://api.fabric.microsoft.com/v1/workspaces/w/dataAgents/a\n",
        encoding="utf-8",
    )
    live_settings = Settings.load(env_file=env_live)
    da_target = _instantiate_plugin_target(
        "fabric-data-agent",
        settings=live_settings,
        questions=questions,
        mock=False,
        clock=clock,
        transcript_path=None,
        profile="tuned",
        seed=7,
        persona="",
        user="eval.tester@contoso.com",
        chat_client=None,
        monitoring=None,
    )
    assert callable(getattr(da_target, "token_provider", None))

    tx_harness = build_harness(
        live_settings,
        option="fabric-native",
        mock=False,
        publish=False,
        trace=False,
        target_name="transcript-import",
        transcript_path=str(tx_path),
    )
    assert not isinstance(tx_harness.local.judge, MockJudge)

    # 5) doctor --verify-tokens succeeds without KeyError on cached delegated JWT
    tid = "11111111-2222-3333-4444-555555555555"
    upn = "eval.tester@contoso.com"
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    claims = {
        "tid": tid,
        "upn": upn,
        "scp": "Sites.Read.All Files.Read.All",
        "aud": "https://graph.microsoft.com",
        "exp": int(time.time()) + 3600,
    }
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    fake_jwt = f"{hdr}.{body}.sig"
    cache_file = tmp_path / "msal_cache.json"
    cache_file.write_text(json.dumps({"AccessToken": {"tok-1": {"secret": fake_jwt}}}), encoding="utf-8")
    doc_env = tmp_path / "doctor.env"
    doc_env.write_text(
        f"TENANT_ID={tid}\nCLIENT_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        f"TEST_USER_UPN={upn}\nTOKEN_CACHE={cache_file}\n"
        f"GOLDEN_SET={REPO_ROOT / 'data' / 'golden' / 'contoso-smoke.yaml'}\n",
        encoding="utf-8",
    )
    assert main(["--env", str(doc_env), "doctor", "--verify-tokens"]) == 0
