"""Fabric REST helpers: OneLake shortcuts from a lakehouse to the Eventhouse tables.

The scorecard app reads telemetry through a lakehouse SQL analytics endpoint.
With OneLake availability on, each KQL table is also stored as Delta in OneLake;
a lakehouse shortcut to it makes it queryable with T-SQL.
"""
import time
from urllib.parse import quote, urlsplit

import requests

from . import runtime
from .schema import TABLES

FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"


def fabric_api_token(settings=None):
    return runtime.token_for(FABRIC_RESOURCE, settings)


class FabricApiError(RuntimeError):
    pass


class FabricClient:
    def __init__(self, token_provider=None, session=None, base_url=FABRIC_API, max_retries=3, settings=None,
                 skill="eventhouse-cli"):
        self._token = token_provider or (lambda: fabric_api_token(settings))
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        base = urlsplit(self.base_url)
        if base.scheme != "https" or not base.hostname or base.username or base.password or base.query or base.fragment:
            raise ValueError("Fabric API base must be an HTTPS URL without credentials, query or fragment")
        self._origin = (base.scheme, base.netloc.lower())
        self.max_retries = max_retries
        self.skill = skill

    def _request(self, method, path, body=None, params=None, missing_ok=False):
        url = path if path.startswith("http") else self.base_url + path
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc.lower()) != self._origin or parsed.username or parsed.password or parsed.fragment:
            raise FabricApiError("Fabric request/continuation escaped the configured HTTPS API origin")
        for attempt in range(self.max_retries + 1):
            r = self.session.request(method, url, json=body, params=params, timeout=60,
                                     headers={"Authorization": "Bearer " + self._token(),
                                              "x-ms-fabric-skill": self.skill}, allow_redirects=False)
            if missing_ok and r.status_code == 404:
                return None
            if r.status_code == 429 and attempt < self.max_retries:
                time.sleep(min(float(r.headers.get("Retry-After") or 10), 60))
                continue
            if r.status_code >= 300:
                raise FabricApiError("Fabric API %s %s returned %s: %s" % (method, path, r.status_code, r.text[:500]))
            return r.json() if r.content else {}
        raise FabricApiError("Fabric API %s %s: retries exhausted" % (method, path))

    def workspace(self, workspace_id):
        return self._request("GET", "/workspaces/%s" % workspace_id)

    def lakehouse(self, workspace_id, item_id):
        return self._request("GET", "/workspaces/%s/lakehouses/%s" % (workspace_id, item_id))

    def kql_database(self, workspace_id, item_id):
        return self._request("GET", "/workspaces/%s/kqlDatabases/%s" % (workspace_id, item_id))

    def items(self, workspace_id, item_type=None):
        out, params = [], {"type": item_type} if item_type else None
        page = self._request("GET", "/workspaces/%s/items" % workspace_id, params=params)
        out += page.get("value", [])
        seen = set()
        while page.get("continuationUri"):
            uri = page["continuationUri"]
            if uri in seen or len(seen) >= 100:
                raise FabricApiError("Fabric item listing repeated a page or exceeded 100 continuation pages")
            seen.add(uri)
            page = self._request("GET", uri)
            out += page.get("value", [])
        return out

    def find_item(self, workspace_id, name, item_type):
        matches = [item for item in self.items(workspace_id, item_type)
                   if item.get("displayName", "").lower() == name.lower()]
        if len(matches) != 1:
            raise FabricApiError("expected one %s named '%s' in workspace %s; found %d" %
                                 (item_type, name, workspace_id, len(matches)))
        return matches[0]

    def create_shortcut(self, workspace_id, item_id, name, target_workspace_id, target_item_id, target_path,
                        path="Tables"):
        lookup = "/workspaces/%s/items/%s/shortcuts/%s/%s" % (
            workspace_id, item_id, quote(path, safe="/"), quote(name, safe=""))
        target = {"workspaceId": target_workspace_id, "itemId": target_item_id, "path": target_path}
        existing = self._request("GET", lookup, missing_ok=True)
        if existing is not None:
            if existing.get("target", {}).get("oneLake") != target or existing.get("transform"):
                raise FabricApiError("Shortcut %s/%s already has a different target; nothing was overwritten" %
                                     (path, name))
            return existing
        self._request(
            "POST", "/workspaces/%s/items/%s/shortcuts" % (workspace_id, item_id),
            body={"path": path, "name": name, "target": {"oneLake": target}},
            params={"shortcutConflictPolicy": "Abort"})
        saved = self._request("GET", lookup)
        if saved.get("target", {}).get("oneLake") != target or saved.get("transform"):
            raise FabricApiError("Shortcut %s/%s did not read back with its expected target" % (path, name))
        return saved


def app_tables():
    return [name for name, spec in TABLES.items() if spec.get("app")]


def create_app_shortcuts(client, lakehouse_workspace_id, lakehouse_id, kql_workspace_id, kql_database_id,
                         tables=None, log=print, path="Tables"):
    """Shortcut each app table from the KQL database (OneLake availability on) into the lakehouse."""
    results = []
    for table in tables or app_tables():
        try:
            client.create_shortcut(lakehouse_workspace_id, lakehouse_id, table, kql_workspace_id, kql_database_id,
                                   "Tables/%s" % table, path=path)
            results.append({"table": table, "status": "ok"})
            log("Verified shortcut %s/%s -> KQL database table %s" % (path, table, table))
        except FabricApiError as exc:
            results.append({"table": table, "status": "error", "detail": str(exc)})
            log("Shortcut for %s failed: %s" % (table, exc))
    return results
