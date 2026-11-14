"""Explicitly bound SDK/CLI token acquisition; never starts interactive sign-in."""

import base64
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


class LoginRequired(RuntimeError):
    """An explicit, labelled sign-in is needed; silent callers must stop."""


def _uuid(value, name):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("%s must be an explicit tenant-specific UUID" % name) from None


def require_identity(tenant_id, upn, object_id=""):
    _uuid(tenant_id, "TENANT_ID")
    if not isinstance(upn, str) or not upn.strip() or "@" not in upn or upn != upn.strip():
        raise ValueError("An exact expected user UPN is required before authentication")
    if object_id:
        _uuid(object_id, "Expected user object ID")


def require_operator_settings(settings, cli=False):
    if settings is None:
        raise ValueError("Pass explicit Settings with TENANT_ID and OPERATOR_UPN; ambient identity is disabled")
    require_identity(settings.tenant_id, settings.operator_upn, settings.operator_object_id)
    if cli:
        _uuid(settings.azure_subscription_id, "AZURE_SUBSCRIPTION_ID")
        if not settings.azure_config_dir or not settings.azure_config_dir.strip():
            raise ValueError("AZURE_CONFIG_DIR must identify a dedicated, already signed-in Azure CLI profile")


def resource_uri(resource):
    resource = {
        "pbi": "https://analysis.windows.net/powerbi/api",
        "keyvault": "https://vault.azure.net",
        "storage": "https://storage.azure.com",
        "kusto": "https://kusto.kusto.windows.net",
    }.get(resource, resource)
    if isinstance(resource, str) and resource.endswith("/.default"):
        resource = resource[: -len("/.default")]
    parsed = urlsplit(resource)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("An explicit HTTPS resource audience is required")
    return resource.rstrip("/")


def resource_for_scopes(scopes):
    resources = {resource_uri(scope.rsplit("/", 1)[0]) for scope in scopes if "/" in scope}
    if not scopes or any("/" not in scope for scope in scopes) or len(resources) != 1:
        raise ValueError("Request scopes for exactly one explicit HTTPS resource")
    return resources.pop()


