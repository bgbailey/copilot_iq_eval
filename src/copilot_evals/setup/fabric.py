"""A thin client for the Fabric, Power BI and OneLake REST calls the deployment makes.

One method per documented endpoint (config/contracts.yaml ``fabric_rest``, ``power_bi_dataset_users``,
``onelake_dfs``), nothing more: the deployment logic lives in ``fabric_deploy``. All calls are
delegated, as the operator who runs ``evals deploy fabric``.
"""

import base64
import json
from typing import Any
from urllib.parse import quote

from copilot_evals.setup.rest import HttpError, JsonHttp

FABRIC_API = "https://api.fabric.microsoft.com/v1"
POWER_BI_API = "https://api.powerbi.com/v1.0/myorg"
ONELAKE_DFS = "https://onelake.dfs.fabric.microsoft.com"

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
POWER_BI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
STORAGE_SCOPE = "https://storage.azure.com/.default"

#: Workspace monitoring settings (preview API): collect every workspace diagnostic into an Eventhouse.
MONITORING_PROPERTIES = {
    "dataCollectionSettings": [
        {
            "sources": {"workspaceDiagnostics": {"mode": "All"}},
            "destinations": {"eventhouse": {"mode": "Auto"}, "eventStream": {"customEndpoint": {"enabled": False}}},
        }
    ],
    "operationsAgent": {"enabled": False},
}


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _notebook_definition(ipynb: str) -> dict[str, Any]:
    return {
        "format": "ipynb",
        "parts": [{"path": "notebook-content.ipynb", "payload": _b64(ipynb), "payloadType": "InlineBase64"}],
    }


