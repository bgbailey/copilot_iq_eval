"""Azure credentials for Microsoft Foundry (judge model and Foundry Evaluations)."""
from . import runtime


class _BoundCredential:
    def __init__(self, settings, application_credential=None):
        self.settings = settings
        self.application_credential = application_credential

    def get_token(self, *scopes, **kwargs):
        if kwargs.get("tenant_id") and kwargs["tenant_id"].lower() != self.settings.tenant_id.lower():
            raise ValueError("Cross-tenant credential requests are disabled")
        if kwargs.get("claims"):
            raise runtime.LoginRequired("A claims challenge requires an explicit labelled sign-in; no repair was started")
        resource = runtime.resource_for_scopes(scopes)
        if self.application_credential is None:
            token = runtime.azure_cli_token(resource, settings=self.settings)
            claims = runtime.inspect_acquired_token(
                token, resource, self.settings.tenant_id, self.settings.operator_upn, self.settings.operator_object_id)
        else:
            token = self.application_credential.get_token(*scopes, **kwargs).token
            claims = runtime.inspect_acquired_token(
                token, resource, self.settings.tenant_id, client_id=self.settings.foundry_sp_client_id, delegated=False)
        from azure.core.credentials import AccessToken

        return AccessToken(token, int(claims["exp"]))

    def close(self):
        if self.application_credential is not None:
            self.application_credential.close()


def foundry_credential(settings):
    """An explicit CLI operator locally; an explicit Key Vault-backed application in notebooks."""
    if runtime.in_fabric_notebook():
        runtime.require_operator_settings(settings)
        if not (settings.foundry_sp_client_id and settings.foundry_sp_secret_name and settings.key_vault_url):
            raise ValueError("In a Fabric notebook set FOUNDRY_SP_CLIENT_ID, FOUNDRY_SP_SECRET_NAME and "
                             "KEY_VAULT_URL (or use an API key for the judge model).")
        runtime._uuid(settings.foundry_sp_client_id, "FOUNDRY_SP_CLIENT_ID")
        from azure.identity import ClientSecretCredential
        secret = runtime.fabric_secret(settings.key_vault_url, settings.foundry_sp_secret_name, settings=settings)
        return _BoundCredential(settings, ClientSecretCredential(
            settings.tenant_id, settings.foundry_sp_client_id, secret))
    runtime.require_operator_settings(settings, cli=True)
    return _BoundCredential(settings)


def judge_api_key(settings):
    if settings.judge_api_key:
        return settings.judge_api_key
    if settings.judge_api_key_secret and settings.key_vault_url and runtime.in_fabric_notebook():
        return runtime.fabric_secret(settings.key_vault_url, settings.judge_api_key_secret, settings=settings)
    return ""
