"""Offline unit tests for Settings.load precedence, Retry-After parsing, and HTTP retry backoff."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

from cfeval import cli
from cfeval.clock import SimClock
from cfeval.config import HttpStatusError, Settings, parse_retry_after, request_with_retry
from cfeval.fabric_rest import FabricApiError, FabricClient, onelake_delta_version, wait_for_onelake_delta


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: str = "{}",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = body
        self.content = body.encode("utf-8") if body else b""
        self.headers = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)


class _FakeSession:
    def __init__(self, steps: list[Any]) -> None:
        self._steps = list(steps)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_settings_load_precedence_and_type_coercion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TENANT_ID", "env-unprefixed-tenant")
    monkeypatch.setenv("CFEVAL_TENANT_ID", "env-prefixed-tenant")
    monkeypatch.setenv("CFEVAL_REPEATS", "2")
    monkeypatch.setenv("SEMANTIC_MODEL_WORKSPACE_ID", "env-workspace")

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "SEMANTIC_MODEL_WORKSPACE_ID=dotenv-unprefixed-ws",
                "CFEVAL_REPEATS=4",
                "REPEATS=9",
                "CFEVAL_PAUSE_SECONDS=1.5",
                "CFEVAL_JUDGE_GATES_VERDICT=true",
            ]
        ),
        encoding="utf-8",
    )

    cfg = Settings.load(env_file=dotenv, target="mcp-agent")
    # CFEVAL_* in process env wins over unprefixed TENANT_ID when .env does not set that key
    assert cfg.tenant_id == "env-prefixed-tenant"
    # .env unprefixed overrides process env unprefixed
    assert cfg.semantic_model_workspace_id == "dotenv-unprefixed-ws"
    # .env CFEVAL_REPEATS wins over .env REPEATS and process env CFEVAL_REPEATS
    assert cfg.repeats == 4
    assert cfg.pause_seconds == pytest.approx(1.5)
    assert cfg.judge_gates_verdict is True
    # Explicit override wins over everything
    assert cfg.target == "mcp-agent"


def test_parse_retry_after_delta_and_rfc7231_date() -> None:
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

    assert parse_retry_after(None, now=now) is None
    assert parse_retry_after("", now=now) is None
    assert parse_retry_after("7", now=now) == 7.0
    assert parse_retry_after("2.5", now=now) == 2.5
    assert parse_retry_after("-5", now=now) == 0.0
    assert parse_retry_after("999", now=now, max_wait=120.0) == 120.0
    assert parse_retry_after("nan", now=now) is None
    assert parse_retry_after("not-a-date", now=now) is None

    # RFC 7231 HTTP-date 45 seconds ahead of `now`
    http_date = "Fri, 01 May 2026 12:00:45 GMT"
    assert parse_retry_after(http_date, now=now) == 45.0


def test_request_with_retry_handles_429_503_and_timeout() -> None:
    clock = SimClock(datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))
    session = _FakeSession(
        [
            _FakeResponse(429, '{"error":"rate_limited"}', headers={"Retry-After": "12"}),
            _FakeResponse(503, '{"error":"unavailable"}'),
            requests.Timeout("read timed out"),
            _FakeResponse(200, '{"ok":true}'),
        ]
    )

    t0 = clock.monotonic()
    resp = request_with_retry(
        session,
        "POST",
        "http://127.0.0.1:9999/chat",
        sleep_fn=clock.sleep,
        max_retries=4,
        backoff_base=2.0,
        timeout=30.0,
    )
    elapsed = clock.monotonic() - t0
    assert resp.status_code == 200
    assert len(session.calls) == 4
    # 12s (Retry-After on attempt 0) + 4s (2.0 * 2**1 on attempt 1) + 8s (2.0 * 2**2 on attempt 2) = 24s
    assert elapsed == pytest.approx(24.0)


def test_request_with_retry_fails_fast_on_400_client_error() -> None:
    clock = SimClock()
    session = _FakeSession([_FakeResponse(400, '{"error":"bad_request"}')])

    t0 = clock.monotonic()
    with pytest.raises(HttpStatusError) as exc_info:
        request_with_retry(
            session,
            "POST",
            "http://127.0.0.1:9999/chat",
            sleep_fn=clock.sleep,
            max_retries=4,
        )
    assert exc_info.value.status_code == 400
    assert len(session.calls) == 1
    assert clock.monotonic() == t0


def test_refresh_sql_endpoint_handles_200_202_lro_and_origin_guard() -> None:
    clock = SimClock()
    ws_id = "00000000-0000-0000-0000-000000000010"
    ep_id = "00000000-0000-0000-0000-000000000020"

    # Synchronous 200 OK
    s200 = _FakeSession([_FakeResponse(200, '[{"tableName":"EvalRun","status":"Success"}]')])
    c200 = FabricClient(token_provider=lambda: "tok", session=s200, sleep_fn=clock.sleep)
    res200 = c200.refresh_sql_endpoint(ws_id, ep_id)
    assert res200 == [{"tableName": "EvalRun", "status": "Success"}]
    assert s200.calls[0][2]["headers"]["x-ms-fabric-skill"] == "sqldw-cli"

    # 202 Accepted LRO polling -> Running -> Succeeded
    op_url = "https://api.fabric.microsoft.com/v1/operations/00000000-0000-0000-0000-000000000099"
    s202 = _FakeSession(
        [
            _FakeResponse(202, "", headers={"Location": op_url, "Retry-After": "4"}),
            _FakeResponse(200, '{"status":"Running","percentComplete":50}'),
            _FakeResponse(200, '{"status":"Succeeded","percentComplete":100}'),
        ]
    )
    c202 = FabricClient(token_provider=lambda: "tok", session=s202, sleep_fn=clock.sleep)
    t0 = clock.monotonic()
    res202 = c202.refresh_sql_endpoint(ws_id, ep_id, poll_interval_s=3.0)
    assert res202["status"] == "Succeeded"
    assert len(s202.calls) == 3
    assert clock.monotonic() - t0 == pytest.approx(7.0)

    # 202 LRO failure surfaces FabricApiError
    s_fail = _FakeSession(
        [
            _FakeResponse(202, "", headers={"Location": op_url}),
            _FakeResponse(200, '{"status":"Failed","error":{"errorCode":"SyncFailed"}}'),
        ]
    )
    c_fail = FabricClient(token_provider=lambda: "tok", session=s_fail, sleep_fn=clock.sleep)
    with pytest.raises(FabricApiError, match="failed"):
        c_fail.refresh_sql_endpoint(ws_id, ep_id, poll_interval_s=1.0)

    # Cross-origin Location header is rejected before sending credentials
    s_evil = _FakeSession(
        [_FakeResponse(202, "", headers={"Location": "https://attacker.example.com/v1/operations/1"})]
    )
    c_evil = FabricClient(token_provider=lambda: "tok", session=s_evil, sleep_fn=clock.sleep)
    with pytest.raises(FabricApiError, match="escaped"):
        c_evil.refresh_sql_endpoint(ws_id, ep_id, poll_interval_s=1.0)
    assert len(s_evil.calls) == 1


def test_onelake_delta_version_ignores_last_checkpoint_and_polls() -> None:
    clock = SimClock()
    ws_id = "00000000-0000-0000-0000-000000000010"
    db_id = "00000000-0000-0000-0000-000000000030"
    listing_v15 = json.dumps(
        {
            "paths": [
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/00000000000000000009.json"},
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/00000000000000000015.json"},
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/00000000000000000015.checkpoint.parquet"},
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/_last_checkpoint"},
            ]
        }
    )
    listing_v17 = json.dumps(
        {
            "paths": [
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/00000000000000000015.json"},
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/00000000000000000017.json"},
                {"name": f"{db_id}/Tables/EvalRun/_delta_log/_last_checkpoint"},
            ]
        }
    )
    sess = _FakeSession(
        [
            _FakeResponse(404, ""),
            _FakeResponse(200, listing_v15),
            _FakeResponse(200, listing_v17),
        ]
    )
    assert onelake_delta_version(ws_id, db_id, token_provider=lambda: "tok", session=sess, sleep_fn=clock.sleep) is None
    ver = wait_for_onelake_delta(
        ws_id,
        db_id,
        min_version=16,
        wait_seconds=30.0,
        poll_seconds=5.0,
        monotonic_fn=clock.monotonic,
        sleep_fn=clock.sleep,
        token_provider=lambda: "tok",
        session=sess,
    )
    assert ver == 17


def test_cli_ergonomic_aliases_and_sync_sql_flags() -> None:
    p = cli.parser()
    ns_sync = p.parse_args(["--env-file", "custom.env", "sync-sql", "--timeout-minutes", "2"])
    assert ns_sync.env == "custom.env"
    assert ns_sync.command == "sync-sql"
    assert ns_sync.timeout_minutes == 2

    ns_cmp = p.parse_args(["compare", "runs/base", "runs/cand"])
    assert ns_cmp.baseline_dir == "runs/base"
    assert ns_cmp.candidate_dir == "runs/cand"

    ns_gate = p.parse_args(["gate", "runs/cand", "--baseline", "runs/base", "--max-regressions", "1"])
    assert ns_gate.baseline == "runs/base"
    assert ns_gate.max_regressions == 1

    ns_gr = p.parse_args(["golden-refresh", "--golden", "data/golden/contoso.yaml"])
    assert ns_gr.golden == "data/golden/contoso.yaml"
