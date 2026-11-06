"""Delegated sign-in for the test user (device code) with a persisted token cache.

The Microsoft 365 Copilot Chat API supports delegated permissions only, so the
harness signs in as a dedicated, Copilot-licensed test user. The MSAL token
cache can live in a local file or in Azure Key Vault (for scheduled Fabric
notebook runs). Refresh tokens keep unattended runs signed in.
"""
import html
import os
from pathlib import Path
from uuid import uuid4

import requests

from . import runtime

GRAPH_COPILOT_CHAT_SCOPES = [
    "https://graph.microsoft.com/" + s
    for s in ("Sites.Read.All", "Mail.Read", "People.Read.All", "OnlineMeetingTranscript.Read.All",
              "Chat.Read", "ChannelMessage.Read.All", "ExternalItem.Read.All")
]
POWERBI_DATASET_SCOPES = ["https://analysis.windows.net/powerbi/api/Dataset.Read.All"]


def _protect_private_file(path):
    if os.name != "nt":
        path.chmod(0o600)
        return
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    set_security = advapi.SetFileSecurityW
    set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_security.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    # Protected DACL with only Owner Rights; no inherited or other explicit grants.
    if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not set_security(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def _atomic_private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = path.with_name(".%s.%s.pending" % (path.name, uuid4().hex))
    try:
        with os.fdopen(os.open(staging, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as out:
            _protect_private_file(staging)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


class FileCacheStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if self.path.is_symlink():
            raise ValueError("TOKEN_CACHE must be a regular, owner-controlled file")
        if not self.path.exists():
            return None
        _protect_private_file(self.path)
        return self.path.read_text(encoding="utf-8")

    def save(self, data):
        _atomic_private_write(self.path, data)


class KeyVaultCacheStore:
    """Token cache stored as a Key Vault secret (REST API, no extra packages)."""

    API = "7.4"

    def __init__(self, vault_url, secret_name, settings=None):
        self.vault_url = vault_url.rstrip("/")
        self.secret_name = secret_name
        self.settings = settings

    def _token(self):
        return runtime.token_for("https://vault.azure.net", settings=self.settings)

    def _url(self):
        return "%s/secrets/%s?api-version=%s" % (self.vault_url, self.secret_name, self.API)

    def load(self):
        r = requests.get(self._url(), headers={"Authorization": "Bearer " + self._token()},
                         timeout=30, allow_redirects=False)
        if 300 <= r.status_code < 400:
            raise requests.HTTPError("Key Vault token cache redirects are not allowed", response=r)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("value")

    def save(self, data):
        r = requests.put(self._url(), headers={"Authorization": "Bearer " + self._token()},
                         json={"value": data, "contentType": "application/json"}, timeout=30, allow_redirects=False)
        if 300 <= r.status_code < 400:
            raise requests.HTTPError("Key Vault token cache redirects are not allowed", response=r)
        r.raise_for_status()


def cache_store_from_settings(settings):
    if settings.token_cache.lower() == "keyvault":
        if not settings.key_vault_url:
            raise ValueError("TOKEN_CACHE=keyvault needs KEY_VAULT_URL")
        return KeyVaultCacheStore(settings.key_vault_url, settings.token_cache_secret, settings=settings)
    if not settings.token_cache.strip():
        raise ValueError("TOKEN_CACHE must be a file path or 'keyvault'")
    return FileCacheStore(settings.token_cache)


def _login_context_renderer(settings):
    runtime.require_identity(settings.tenant_id, settings.test_user_upn, settings.test_user_object_id)
    run = "%s-%s" % (settings.auth_run_label or "cfeval-login", uuid4().hex[:12])
    tenant = "%s / %s" % (settings.tenant_label, settings.tenant_id) if settings.tenant_label else settings.tenant_id

    def render(verification_uri, user_code, resource):
        if verification_uri.rstrip("/") not in ("https://login.microsoft.com/device",
                                                 "https://microsoft.com/devicelogin",
                                                 "https://www.microsoft.com/devicelogin"):
            raise runtime.LoginRequired("Unrecognized verification URL; no sign-in context was displayed")
        service = {"https://graph.microsoft.com": "Microsoft 365 Copilot Chat / Microsoft Graph",
                   "https://analysis.windows.net/powerbi/api": "Power BI"}.get(resource, resource)
        label = "Scout | %s | %s | %s | %s" % (run, service, tenant, settings.test_user_upn)
        details = (("Task/run", run), ("Service", service), ("Expected tenant", tenant),
                   ("Expected user", settings.test_user_upn), ("Environment", runtime.host_name()),
                   ("Azure subscription", settings.azure_subscription_id or "not used for this sign-in"))
        rows = "".join("<dt>%s</dt><dd>%s</dd>" % (html.escape(k), html.escape(v)) for k, v in details)
        body = ('<section role="region" aria-label="%s"><h1>%s</h1><dl>%s</dl>'
                '<p>Keep this context visible throughout sign-in and consent. '
                'Use a new tab in this SAME window. If the browser opens another window, move the sign-in tab '
                'here before continuing. Check the expected account and tenant; do not switch another session.</p>'
                '<p>Device sign-in code: <code>%s</code></p>'
                '<a href="%s" target="_blank" rel="noopener noreferrer">Open Microsoft device sign-in '
                'in a new tab in this window</a></section>') % (
                    html.escape(label), html.escape(label), rows, html.escape(user_code), html.escape(verification_uri))
        return label, body

    return render


def browser_login_callback(settings, directory=None, opener=None, prompt=print):
    """Explicit CLI opt-in: callback(uri, code, resource) must establish same-window context.

    This helper opens only a harmless local context page. The user clicks its
    documented Microsoft device verification link into a tab in that window.
    Keep the context tab open through redirects and consent; no provider UI is changed.
    """
    render = _login_context_renderer(settings)
    directory = Path(directory) if directory is not None else Path(settings.output_dir) / "auth-context"

    def callback(verification_uri, user_code, resource):
        label, body = render(verification_uri, user_code, resource)
        page = '<!doctype html><html lang="en"><meta charset="utf-8"><title>%s</title>%s</html>' % (
            html.escape(label), body)
        path = (directory / (uuid4().hex + ".html")).resolve()
        _atomic_private_write(path, page)
        if opener is None:
            import webbrowser
            open_page = webbrowser.open
        else:
            open_page = opener
        if not open_page(path.as_uri(), new=1):
            raise runtime.LoginRequired("Open the labelled context page manually before retrying sign-in: %s" % path)
        prompt("Authentication context: %s. Keep it open with sign-in in the same browser window." % path)
        return True

    return callback


def notebook_login_callback(settings, prompt=print):
    """Explicit notebook opt-in; display context beside a user-clicked sign-in link.

    Keep this output visible in the same browser window throughout redirects
    and consent. No kernel-host files or browser processes are needed.
    """
    render = _login_context_renderer(settings)

    def callback(verification_uri, user_code, resource):
        _, body = render(verification_uri, user_code, resource)
        try:
            from IPython.display import HTML, display
        except ImportError:
            raise runtime.LoginRequired("Notebook sign-in requires IPython.display and persistent HTML output; "
                                        "open this explicit login from a notebook UI") from None
        display(HTML(body))
        prompt("Authentication context displayed in notebook output. Keep this notebook visible in the "
               "same browser window as sign-in.")
        return True

    return callback


class DelegatedAuth:
    """Silent by default; device sign-in requires explicit opt-in and a context callback.

    A dedicated, low-traffic test user is recommended, not required.
    """

    def __init__(self, tenant_id, client_id, cache_store, expected_upn="", prompt=print,
                 expected_object_id="", login_callback=None):
        runtime.require_identity(tenant_id, expected_upn, expected_object_id)
        runtime._uuid(client_id, "CLIENT_ID")
        import msal  # imported lazily so offline mode needs no extra packages

        self._store = cache_store
        self._cache = msal.SerializableTokenCache()
        existing = cache_store.load()
        if existing:
            self._cache.deserialize(existing)
        self._app = msal.PublicClientApplication(
            client_id, authority="https://login.microsoftonline.com/%s" % tenant_id, token_cache=self._cache)
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.expected_upn = expected_upn
        self.expected_object_id = expected_object_id
        self._signed_in_upn = ""
        self._prompt = prompt
        self._login_callback = login_callback

    @classmethod
    def from_settings(cls, settings, prompt=print, login_callback=None):
        runtime.require_identity(settings.tenant_id, settings.test_user_upn, settings.test_user_object_id)
        return cls(settings.tenant_id, settings.client_id, cache_store_from_settings(settings),
                   settings.test_user_upn, prompt, settings.test_user_object_id, login_callback)

    def _account(self):
        accounts = [a for a in self._app.get_accounts(username=self.expected_upn)
                    if a.get("username", "").casefold() == self.expected_upn.casefold()
                    and a.get("realm", "").lower() == self.tenant_id.lower()
                    and (not self.expected_object_id
                         or a.get("local_account_id", "").lower() == self.expected_object_id.lower())]
        if len(accounts) > 1:
            raise runtime.LoginRequired("Multiple matching cached accounts; use a dedicated test-user cache")
        return accounts[0] if accounts else None

    def token(self, scopes=None, *, interactive=False):
        scopes = scopes or GRAPH_COPILOT_CHAT_SCOPES
        resource = runtime.resource_for_scopes(scopes)
        before = self._cache.serialize()
        self._signed_in_upn = ""
        try:
            account = self._account()
            result = self._app.acquire_token_silent(scopes, account=account) if account else None
            if not result or "access_token" not in result:
                if not interactive or self._login_callback is None:
                    raise runtime.LoginRequired("No usable token for the configured test user. Run explicit login "
                                                "with a labelled browser context; unattended runs never prompt.")
                flow = self._app.initiate_device_flow(scopes=scopes)
                if not flow.get("user_code") or not flow.get("verification_uri"):
                    raise runtime.LoginRequired("Device sign-in could not start; no anonymous prompt was displayed")
                if self._login_callback(flow["verification_uri"], flow["user_code"], resource) is not True:
                    raise runtime.LoginRequired("A persistent same-window sign-in context must be established first")
                result = self._app.acquire_token_by_device_flow(flow)
            if not result or "access_token" not in result:
                raise runtime.LoginRequired("Sign-in did not return a usable token for the configured test user")
            claims = runtime.inspect_acquired_token(
                result["access_token"], resource, self.tenant_id, self.expected_upn, self.expected_object_id,
                required_scopes=scopes, client_id=self.client_id)
        except Exception:
            self._cache.deserialize(before)
            raise
        if self._cache.has_state_changed:
            self._store.save(self._cache.serialize())
        self._signed_in_upn = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name")
        return result["access_token"]

    def signed_in_upn(self):
        return self._signed_in_upn