def inspect_acquired_token(
    token, resource, tenant_id, expected_upn="", expected_object_id="", required_scopes=(), client_id="", delegated=True
):
    """Inspect a trusted MSAL/SDK/CLI result, NOT an arbitrary bearer token.

    Decoding does not verify a JWT signature. The acquisition library/authority
    and ultimately the resource server provide that trust. Opaque tokens fail closed.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        if not isinstance(claims, dict):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise LoginRequired("Acquired token is not inspectable; cannot bind its identity safely") from None

    def reject(reason):
        raise LoginRequired("Acquired token %s; use an explicit labelled login for the configured identity" % reason)

    tenant = _uuid(tenant_id, "TENANT_ID")
    if str(claims.get("tid", "")).lower() != tenant:
        reject("has the wrong tenant")
    issuer = str(claims.get("iss", "")).lower().rstrip("/")
    if issuer not in ("https://sts.windows.net/" + tenant, "https://login.microsoftonline.com/" + tenant + "/v2.0"):
        reject("has an unexpected issuer")
    audience = resource_uri(resource).lower()
    aliases = {
        "https://graph.microsoft.com": {"00000003-0000-0000-c000-000000000000"},
        "https://analysis.windows.net/powerbi/api": {"00000009-0000-0000-c000-000000000000"},
        "https://management.azure.com": {"https://management.core.windows.net"},
    }
    if str(claims.get("aud", "")).lower().rstrip("/") not in {audience} | aliases.get(audience, set()):
        reject("has the wrong audience")
    expiry, not_before = claims.get("exp"), claims.get("nbf", 0)
    if (
        not isinstance(expiry, (int, float))
        or isinstance(expiry, bool)
        or not math.isfinite(expiry)
        or expiry <= time.time() + 30
    ):
        reject("is expired or too close to expiry")
    if (
        not isinstance(not_before, (int, float))
        or isinstance(not_before, bool)
        or not math.isfinite(not_before)
        or not_before > time.time() + 60
    ):
        reject("is not yet valid")
    if client_id and str(claims.get("azp") or claims.get("appid", "")).lower() != client_id.lower():
        reject("belongs to the wrong application")
    if delegated:
        require_identity(tenant_id, expected_upn, expected_object_id)
        principal = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name") or ""
        if not isinstance(principal, str) or principal.casefold() != expected_upn.casefold():
            reject("belongs to the wrong user")
        if expected_object_id and str(claims.get("oid", "")).lower() != expected_object_id.lower():
            reject("has the wrong user object ID")
        scopes = claims.get("scp", "")
        required = {scope.rsplit("/", 1)[-1] for scope in required_scopes if not scope.endswith("/.default")}
        if (
            claims.get("idtyp") == "app"
            or not isinstance(scopes, str)
            or not scopes.strip()
            or not required <= set(scopes.split())
        ):
            reject("lacks the required delegated scopes")
    elif not client_id:
        raise ValueError("Application token inspection requires an explicit client ID")
    return claims


def in_fabric_notebook():
    """True when running inside a Microsoft Fabric notebook."""
    try:
        import notebookutils  # noqa: F401  (available only in Fabric)

        return True
    except ImportError:
        return False


def fabric_token(audience, settings=None):
    """Use a notebook token only after checking the configured operator identity."""
    require_operator_settings(settings)
    resource = resource_uri(audience)
    import notebookutils  # type: ignore

    keys = {
        "https://analysis.windows.net/powerbi/api": "pbi",
        "https://api.fabric.microsoft.com": "pbi",
        "https://vault.azure.net": "keyvault",
        "https://storage.azure.com": "storage",
        "https://kusto.kusto.windows.net": "kusto",
    }
    if resource not in keys:
        raise ValueError("This resource needs an explicit credential; NotebookUtils has no supported audience key")
    token = notebookutils.credentials.getToken(keys[resource])
    expected_audience = "https://analysis.windows.net/powerbi/api" if keys[resource] == "pbi" else resource
    inspect_acquired_token(
        token, expected_audience, settings.tenant_id, settings.operator_upn, settings.operator_object_id
    )
    return token


def fabric_secret(vault_url, name, settings=None):
    fabric_token("keyvault", settings=settings)
    import notebookutils  # type: ignore

    return notebookutils.credentials.getSecret(vault_url, name)


def _az_json(arguments, settings):
    env = dict(
        os.environ,
        AZURE_CONFIG_DIR=str(Path(settings.azure_config_dir).expanduser().resolve()),
        AZURE_CORE_COLLECT_TELEMETRY="no",
        AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no",
    )
    try:
        out = subprocess.run(
            [shutil.which("az") or "az", *arguments, "--output", "json", "--only-show-errors"],
            env=env,
            stdin=subprocess.DEVNULL,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        data = json.loads(out)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except subprocess.CalledProcessError as exc:
        codes = sorted(set(re.findall(r"\bAADSTS[0-9]+\b", exc.stderr or "")))
        raise LoginRequired(
            "Azure CLI request failed (exit %s%s); no automatic sign-in or account switch was "
            "attempted" % (exc.returncode, ", " + ", ".join(codes) if codes else "")
        ) from None
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "Azure CLI could not run (%s); check the CLI installation and profile" % type(exc).__name__
        ) from None
    except ValueError:
        raise LoginRequired(
            "The dedicated Azure CLI profile is unavailable or needs an explicit labelled login; "
            "no automatic sign-in or account switch was attempted"
        ) from None


def azure_cli_token(resource, settings=None):
    """Use only the configured CLI profile/subscription and verify the actual token."""
    require_operator_settings(settings, cli=True)
    resource = resource_uri(resource)
    account = _az_json(["account", "show", "--subscription", settings.azure_subscription_id], settings)
    user = account.get("user") or {}
    if (
        str(account.get("tenantId", "")).lower() != settings.tenant_id.lower()
        or str(account.get("id", "")).lower() != settings.azure_subscription_id.lower()
        or user.get("type", "").lower() != "user"
        or user.get("name", "").casefold() != settings.operator_upn.casefold()
    ):
        raise LoginRequired(
            "Azure CLI profile does not match TENANT_ID, AZURE_SUBSCRIPTION_ID and OPERATOR_UPN; "
            "use a separately labelled login, not an ambient account switch"
        )
    result = _az_json(
        ["account", "get-access-token", "--resource", resource, "--subscription", settings.azure_subscription_id],
        settings,
    )
    token = result.get("accessToken", "")
    inspect_acquired_token(token, resource, settings.tenant_id, settings.operator_upn, settings.operator_object_id)
    return token


def token_for(resource, settings=None):
    """Return an identity-checked token; settings are never inferred from ambient state."""
    if in_fabric_notebook():
        return fabric_token(resource, settings=settings)
    return azure_cli_token(resource, settings=settings)


def host_name():
    if in_fabric_notebook():
        return "fabric-notebook"
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github-actions"
    return "local"
