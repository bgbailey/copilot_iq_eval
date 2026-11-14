"""Settings from environment variables or a .env file, plus shared HTTP retry helper."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

DEFAULT_RETRY_STATUSES: tuple[int, ...] = (429, 502, 503, 504)


def _strip_dotenv_value(raw: str) -> str:
    """Parse a .env value, preserving '#' inside quotes and stripping inline comments after whitespace."""
    s = raw.strip()
    if not s:
        return ""
    if s[0] in ('"', "'"):
        quote_char = s[0]
        escaped = False
        buf: list[str] = []
        for idx in range(1, len(s)):
            ch = s[idx]
            if escaped:
                buf.append(ch)
                escaped = False
                continue
            if ch == "\\" and quote_char == '"':
                escaped = True
                continue
            if ch == quote_char:
                return "".join(buf)
            buf.append(ch)
        return "".join(buf)
    for idx, ch in enumerate(s):
        if ch == "#" and (idx == 0 or s[idx - 1].isspace()):
            return s[:idx].rstrip()
    return s


def read_dotenv(path: str | Path | None) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE, # comments). Returns a dict; doesn't touch os.environ."""
    values: dict[str, str] = {}
    if not path or not Path(path).exists():
        return values
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_val = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key:
            values[key] = _strip_dotenv_value(raw_val)
    return values


class HttpStatusError(requests.HTTPError):
    """Non-retryable or exhausted HTTP error carrying status_code and body snippet."""

    def __init__(self, status_code: int, method: str, url: str, body: str = "", response: Any = None) -> None:
        snippet = (body or "")[:500]
        super().__init__(f"HTTP {status_code} for {method.upper()} {url}: {snippet}", response=response)
        self.status_code = status_code
        self.method = method.upper()
        self.url = url
        self.body = body or ""


def parse_retry_after(
    header_value: str | None,
    *,
    now: datetime | None = None,
    max_wait: float = 60.0,
) -> float | None:
    """Parse an HTTP Retry-After header (delta-seconds or RFC 7231 HTTP-date)."""
    if header_value is None:
        return None
    raw = str(header_value).strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
        if seconds != seconds:  # NaN check
            return None
        return max(0.0, min(seconds, max_wait))
    except ValueError:
        pass
    try:
        target_dt = parsedate_to_datetime(raw)
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=timezone.utc)
        ref_now = now or datetime.now(timezone.utc)
        delta = (target_dt - ref_now).total_seconds()
        return max(0.0, min(delta, max_wait))
    except (TypeError, ValueError, OverflowError):
        return None


