"""A thin client for the Microsoft Graph calls the setup makes (config/contracts.yaml ``graph_sharepoint_files``).

Directory lookups (users and service principals, to grant Fabric roles by object ID) and SharePoint
file operations (sites, folders and uploads, to seed the Work IQ documents). Delegated, as the
operator who runs ``evals deploy``.
"""

from typing import Any
from urllib.parse import quote, urlsplit

from copilot_evals.setup.rest import HttpError, JsonHttp, SetupError

GRAPH_API = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def _path(segments: str) -> str:
    """A drive path with every segment URL-encoded, for the ``root:/<path>:`` addressing form."""
    return "/".join(quote(segment) for segment in segments.strip("/").split("/") if segment)


class GraphClient:
    """Users, service principals and SharePoint drive items."""

    def __init__(self, http: JsonHttp) -> None:
        self._http = http

    # --- directory -------------------------------------------------------------------------

    def user_id(self, upn: str) -> str:
        """The object ID of a user, for Fabric role assignments."""
        try:
            user = self._http.get(f"{GRAPH_API}/users/{quote(upn)}?$select=id", scope=GRAPH_SCOPE)
        except HttpError as error:
            if error.status == 404:
                raise SetupError(f"user {upn} not found: create the persona accounts first (PLAN §6 T6)") from error
            raise
        return str(user["id"])

    def service_principal_id(self, app_id: str) -> str:
        """The object ID of an app registration's service principal, for Fabric role assignments."""
        try:
            principal = self._http.get(
                f"{GRAPH_API}/servicePrincipals(appId='{quote(app_id)}')?$select=id", scope=GRAPH_SCOPE
            )
        except HttpError as error:
            if error.status == 404:
                raise SetupError(f"no service principal for app {app_id}: run infra/entra first") from error
            raise
        return str(principal["id"])

    # --- SharePoint ------------------------------------------------------------------------

    def site(self, site_url: str) -> dict[str, Any]:
        """A site by URL, for example https://contoso.sharepoint.com/sites/eval-planning."""
        parts = urlsplit(site_url)
        if parts.scheme != "https" or not parts.hostname or not parts.path.strip("/"):
            raise SetupError(f"not a SharePoint site URL: {site_url!r}")
        try:
            site: dict[str, Any] = self._http.get(
                f"{GRAPH_API}/sites/{parts.hostname}:/{_path(parts.path)}", scope=GRAPH_SCOPE
            )
        except HttpError as error:
            if error.status in {403, 404}:
                message = f"site {site_url} not found or not accessible: create it first (PLAN §6 T20)"
                raise SetupError(message) from error
            raise
        return site

    def default_drive(self, site_id: str) -> dict[str, Any]:
        """The site's default document library (Shared Documents)."""
        drive: dict[str, Any] = self._http.get(f"{GRAPH_API}/sites/{site_id}/drive", scope=GRAPH_SCOPE)
        return drive

    def ensure_folder(self, drive_id: str, folder_path: str) -> str:
        """Create each folder in ``folder_path`` that does not exist yet; return the last folder's item ID."""
        parent = "root"
        walked = ""
        for name in [segment for segment in folder_path.strip("/").split("/") if segment]:
            walked = f"{walked}/{name}"
            body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
            url = f"{GRAPH_API}/drives/{drive_id}/items/{parent}/children"
            response = self._http.request("POST", url, scope=GRAPH_SCOPE, json_body=body, expected=(201, 409))
            if response.status == 201:
                parent = str(response.json()["id"])
            else:
                existing = self._http.get(f"{GRAPH_API}/drives/{drive_id}/root:/{_path(walked)}", scope=GRAPH_SCOPE)
                parent = str(existing["id"])
        return parent

    def upload(self, drive_id: str, parent_id: str, file_name: str, content: bytes) -> dict[str, Any]:
        """Upload or replace a small file (up to 250 MB) in a folder; return the drive item."""
        url = (
            f"{GRAPH_API}/drives/{drive_id}/items/{parent_id}:/{quote(file_name)}:/content"
            "?@microsoft.graph.conflictBehavior=replace"
        )
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        item: dict[str, Any] = self._http.request(
            "PUT", url, scope=GRAPH_SCOPE, data=content, content_type=content_type, expected=(200, 201)
        ).json()
        return item

    def item_by_path(self, drive_id: str, path: str) -> dict[str, Any] | None:
        """A drive item by path, or None when it does not exist (or the caller cannot see it)."""
        try:
            url = f"{GRAPH_API}/drives/{drive_id}/root:/{_path(path)}"
            item: dict[str, Any] = self._http.get(url, scope=GRAPH_SCOPE)
        except HttpError as error:
            if error.status in {403, 404}:
                return None
            raise
        return item
