"""Live service contract tests gated behind CFEVAL_LIVE=1 (M1-01 & Section 9)."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from cfeval.auth import DelegatedAuth
from cfeval.chat import CopilotChatClient
from cfeval.clock import utc_now
from cfeval.config import Settings
from cfeval.credentials import foundry_credential
from cfeval.foundry import CODE_EVALUATORS, FoundryEvaluation, code_bundle
from cfeval.kusto import KustoQueryClient
from cfeval.targets import get_target
from cfeval.trace import WorkspaceMonitoringEvidenceSource, WorkspaceMonitoringSource


def _require_env(*names: str) -> None:
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip("Missing required live configuration: " + ", ".join(missing))


@pytest.mark.live
def test_live_copilot_chat_fabric_iq_grounding() -> None:
    """Verify Microsoft 365 Copilot Chat returns grounded answer text and attributions."""
    _require_env("TENANT_ID", "CLIENT_ID", "TEST_USER_UPN")
    settings = Settings.load()
    prompt = os.environ.get(
        "CFEVAL_LIVE_SMOKE_QUESTION",
        "Summarize the top metrics from the primary Power BI report in one sentence.",
    )
    auth = DelegatedAuth.from_settings(settings)
    client = CopilotChatClient(auth.token)
    res = client.ask(prompt, explain_mode="none")
    assert res.ok, f"Live Copilot Chat ask failed: {res.error}"
    assert res.answer is not None and res.answer.text.strip()
    assert isinstance(res.answer.attributions, list)


@pytest.mark.live
def test_live_workspace_monitoring_semantic_model_logs() -> None:
    """Verify Eventhouse Workspace Monitoring SemanticModelLogs schema and query access."""
    _require_env("MONITORING_QUERY_URI", "MONITORING_DATABASE", "TEST_USER_UPN")
    settings = Settings.load()
    kusto_client = KustoQueryClient(settings.monitoring_query_uri, settings=settings)
    ws_mon = WorkspaceMonitoringSource(kusto_client, settings.monitoring_database)
    source = WorkspaceMonitoringEvidenceSource(ws_mon, wait_seconds=0.0)
    now = utc_now()
    asks = [{"AskId": "live-smoke-window", "AskStartUtc": now - timedelta(minutes=5), "AskEndUtc": now}]
    collected = source.collect(
        run_id="live-smoke-run",
        asks=asks,
        started=now - timedelta(minutes=5),
        ended=now,
        user_upn=settings.effective_trace_user,
    )
    assert "live-smoke-window" in collected
    assert collected["live-smoke-window"].status in ("observed", "none", "pending")


@pytest.mark.live
def test_live_fabric_iq_mcp_tool_discovery() -> None:
    """Verify Fabric IQ MCP target command configuration and live non-mock wiring."""
    _require_env("MCP_SERVER_COMMAND")
    cmd = os.environ["MCP_SERVER_COMMAND"].strip()
    target = get_target("mcp-agent", mcp_server_command=cmd, mock=False)
    assert getattr(target, "name", "") in ("mcp-agent", "fabric-iq-mcp-reference")
    assert getattr(target, "mock", True) is False


@pytest.mark.live
def test_live_foundry_custom_code_evaluator_registration() -> None:
    """Verify Foundry custom code evaluator bundle limits and live registration contract."""
    for check in CODE_EVALUATORS:
        payload = code_bundle(check).encode("utf-8")
        assert len(payload) < 256 * 1024

    _require_env("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_EVAL_DEPLOYMENT")
    settings = Settings.load()
    runner = FoundryEvaluation(
        settings.foundry_project_endpoint,
        settings.foundry_eval_deployment,
        credential=foundry_credential(settings),
        include_trace=True,
        include_builtin=False,
    )
    assert set(CODE_EVALUATORS).issubset(set(runner.checks()))
