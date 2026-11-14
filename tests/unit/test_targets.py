"""Offline unit tests for pluggable targets, target registry, and EvalHarness integration."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from cfeval.artifacts import extract_artifacts
from cfeval.chat import AskResult, ChatTurn
from cfeval.clock import SimClock
from cfeval.golden import GoldenQuestion, load_golden
from cfeval.mock import MockCopilotChat, MockWorld
from cfeval.pipeline import EvalHarness
from cfeval.scoring import LocalBackend
from cfeval.targets import (
    CopilotChatTarget,
    FabricDataAgentTarget,
    McpReferenceTarget,
    TranscriptImportTarget,
    UnknownTargetError,
    get_target,
    list_targets,
    register_target,
)
from cfeval.trace import collect_traces

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TRANSCRIPT = REPO_ROOT / "samples" / "contoso" / "transcript_sample.jsonl"
CONTOSO_GOLDEN = REPO_ROOT / "data" / "golden" / "contoso.yaml"


def test_list_targets_and_registry_lookup() -> None:
    listed = list_targets()
    names = {item["name"] for item in listed}
    assert {"copilot-chat", "transcript-import", "mcp-agent", "fabric-data-agent"} <= names

    da_meta = next(item for item in listed if item["name"] == "fabric-data-agent")
    assert da_meta["experimental"] is True

    # Aliases resolve cleanly
    t_imp = get_target("import", records=[])
    assert isinstance(t_imp, TranscriptImportTarget)
    t_mcp = get_target("fabric-iq-mcp-reference", mock=True)
    assert isinstance(t_mcp, McpReferenceTarget)

    # Custom registration
    class _CustomTarget:
        name = "custom-test-target"
        surface = "custom"
        supports_engine_trace = False
        experimental = False

        def __init__(self, greeting: str = "hi") -> None:
            self.greeting = greeting

    register_target("custom-test-target", _CustomTarget)
    inst = get_target("custom-test-target", greeting="hello")
    assert inst.greeting == "hello"
    assert any(t["name"] == "custom-test-target" for t in list_targets())

    with pytest.raises(UnknownTargetError):
        get_target("non-existent-target-xyz")


def test_copilot_chat_target_persona_prefix_and_mock_compatibility() -> None:
    clock = SimClock()
    captured_prompts: list[str] = []

    class _SpyChatClient:
        def ask(self, prompt: str, explain_mode: str = "followup") -> AskResult:
            captured_prompts.append(prompt)
            now = clock.now()
            turn = ChatTurn(text="$12.84M", attributions=[], started=now, ended=now, latency_ms=10.0)
            return AskResult(
                question=prompt,
                conversation_id="c-1",
                answer=turn,
                http_status=200,
                started=now,
                ended=now,
            )

    live_target = CopilotChatTarget(_SpyChatClient(), persona="executive")
    res = live_target.ask("What was gross revenue in FY2025?")
    assert res.ok is True
    assert captured_prompts == ["Context: Respond for persona 'executive'.\n\nWhat was gross revenue in FY2025?"]

    # MockCopilotChat lookup remains compatible even when persona is configured
    q = GoldenQuestion(
        id="Q01",
        question="What was gross revenue in FY2025?",
        expected_artifact="Sales Analytics",
        expected_value=12840000.0,
        unit="currency",
        persona="executive",
    )
    world = MockWorld(clock, [q])
    mock_target = CopilotChatTarget(MockCopilotChat(world), persona="executive")
    mock_res = mock_target.ask(q)
    assert mock_res.ok is True
    assert mock_res.answer is not None
    assert "12.8" in mock_res.answer.text
    assert mock_target.last_prompt.startswith("Context: Respond for persona 'executive'.\n\n")


def test_transcript_import_target_jsonl_csv_md_and_missing_404(tmp_path: Path) -> None:
    clock = SimClock()
    questions = load_golden(CONTOSO_GOLDEN)
    target = TranscriptImportTarget(SAMPLE_TRANSCRIPT, questions=questions, clock=clock)
    assert target.name == "transcript-import"
    assert target.supports_engine_trace is False

    res_q1 = target.ask(questions[0])
    assert res_q1.ok is True
    assert res_q1.answer is not None
    assert "12.84M" in res_q1.answer.text
    arts = extract_artifacts(res_q1.answer.attributions, res_q1.answer.text)
    assert any(a["name"] == "Sales Analytics" and a["kind"] == "powerbi_report" for a in arts)
    assert len(target.recorded_queries()) == 0

    # Missing question returns AskResult with 404 and explicit message
    missing = target.ask("What is the airspeed velocity of an unladen swallow?")
    assert missing.ok is False
    assert missing.http_status == 404
    assert missing.error == "Question not found in transcript"

    # CSV format (with DAX recorded into in-memory monitoring)
    csv_path = tmp_path / "captured.csv"
    csv_path.write_text(
        "id,question,answer,citations,dax\n"
        'C01,"Total orders?","Total orders were 10,420.","Sales Analytics","EVALUATE {10420}"\n',
        encoding="utf-8",
    )
    csv_target = TranscriptImportTarget(csv_path, clock=clock)
    csv_res = csv_target.ask("Total orders?")
    assert csv_res.ok is True
    assert csv_res.answer is not None
    csv_arts = extract_artifacts(csv_res.answer.attributions, csv_res.answer.text)
    assert any(a["name"] == "Sales Analytics" for a in csv_arts)
    assert len(csv_target.recorded_queries()) == 1
    assert csv_target.recorded_queries()[0].dax == "EVALUATE {10420}"

    # Markdown table format
    md_path = tmp_path / "captured.md"
    md_path.write_text(
        "# Transcript\n\n"
        "| id | question | answer | citations |\n"
        "| --- | --- | --- | --- |\n"
        "| M01 | Net margin? | Net margin was 18.4%. | Finance Margin |\n",
        encoding="utf-8",
    )
    md_target = TranscriptImportTarget(md_path, clock=clock)
    md_res = md_target.ask("Net margin?")
    assert md_res.ok is True
    assert md_res.answer is not None
    assert "18.4%" in md_res.answer.text


def test_mcp_reference_target_mock_executor_and_harness_tool_call_evidence(tmp_path: Path) -> None:
    clock = SimClock()
    q = GoldenQuestion(
        id="Q01",
        question="What was gross revenue in FY2025 in the Sales Analytics report?",
        category="named-source",
        expected_artifact="Sales Analytics",
        expected_model="Sales Analytics",
        expected_value=12840000.0,
        unit="currency",
        reference_dax='EVALUATE ROW("Gross Revenue", 12840000)',
    )
    target = McpReferenceTarget(questions=[q], mock=True, clock=clock, test_user="eval.tester@contoso.com")
    assert target.name == "mcp-agent"
    assert target.surface == "mcp-agent"
    assert target.supports_engine_trace is True
    assert target.monitoring.watermark_seen("any-marker") is True
    assert target.monitoring.latest_timestamp() >= clock.now() + timedelta(seconds=60)

    harness = EvalHarness(
        run_id="run-mcp-01",
        run_name="mcp-offline-test",
        questions=[q],
        target=target,
        monitoring=target.monitoring,
        local_backend=LocalBackend(),
        output_dir=tmp_path,
        clock=clock,
        pause_seconds=0.0,
        trace_wait_seconds=10.0,
        trace_poll_seconds=1.0,
        trace_settle_seconds=2.0,
        test_user="eval.tester@contoso.com",
        log=lambda _m: None,
    )
    outcome = harness.run()
    assert outcome.metrics["pass"] == 1
    assert outcome.results[0]["RoutingEvidence"] == "tool_call"
    iq_rows = harness.jsonl.read("FabricIqQuery")
    assert len(iq_rows) == 1
    assert iq_rows[0]["ApplicationName"] == "MCP-PowerBI"

    asks = harness.jsonl.read("EvalAsk")
    ev = collect_traces(
        target.monitoring,
        run_id="run-mcp-01",
        asks=asks,
        user_upn="eval.tester@contoso.com",
        clock=clock,
        log=lambda _m: None,
    )
    assert ev[asks[0]["AskId"]].routing_evidence == "tool_call"


def test_mcp_reference_target_stdio_jsonrpc_subprocess() -> None:
    server_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('id') == 1:\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'capabilities': {}}}))\n"
        "        sys.stdout.flush()\n"
        "    elif msg.get('id') == 2:\n"
        "        res = {'answer': 'Gross revenue was $12,840,000.', 'value': 12840000, 'model': 'Sales Analytics'}\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': 2, 'result': res}))\n"
        "        sys.stdout.flush()\n"
        "        break\n"
    )
    target = McpReferenceTarget(
        mcp_server_command=[sys.executable, "-c", server_script],
        mock=False,
        test_user="eval.tester@contoso.com",
    )
    res = target.ask("What was gross revenue in FY2025?", explain_mode="off")
    assert res.ok is True
    assert res.answer is not None
    assert "$12,840,000" in res.answer.text
    assert len(target.recorded_queries()) == 1
    assert target.recorded_queries()[0].operation_id == "mcp-tool-call"


class _FakeDataAgentResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeDataAgentSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self._polls = 0

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeDataAgentResponse:
        self.requests.append((method, url, kwargs))
        if method == "POST" and url.endswith("/threads"):
            return _FakeDataAgentResponse({"id": "thread-101"})
        if method == "POST" and url.endswith("/threads/thread-101/messages"):
            return _FakeDataAgentResponse({"id": "msg-user-1"})
        if method == "POST" and url.endswith("/threads/thread-101/runs"):
            return _FakeDataAgentResponse({"id": "run-202", "status": "in_progress"})
        if method == "GET" and url.endswith("/threads/thread-101/runs/run-202"):
            self._polls += 1
            return _FakeDataAgentResponse(
                {
                    "id": "run-202",
                    "status": "completed",
                    "model": "Sales Analytics",
                    "dax": 'EVALUATE ROW("Gross Revenue", 12840000)',
                }
            )
        if method == "GET" and url.endswith("/threads/thread-101/messages"):
            return _FakeDataAgentResponse(
                {
                    "data": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": {
                                        "value": "Gross revenue in FY2025 was $12,840,000.",
                                        "annotations": [
                                            {
                                                "title": "Sales Analytics",
                                                "url": "https://app.powerbi.com/groups/ws/datasets/ds-1",
                                            }
                                        ],
                                    },
                                }
                            ],
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected call: {method} {url}")


def test_fabric_data_agent_target_mock_and_rest_lifecycle() -> None:
    clock = SimClock()
    q = GoldenQuestion(
        id="Q01",
        question="What was gross revenue in FY2025?",
        expected_artifact="Sales Analytics",
        expected_model="Sales Analytics",
        expected_value=12840000.0,
        unit="currency",
    )
    mock_da = FabricDataAgentTarget(questions=[q], mock=True, clock=clock)
    assert mock_da.experimental is True
    m_res = mock_da.ask(q)
    assert m_res.ok is True
    assert len(mock_da.recorded_queries()) == 1

    fake_sess = _FakeDataAgentSession()
    live_da = FabricDataAgentTarget(
        endpoint="http://127.0.0.1:9999/dataagent",
        token_provider=lambda: "offline-token",
        session=fake_sess,
        clock=clock,
        poll_seconds=0.5,
    )
    l_res = live_da.ask("What was gross revenue in FY2025?")
    assert l_res.ok is True
    assert l_res.answer is not None
    assert "$12,840,000" in l_res.answer.text
    assert len(live_da.recorded_queries()) == 1
    assert live_da.recorded_queries()[0].item_name == "Sales Analytics"
    assert any(
        hdrs.get("headers", {}).get("Authorization") == "Bearer offline-token" for (_m, _u, hdrs) in fake_sess.requests
    )
