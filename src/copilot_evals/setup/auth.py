"""Sign-in for the setup commands: the operator's own delegated identity (docs/deployment.md).

``evals deploy`` acts as the person who runs it. That account needs Contributor (or Admin) rights on
the Fabric capacity, rights to create workspaces, and ownership of the Work IQ SharePoint sites.
Two sign-in modes:

* ``device-code`` (default): the copilot-eval-setup app registration (``[apps] setup_client_id``),
  created by infra/entra/New-EvalAppRegistrations.ps1 with the delegated permissions the setup
  needs. Works from any terminal, including a Codespace or the runner VM.
* ``azure-cli``: reuse ``az login``. No app registration, but some tenants block the Azure CLI's
  first-party app for Fabric or SharePoint scopes; fall back to ``device-code`` if a call returns 401.

azure-identity is an optional extra: ``uv sync --extra setup``.
"""

import time
from typing import Literal

from copilot_evals.setup.rest import SetupError

SignIn = Literal["device-code", "azure-cli"]

_REFRESH_MARGIN_S = 300


class AzureIdentityTokens:
    """A token provider (``scope -> access token``) over azure-identity, cached per scope."""

    def __init__(self, sign_in: SignIn, *, tenant_id: str, client_id: str = "") -> None:
        try:
            from azure.identity import AzureCliCredential, DeviceCodeCredential
        except ImportError as error:
            raise SetupError("Sign-in needs azure-identity: run `uv sync --extra setup`.") from error
        if not tenant_id:
            raise SetupError("[tenant] tenant_id is empty in config/settings.toml.")
        if sign_in == "device-code":
            if not client_id:
                raise SetupError(
                    "[apps] setup_client_id is empty: create the copilot-eval-setup app registration "
                    "(infra/entra/New-EvalAppRegistrations.ps1) or use --sign-in azure-cli."
                )
            self._credential: DeviceCodeCredential | AzureCliCredential = DeviceCodeCredential(
                client_id=client_id, tenant_id=tenant_id
            )
        else:
            self._credential = AzureCliCredential(tenant_id=tenant_id)
        self._cache: dict[str, tuple[str, float]] = {}

    def __call__(self, scope: str) -> str:
        token, expires_on = self._cache.get(scope, ("", 0.0))
        if time.time() < expires_on - _REFRESH_MARGIN_S:
            return token
        access = self._credential.get_token(scope)
        self._cache[scope] = (access.token, float(access.expires_on))
        return access.token
