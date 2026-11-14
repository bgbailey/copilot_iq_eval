"""Offline unit tests for JWT claim decoding, delegated vs app-only verification, and runtime checks."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest

from cfeval.auth import decode_jwt_claims_unverified, verify_token_claims
from cfeval.runtime import LoginRequired, inspect_acquired_token, require_identity


def _make_jwt(payload: dict[str, Any]) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode("utf-8")).decode("ascii").rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(b"offline-test-signature").decode("ascii").rstrip("=")
    return f"{h_b64}.{p_b64}.{sig_b64}"


def test_decode_jwt_claims_unverified_parses_and_rejects_malformed() -> None:
    tok = _make_jwt({"tid": "tenant-123", "upn": "eval.tester@contoso.com", "scp": "Files.Read.All"})
    claims = decode_jwt_claims_unverified(tok)
    assert claims["tid"] == "tenant-123"
    assert claims["upn"] == "eval.tester@contoso.com"

    with pytest.raises(ValueError, match="Invalid JWT"):
        decode_jwt_claims_unverified("not-a-jwt")


def test_verify_token_claims_delegated_vs_app_only_and_mismatches() -> None:
    future_exp = int(time.time()) + 3600

    delegated_tok = _make_jwt(
        {
            "tid": "00000000-0000-0000-0000-000000000010",
            "upn": "eval.tester@contoso.com",
            "scp": "Sites.Read.All Files.Read.All Chat.Create",
            "exp": future_exp,
        }
    )
    verified = verify_token_claims(
        delegated_tok,
        expected_tid="00000000-0000-0000-0000-000000000010",
        expected_upn="EVAL.TESTER@CONTOSO.COM",
        required_scp=["Files.Read.All", "Sites.Read.All"],
        allow_app_only=False,
    )
    assert verified["ok"] is True
    assert verified["app_only"] is False
    assert verified["upn"] == "eval.tester@contoso.com"

    # Tenant mismatch
    bad_tid = verify_token_claims(
        delegated_tok,
        expected_tid="00000000-0000-0000-0000-000000000099",
    )
    assert bad_tid["ok"] is False
    assert any("tenant mismatch" in issue for issue in bad_tid["issues"])

    # UPN mismatch
    bad_upn = verify_token_claims(
        delegated_tok,
        expected_tid="00000000-0000-0000-0000-000000000010",
        expected_upn="other.user@contoso.com",
    )
    assert bad_upn["ok"] is False
    assert any("user mismatch" in issue for issue in bad_upn["issues"])

    # Missing delegated scope
    bad_scp = verify_token_claims(
        delegated_tok,
        required_scp=["Files.Read.All", "People.Read.All"],
    )
    assert bad_scp["ok"] is False
    assert any("missing required scopes" in issue for issue in bad_scp["issues"])

    # App-only token rejected when allow_app_only=False, accepted when allow_app_only=True
    app_only_tok = _make_jwt(
        {
            "tid": "00000000-0000-0000-0000-000000000010",
            "idtyp": "app",
            "roles": ["Workspace.Read.All"],
            "exp": future_exp,
        }
    )
    rejected_app = verify_token_claims(app_only_tok, allow_app_only=False)
    assert rejected_app["ok"] is False
    assert rejected_app["app_only"] is True
    assert any("app-only" in issue for issue in rejected_app["issues"])

    allowed_app = verify_token_claims(
        app_only_tok,
        expected_tid="00000000-0000-0000-0000-000000000010",
        allow_app_only=True,
    )
    assert allowed_app["ok"] is True
    assert allowed_app["app_only"] is True


def test_runtime_inspect_acquired_token_and_require_identity() -> None:
    tenant_id = "11111111-2222-3333-4444-555555555555"
    client_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    require_identity(tenant_id, "eval.tester@contoso.com")

    valid_graph_tok = _make_jwt(
        {
            "aud": "https://graph.microsoft.com",
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "tid": tenant_id,
            "azp": client_id,
            "upn": "eval.tester@contoso.com",
            "scp": "Files.Read.All Sites.Read.All",
            "exp": int(time.time()) + 3600,
        }
    )
    claims = inspect_acquired_token(
        valid_graph_tok,
        "https://graph.microsoft.com",
        tenant_id,
        expected_upn="eval.tester@contoso.com",
        required_scopes=["https://graph.microsoft.com/Files.Read.All"],
        client_id=client_id,
        delegated=True,
    )
    assert claims["upn"] == "eval.tester@contoso.com"
    assert claims["tid"] == tenant_id

    wrong_aud_tok = _make_jwt(
        {
            "aud": "https://api.fabric.microsoft.com",
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "tid": tenant_id,
            "upn": "eval.tester@contoso.com",
            "scp": "Files.Read.All",
            "exp": int(time.time()) + 3600,
        }
    )
    with pytest.raises(LoginRequired, match="wrong audience"):
        inspect_acquired_token(
            wrong_aud_tok,
            "https://graph.microsoft.com",
            tenant_id,
            expected_upn="eval.tester@contoso.com",
            required_scopes=["https://graph.microsoft.com/Files.Read.All"],
        )

    expired_tok = _make_jwt(
        {
            "aud": "https://graph.microsoft.com",
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "tid": tenant_id,
            "upn": "eval.tester@contoso.com",
            "scp": "Files.Read.All",
            "exp": int(time.time()) - 120,
        }
    )
    with pytest.raises(LoginRequired, match="expired"):
        inspect_acquired_token(
            expired_tok,
            "https://graph.microsoft.com",
            tenant_id,
            expected_upn="eval.tester@contoso.com",
            required_scopes=["https://graph.microsoft.com/Files.Read.All"],
        )