def request_with_retry(
    session: Any,
    method: str,
    url: str,
    *,
    timeout: float | tuple[float, float] = (10.0, 60.0),
    max_retries: int = 3,
    backoff_base: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
    retry_statuses: Sequence[int] = DEFAULT_RETRY_STATUSES,
    allow_statuses: Collection[int] = (),
    raise_for_status: bool = True,
    **kwargs: Any,
) -> Any:
    """Execute an HTTP request with bounded retries on 429/502/503/504 and transient network errors."""
    method_upper = method.upper()
    retries = max(0, int(max_retries))
    retryable = set(retry_statuses)
    allowed = set(allow_statuses)
    allow_redirects = kwargs.get("allow_redirects", True)

    for attempt in range(retries + 1):
        call_kwargs = dict(kwargs)
        headers = call_kwargs.get("headers")
        if callable(headers):
            call_kwargs["headers"] = headers()
        try:
            if hasattr(session, "request"):
                resp = session.request(method_upper, url, timeout=timeout, **call_kwargs)
            else:
                fn = getattr(session, method_upper.lower())
                resp = fn(url, timeout=timeout, **call_kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt < retries:
                wait_s = min(max(0.0, backoff_base * (2**attempt)), 60.0)
                sleep_fn(wait_s)
                continue
            raise

        status = int(getattr(resp, "status_code", 200))
        if status in allowed:
            return resp
        if 200 <= status < 300:
            return resp
        if 300 <= status < 400 and allow_redirects:
            return resp

        if status in retryable and attempt < retries:
            resp_headers = getattr(resp, "headers", None) or {}
            retry_after = parse_retry_after(resp_headers.get("Retry-After")) if status == 429 else None
            if retry_after is None:
                retry_after = parse_retry_after(resp_headers.get("Retry-After"))
            wait_s = retry_after if retry_after is not None else min(max(0.0, backoff_base * (2**attempt)), 60.0)
            sleep_fn(wait_s)
            continue

        if raise_for_status:
            text = getattr(resp, "text", "") or ""
            raise HttpStatusError(status, method_upper, url, text, response=resp)
        return resp

    raise HttpStatusError(0, method_upper, url, "retries exhausted")


@dataclass
class Settings:
    # Explicit operator identity/profile; never infer these from an ambient login
    tenant_id: str = ""
    tenant_label: str = ""  # optional tenant display name and domain for browser context
    auth_run_label: str = ""  # optional task/run prefix; login adds a unique suffix
    azure_subscription_id: str = ""
    azure_config_dir: str = ""
    operator_upn: str = ""
    operator_object_id: str = ""

    # Copilot Chat (delegated sign-in as the test user)
    client_id: str = ""
    test_user_upn: str = ""
    test_user_object_id: str = ""
    time_zone: str = "America/New_York"
    token_cache: str = ".cache/msal_token_cache.json"  # file path, or "keyvault"
    key_vault_url: str = ""
    token_cache_secret: str = "cfeval-msal-token-cache"

    # Run behaviour & pluggable targets
    target: str = "copilot-chat"
    gate_profile: str = "auto"
    golden_set: str = "data/golden/golden_questions.csv"
    explain_mode: str = "followup"  # followup | inline | off
    repeats: int = 1
    pause_seconds: float = 20.0
    output_dir: str = "runs"

    # HTTP resilience & observability
    http_timeout_s: float = 60.0
    http_max_retries: int = 3
    otel_endpoint: str = ""

    # Additional target endpoints
    foundry_resource_endpoint: str = ""
    data_agent_endpoint: str = ""
    mcp_server_command: str = ""

    # Telemetry Eventhouse (KQL database)
    eventhouse_query_uri: str = ""
    eventhouse_ingest_uri: str = ""
    eventhouse_database: str = "copilot_eval"
    eventhouse_workspace_id: str = ""
    eventhouse_database_id: str = ""  # Fabric KQL database item GUID, not its display/engine name

    # Existing app lakehouse and its SQL analytics endpoint (setup/verification entrypoints)
    lakehouse_workspace_id: str = ""
    lakehouse_id: str = ""
    lakehouse_shortcut_path: str = "Tables"
    sql_endpoint_id: str = ""
    sql_endpoint_server: str = ""
    sql_endpoint_database: str = ""
    sql_schema: str = "dbo"
    sql_odbc_driver: str = "ODBC Driver 18 for SQL Server"
    demo_app_url: str = ""

    # DAX capture: workspace monitoring Eventhouse
    monitoring_query_uri: str = ""
    monitoring_database: str = ""
    monitoring_sources: str = ""  # optional JSON list of {query_uri, database}
    trace_wait_seconds: float = 300.0
    trace_poll_seconds: float = 20.0
    trace_settle_seconds: float = 40.0
    trace_user: str = ""  # defaults to test_user_upn
    # Workspace that holds the semantic models: used for the DAX watermark query and golden refresh
    semantic_model_workspace_id: str = ""

    # Option 1: Foundry model as judge
    judge_endpoint: str = ""  # https://<resource>.openai.azure.com or https://<resource>.services.ai.azure.com
    judge_deployment: str = "gpt-5-mini"
    judge_api_key: str = ""
    judge_api_key_secret: str = ""  # Key Vault secret name (used in Fabric notebooks)
    judge_gates_verdict: bool = False  # True: a judge 'incorrect' also fails the ask

    # Option 2: Foundry Evaluations
    foundry_project_endpoint: str = ""  # https://<account>.services.ai.azure.com/api/projects/<project>
    foundry_eval_deployment: str = "gpt-5-mini"
    # Fabric notebooks can't use the Azure CLI: give Foundry a service principal whose secret is in Key Vault
    foundry_sp_client_id: str = ""
    foundry_sp_secret_name: str = ""
    foundry_builtin_evaluators: bool = True  # add builtin.coherence and builtin.similarity

    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, env_file: str | Path | None = ".env", **overrides: Any) -> Settings:
        """Settings from environment variables, then the .env file (the file wins), then overrides.

        Prefixed CFEVAL_<NAME> keys take precedence over ambient unprefixed <NAME> keys within each source.
        """
        dotenv = read_dotenv(env_file)
        environ = dict(os.environ)
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name == "extra":
                continue
            upper = f.name.upper()
            prefixed = "CFEVAL_" + upper
            raw: str | None = None
            for candidate in (
                dotenv.get(prefixed),
                dotenv.get(upper),
                environ.get(prefixed),
                environ.get(upper),
            ):
                if candidate is not None and candidate != "":
                    raw = candidate
                    break
            if raw is None:
                continue
            ftype = str(f.type)
            if f.type is bool or ftype == "bool":
                values[f.name] = raw.strip().lower() in ("1", "true", "yes", "on")
            elif f.type is int or ftype == "int":
                values[f.name] = int(raw)
            elif f.type is float or ftype == "float":
                values[f.name] = float(raw)
            else:
                values[f.name] = raw
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    @property
    def effective_trace_user(self) -> str:
        return self.trace_user or self.test_user_upn

    @property
    def telemetry_enabled(self) -> bool:
        return bool(self.eventhouse_query_uri and self.eventhouse_database)

    @property
    def trace_enabled(self) -> bool:
        return bool(self.monitoring_sources.strip() or (self.monitoring_query_uri and self.monitoring_database))

    @property
    def judge_enabled(self) -> bool:
        return bool(self.judge_endpoint and self.judge_deployment)

    @property
    def foundry_enabled(self) -> bool:
        endpoint = self.foundry_project_endpoint or self.foundry_resource_endpoint
        return bool(endpoint and self.foundry_eval_deployment)

    def public(self) -> dict[str, Any]:
        """Run settings without keys, auth identity/profile details or cache locators."""
        hidden = {
            "judge_api_key",
            "extra",
            "tenant_id",
            "tenant_label",
            "auth_run_label",
            "client_id",
            "azure_subscription_id",
            "azure_config_dir",
            "operator_upn",
            "operator_object_id",
            "test_user_upn",
            "test_user_object_id",
            "token_cache",
            "token_cache_secret",
            "key_vault_url",
            "judge_api_key_secret",
            "foundry_sp_client_id",
            "foundry_sp_secret_name",
            "mcp_server_command",
        }
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in hidden}