class FabricClient:
    """Fabric REST (workspaces, items, jobs), Power BI REST (dataset permissions) and OneLake reads."""

    def __init__(self, http: JsonHttp) -> None:
        self._http = http

    # --- capacities and workspaces ---------------------------------------------------------

    def capacities(self) -> list[dict[str, Any]]:
        return list(self._http.paged(f"{FABRIC_API}/capacities", scope=FABRIC_SCOPE))

    def workspaces(self) -> list[dict[str, Any]]:
        return list(self._http.paged(f"{FABRIC_API}/workspaces", scope=FABRIC_SCOPE))

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._http.get(f"{FABRIC_API}/workspaces/{workspace_id}", scope=FABRIC_SCOPE)
        return result

    def create_workspace(self, name: str, capacity_id: str, description: str) -> dict[str, Any]:
        body = {"displayName": name, "capacityId": capacity_id, "description": description}
        result: dict[str, Any] = self._http.request(
            "POST", f"{FABRIC_API}/workspaces", scope=FABRIC_SCOPE, json_body=body, expected=(201,)
        ).json()
        return result

    def assign_to_capacity(self, workspace_id: str, capacity_id: str) -> None:
        self._http.request(
            "POST", f"{FABRIC_API}/workspaces/{workspace_id}/assignToCapacity", scope=FABRIC_SCOPE,
            json_body={"capacityId": capacity_id}, expected=(200, 202),
        )

    def role_assignments(self, workspace_id: str) -> list[dict[str, Any]]:
        url = f"{FABRIC_API}/workspaces/{workspace_id}/roleAssignments"
        return list(self._http.paged(url, scope=FABRIC_SCOPE))

    def add_role_assignment(self, workspace_id: str, principal_id: str, principal_type: str, role: str) -> None:
        body = {"principal": {"id": principal_id, "type": principal_type}, "role": role}
        self._http.request(
            "POST", f"{FABRIC_API}/workspaces/{workspace_id}/roleAssignments", scope=FABRIC_SCOPE,
            json_body=body, expected=(200, 201),
        )

    # --- items -----------------------------------------------------------------------------

    def items(self, workspace_id: str, item_type: str) -> list[dict[str, Any]]:
        url = f"{FABRIC_API}/workspaces/{workspace_id}/items?type={quote(item_type)}"
        return list(self._http.paged(url, scope=FABRIC_SCOPE))

    def create_lakehouse(self, workspace_id: str, name: str, description: str) -> dict[str, Any]:
        """Create a lakehouse without schemas (nb_01 writes to Tables/<name>, PLAN §4.1)."""
        response = self._http.request(
            "POST", f"{FABRIC_API}/workspaces/{workspace_id}/lakehouses", scope=FABRIC_SCOPE,
            json_body={"displayName": name, "description": description}, expected=(201, 202),
        )
        created: dict[str, Any] = self._http.wait_for_operation(response, scope=FABRIC_SCOPE) or {}
        return created

    def create_notebook(self, workspace_id: str, name: str, ipynb: str, description: str) -> dict[str, Any]:
        body = {"displayName": name, "description": description, "definition": _notebook_definition(ipynb)}
        response = self._http.request(
            "POST", f"{FABRIC_API}/workspaces/{workspace_id}/notebooks", scope=FABRIC_SCOPE,
            json_body=body, expected=(201, 202),
        )
        created: dict[str, Any] = self._http.wait_for_operation(response, scope=FABRIC_SCOPE) or {}
        return created

    def update_notebook(self, workspace_id: str, notebook_id: str, ipynb: str) -> None:
        url = f"{FABRIC_API}/workspaces/{workspace_id}/notebooks/{notebook_id}/updateDefinition"
        response = self._http.request(
            "POST", url, scope=FABRIC_SCOPE, json_body={"definition": _notebook_definition(ipynb)},
            expected=(200, 202),
        )
        self._http.wait_for_operation(response, scope=FABRIC_SCOPE)

    def run_notebook(
        self, workspace_id: str, notebook_id: str, parameters: dict[str, tuple[object, str]], lakehouse_id: str
    ) -> tuple[str, float]:
        """Start a notebook run; ``parameters`` maps name -> (value, type), type being Text, Integer,
        Number or Boolean, values in their native JSON type. The run uses ``lakehouse_id`` in
        ``workspace_id`` as its default lakehouse. Returns the job instance URL to poll and the
        seconds to wait before the first poll (``Retry-After``)."""
        url = f"{FABRIC_API}/workspaces/{workspace_id}/notebooks/{notebook_id}/jobs/execute/instances?beta=false"
        body = {
            "parameters": [{"name": name, "value": value, "type": kind} for name, (value, kind) in parameters.items()],
            "executionData": {
                "compute": "Spark",
                "computeConfiguration": {
                    "defaultLakehouse": {"referenceType": "ById", "itemId": lakehouse_id, "workspaceId": workspace_id}
                },
            },
        }
        response = self._http.request("POST", url, scope=FABRIC_SCOPE, json_body=body, expected=(202,))
        location = response.header("location")
        if not location:
            raise HttpError("POST", url, response.status, b'{"message": "no Location header on the job response"}')
        try:
            first_poll_s = float(response.header("retry-after") or 60)
        except ValueError:
            first_poll_s = 60.0
        return location, first_poll_s

    def wait_for_job(self, location: str, timeout_s: float, first_poll_s: float = 60) -> dict[str, Any]:
        return self._http.wait_for_job(location, scope=FABRIC_SCOPE, timeout_s=timeout_s, first_poll_s=first_poll_s)

    # --- workspace monitoring (preview API) ------------------------------------------------

    def create_monitoring(self, workspace_id: str, name: str) -> dict[str, Any]:
        definition = {
            "format": "MonitoringV1",
            "parts": [
                {"path": "MonitoringProperties.json", "payload": _b64(json.dumps(MONITORING_PROPERTIES)),
                 "payloadType": "InlineBase64"}
            ],
        }
        response = self._http.request(
            "POST", f"{FABRIC_API}/workspaces/{workspace_id}/monitoringItems", scope=FABRIC_SCOPE,
            json_body={"displayName": name, "definition": definition}, expected=(201, 202),
        )
        created: dict[str, Any] = self._http.wait_for_operation(response, scope=FABRIC_SCOPE) or {}
        return created

    def enable_monitoring(self, workspace_id: str, monitoring_id: str) -> bool:
        """Turn on data collection (succeeds unchanged when it is already on). False on 409:
        another monitoring item in the workspace already collects (WSMDataCollectionAlreadyEnabledInWorkspace)."""
        url = f"{FABRIC_API}/workspaces/{workspace_id}/monitoringItems/{monitoring_id}/enableDataCollection"
        response = self._http.request("POST", url, scope=FABRIC_SCOPE, expected=(200, 202, 409))
        if response.status == 202:
            self._http.wait_for_operation(response, scope=FABRIC_SCOPE)
        return response.status != 409

    # --- Power BI: datasets and permissions ------------------------------------------------

    def datasets(self, workspace_id: str) -> list[dict[str, Any]]:
        return list(self._http.paged(f"{POWER_BI_API}/groups/{workspace_id}/datasets", scope=POWER_BI_SCOPE))

    def grant_dataset_access(self, workspace_id: str, dataset_id: str, upn: str, access: str = "ReadExplore") -> None:
        """Give a user Read and Build on a semantic model (ReadExplore) so Copilot can query it for them."""
        body = {"identifier": upn, "principalType": "User", "datasetUserAccessRight": access}
        self._http.request(
            "POST", f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}/users", scope=POWER_BI_SCOPE,
            json_body=body, expected=(200,),
        )

    # --- OneLake ---------------------------------------------------------------------------

    def read_onelake_file(self, workspace_id: str, item_id: str, path: str) -> bytes:
        url = f"{ONELAKE_DFS}/{workspace_id}/{item_id}/{quote(path)}"
        return self._http.request("GET", url, scope=STORAGE_SCOPE, expected=(200,)).body
