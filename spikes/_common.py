"""Shared helpers for the Phase 0 spikes (spikes/README.md).

Spikes are short probes run by hand against a test tenant to answer one open question each. They
favour clarity over reuse: synchronous calls, raw responses saved to ``spikes/out/`` (gitignored,
because they hold tenant identifiers and user names) and a plain-text summary for the ADR.

Sign-in:

* personas use MSAL device-code sign-in with the copilot-eval-public app (``[apps] public_client_id``)
  and a file token cache per persona under ``.cache/`` (gitignored), so each persona signs in once;
* the operator (engine logs, Foundry) uses azure-identity's DefaultAzureCredential, for example
  after ``az login``.

Install the spike dependencies with ``uv sync --extra spikes``.
"""

import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import msal

from copilot_evals.config import Settings, load_settings
from copilot_evals.golden import GoldenSet, load_golden_set

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"
CACHE = ROOT / ".cache"
SNAPSHOT = ROOT / "runs" / "deploy" / "expected_snapshot.json"

GRAPH_CHAT_SCOPES = [
    "https://graph.microsoft.com/Sites.Read.All",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/People.Read.All",
    "https://graph.microsoft.com/OnlineMeetingTranscript.Read.All",
    "https://graph.microsoft.com/Chat.Read",
    "https://graph.microsoft.com/ChannelMessage.Read.All",
    "https://graph.microsoft.com/ExternalItem.Read.All",
]  # config/contracts.yaml copilot_chat_api: all are required

_NUMBER = re.compile(r"\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(million|m|bn|billion|k)?\b", re.I)
ONE_PERCENT = Decimal("0.01")
_SCALE = {"k": Decimal(1_000), "m": Decimal(1_000_000), "million": Decimal(1_000_000),
          "bn": Decimal(1_000_000_000), "billion": Decimal(1_000_000_000)}


def settings() -> Settings:
    return load_settings()


def golden() -> GoldenSet:
    return load_golden_set(ROOT / "evals" / "golden")


def persona_upn(persona: str) -> str:
    return golden().personas[persona].resolve_upn(settings().tenant.tenant_domain)


def persona_token(persona: str, scopes: list[str]) -> str:
    """A delegated access token for a persona; device-code sign-in the first time, silent afterwards."""
    config = settings()
    upn = persona_upn(persona)
    CACHE.mkdir(exist_ok=True)
    cache_file = CACHE / f"msal-{persona}.json"
    cache = msal.SerializableTokenCache()
    if cache_file.exists():
        cache.deserialize(cache_file.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        config.apps.public_client_id,
        authority=f"https://login.microsoftonline.com/{config.tenant.tenant_id}",
        token_cache=cache,
    )
    accounts = app.get_accounts(username=upn)
    result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise SystemExit(f"[{persona}] device-code flow failed: {flow.get('error_description')}")
        print(f"[{persona}] Sign in as {upn}. {flow['message']}")
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(f"[{persona}] sign-in failed: {result.get('error_description')}")
    signed_in = str(result.get("id_token_claims", {}).get("preferred_username", upn))
    if signed_in.lower() != upn.lower():
        raise SystemExit(f"[{persona}] signed in as {signed_in}, expected {upn}: delete {cache_file} and retry")
    if cache.has_state_changed:
        cache_file.write_text(cache.serialize(), encoding="utf-8")
        os.chmod(cache_file, 0o600)
    return str(result["access_token"])


def operator_credential() -> Any:
    """The operator's own Azure credential (az login, VS Code, environment or managed identity)."""
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def save(spike: str, name: str, payload: Any) -> Path:
    """Write a raw response under spikes/out/<spike>/ and return the path."""
    folder = OUT / spike
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now(tz=UTC):%Y%m%dT%H%M%SZ}-{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def expected_value(case_id: str) -> str | None:
    """The deployment snapshot's value for a case (runs/deploy/expected_snapshot.json), if any."""
    if not SNAPSHOT.exists():
        return None
    entry = json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("cases", {}).get(case_id, {})
    value = entry.get("value")
    return str(value) if value is not None else None


def numbers_in(text: str) -> list[Decimal]:
    """Every number in an answer, with K/M/B scale words applied. Rough: for spike summaries only."""
    found = []
    for digits, scale in _NUMBER.findall(text or ""):
        try:
            value = Decimal(digits.replace(",", ""))
        except InvalidOperation:
            continue
        found.append(value * _SCALE.get(scale.lower(), Decimal(1)) if scale else value)
    return found


def close_to(numbers: list[Decimal], expected: Decimal, rel: Decimal = ONE_PERCENT) -> bool:
    """True when any number is within ``rel`` of ``expected`` (rounded answers such as $12.8M pass)."""
    return any(abs(number - expected) <= abs(expected) * rel for number in numbers)


def heading(text: str) -> None:
    print(f"\n== {text} " + "=" * max(0, 70 - len(text)))
