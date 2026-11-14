"""Offline unit tests for Settings.load precedence, Retry-After parsing, and HTTP retry backoff."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

from cfeval.clock import SimClock
from cfeval.config import HttpStatusError, Settings, parse_retry_after, request_with_retry


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: str = "{}",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = body
        self.headers = headers or {}


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
