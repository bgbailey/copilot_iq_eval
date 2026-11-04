"""Setup automation (``evals deploy``) against an in-memory fake tenant: no network, no credentials.

``FakeTenant`` answers the Fabric, Power BI, OneLake and Microsoft Graph calls the deployment makes,
in the shapes config/contracts.yaml records, so these tests pin down what the deployment sends: which
items it creates, which roles it grants, the notebook parameters, and that a second run changes
nothing.
"""

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from copilot_evals.config import Settings
from copilot_evals.golden import load_golden_set
from copilot_evals.setup.fabric import FabricClient
from copilot_evals.setup.fabric_deploy import FabricDeployment, build_plan
from copilot_evals.setup.graph import GraphClient
from copilot_evals.setup.rest import HttpError, JsonHttp, Response, SetupError, urllib_transport
from copilot_evals.setup.workiq import CONTENT_FILE, DOCUMENTS_DIR, WorkIQSeeder, load_content_pack

FABRIC = "https://api.fabric.microsoft.com/v1"
POWER_BI = "https://api.powerbi.com/v1.0/myorg"
GRAPH = "https://graph.microsoft.com/v1.0"
ONELAKE = r"https://onelake\.dfs\.fabric\.microsoft\.com"
Route = Callable[[re.Match[str], Any], Response]


def _json(status: int, payload: Any = None, **headers: str) -> Response:
    body = json.dumps(payload).encode() if payload is not None else b""
    return Response(status, {name.replace("_", "-").lower(): value for name, value in headers.items()}, body)


class FakeTenant:
    """Just enough of Fabric, Power BI, OneLake and Graph for the deployment, with recorded calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.workspaces: list[dict[str, Any]] = []
        self.items: dict[str, list[dict[str, Any]]] = {}
        self.roles: dict[str, list[dict[str, Any]]] = {}
        self.datasets: dict[str, list[dict[str, str]]] = {}
        self.dataset_users: list[tuple[str, str, str]] = []
        self.notebook_runs: list[tuple[str, dict[str, Any]]] = []
        self.drive_items: dict[str, dict[str, Any]] = {}
        self._ids = 0
        self._routes: list[tuple[str, re.Pattern[str], Route]] = [
            ("GET", re.compile(rf"{GRAPH}/users/([^?]+)\?"), lambda m, _: _json(200, {"id": f"user:{m[1]}"})),
            ("GET", re.compile(rf"{GRAPH}/servicePrincipals\(appId='([^']+)'\)"),
             lambda m, _: _json(200, {"id": f"sp:{m[1]}"})),
            ("GET", re.compile(rf"{FABRIC}/capacities$"), lambda m, _: _json(200, {"value": [
                {"id": "cap-1", "displayName": "fcdemo64", "sku": "F64", "state": "Active"}]})),
            ("GET", re.compile(rf"{FABRIC}/workspaces$"), lambda m, _: _json(200, {"value": self.workspaces})),
            ("POST", re.compile(rf"{FABRIC}/workspaces$"), self._create_workspace),
            ("GET", re.compile(rf"{FABRIC}/workspaces/([^/]+)/roleAssignments$"),
             lambda m, _: _json(200, {"value": self.roles.setdefault(m[1], [])})),
            ("POST", re.compile(rf"{FABRIC}/workspaces/([^/]+)/roleAssignments$"), self._add_role),
            ("GET", re.compile(rf"{FABRIC}/workspaces/([^/]+)/items\?type=(\w+)$"), self._list_items),
            ("POST", re.compile(rf"{FABRIC}/workspaces/([^/]+)/lakehouses$"), self._create_lakehouse),
            ("GET", re.compile(rf"{FABRIC}/operations/(op-[^/]+)$"), lambda m, _: _json(
                200, {"status": "Succeeded"}, location=f"{FABRIC}/operations/{m[1]}/result")),
            ("GET", re.compile(rf"{FABRIC}/operations/(op-[^/]+)/result$"), self._operation_result),
            ("POST", re.compile(rf"{FABRIC}/workspaces/([^/]+)/monitoringItems$"), self._create_monitoring),
            ("POST", re.compile(rf"{FABRIC}/workspaces/[^/]+/monitoringItems/[^/]+/enableDataCollection$"),
             lambda m, _: _json(200)),
            ("POST", re.compile(rf"{FABRIC}/workspaces/([^/]+)/notebooks$"),
             lambda m, body: _json(201, self._add_item(m[1], "Notebook", body["displayName"]))),
            ("POST", re.compile(rf"{FABRIC}/workspaces/[^/]+/notebooks/[^/]+/updateDefinition$"),
             lambda m, _: _json(200)),
            ("POST", re.compile(rf"{FABRIC}/workspaces/([^/]+)/notebooks/([^/]+)/jobs/execute/instances\?beta=false$"),
             self._run_notebook),
            ("GET", re.compile(rf"{FABRIC}/workspaces/[^/]+/items/[^/]+/jobs/instances/[^/]+$"),
             lambda m, _: _json(200, {"status": "Completed"})),
            ("GET", re.compile(rf"{POWER_BI}/groups/([^/]+)/datasets$"),
             lambda m, _: _json(200, {"value": self.datasets.get(m[1], [])})),
            ("POST", re.compile(rf"{POWER_BI}/groups/([^/]+)/datasets/([^/]+)/users$"), self._grant),
            ("GET", re.compile(rf"{ONELAKE}/[^/]+/[^/]+/Files/eval/expected_snapshot\.json$"),
             lambda m, _: _json(200, {"cases": {"REV-001": {"value": "12840000.00"}}, "errors": {}})),
            ("GET", re.compile(rf"{GRAPH}/sites/contoso\.sharepoint\.com:/sites/([\w-]+)$"),
             lambda m, _: _json(200, {"id": f"site:{m[1]}"})),
            ("GET", re.compile(rf"{GRAPH}/sites/site:([\w-]+)/drive$"),
             lambda m, _: _json(200, {"id": f"drive:{m[1]}"})),
            ("POST", re.compile(rf"{GRAPH}/drives/([^/]+)/items/([^/]+)/children$"), self._create_folder),
            ("GET", re.compile(rf"{GRAPH}/drives/([^/]+)/root:/(.+)$"), self._item_by_path),
            ("PUT", re.compile(rf"{GRAPH}/drives/([^/]+)/items/([^/]+):/([^:]+):/content\?"), self._upload),
        ]

    # --- transport ---------------------------------------------------------------------------

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> Response:
        assert headers["Authorization"] == "Bearer test-token"
        self.calls.append((method, url))
        payload = json.loads(body) if body and headers.get("Content-Type") == "application/json" else body
        for route_method, pattern, handler in self._routes:
            match = pattern.match(url)
            if route_method == method and match:
                return handler(match, payload)
        return _json(404, {"error": {"code": "NotFound", "message": f"no fake route for {method} {url}"}})

    def creates(self) -> list[str]:
        return [url for method, url in self.calls if method in {"POST", "PUT"}]

    # --- Fabric ------------------------------------------------------------------------------

    def _new_id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}-{self._ids}"

    def _add_item(self, workspace_id: str, item_type: str, name: str) -> dict[str, Any]:
        item = {"id": self._new_id(item_type.lower()), "displayName": name, "type": item_type}
        self.items.setdefault(workspace_id, []).append(item)
        return item

    def _create_workspace(self, match: re.Match[str], body: Any) -> Response:
        workspace = {"id": self._new_id("ws"), "displayName": body["displayName"], "capacityId": body["capacityId"]}
        self.workspaces.append(workspace)
        return _json(201, workspace)

    def _add_role(self, match: re.Match[str], body: Any) -> Response:
        self.roles.setdefault(match[1], []).append({"principal": body["principal"], "role": body["role"]})
        return _json(201)

    def _list_items(self, match: re.Match[str], body: Any) -> Response:
        return _json(200, {"value": [i for i in self.items.get(match[1], []) if i["type"] == match[2]]})

    def _create_monitoring(self, match: re.Match[str], body: Any) -> Response:
        """Items of type Monitoring; the deployment reuses an existing one rather than creating another."""
        assert not any(i["type"] == "Monitoring" for i in self.items.get(match[1], [])), "monitoring created twice"
        return _json(201, self._add_item(match[1], "Monitoring", body["displayName"]))

    def _create_lakehouse(self, match: re.Match[str], body: Any) -> Response:
        assert "creationPayload" not in body, "lakehouses are created without schemas (nb_01 writes Tables/<name>)"
        item = self._add_item(match[1], "Lakehouse", body["displayName"])
        operation = f"op-{item['id']}"
        self._pending = getattr(self, "_pending", {}) | {operation: item}
        return _json(202, location=f"{FABRIC}/operations/{operation}", retry_after="1")

    def _operation_result(self, match: re.Match[str], body: Any) -> Response:
        return _json(200, self._pending[match[1]])

    def _run_notebook(self, match: re.Match[str], body: Any) -> Response:
        notebook = next(i for i in self.items[match[1]] if i["id"] == match[2])
        self.notebook_runs.append((notebook["displayName"], body))
        if notebook["displayName"] == "nb_02_build_models":
            for workspace in self.workspaces:
                names = {"ws-eval-certified": ["Sales Analytics", "Finance", "Service Operations"],
                         "ws-eval-sandbox": ["Sales Sandbox"]}.get(workspace["displayName"], [])
                self.datasets[workspace["id"]] = [{"id": f"ds:{name}", "name": name} for name in names]
        location = f"{FABRIC}/workspaces/{match[1]}/items/{match[2]}/jobs/instances/job-{len(self.notebook_runs)}"
        return _json(202, location=location, retry_after="1")

    def _grant(self, match: re.Match[str], body: Any) -> Response:
        self.dataset_users.append((match[2], body["identifier"], body["datasetUserAccessRight"]))
        return _json(200)

    # --- Graph: SharePoint --------------------------------------------------------------------

    def _create_folder(self, match: re.Match[str], body: Any) -> Response:
        parent = "" if match[2] == "root" else self.drive_items_by_id()[match[2]]["path"]
        path = f"{parent}/{body['name']}".lstrip("/")
        if (match[1], path) in {(i["drive"], i["path"]) for i in self.drive_items.values()}:
            return _json(409, {"error": {"code": "nameAlreadyExists", "message": "exists"}})
        item = {"id": self._new_id("folder"), "drive": match[1], "path": path, "size": 0}
        self.drive_items[item["id"]] = item
        return _json(201, item)

    def _item_by_path(self, match: re.Match[str], body: Any) -> Response:
        from urllib.parse import unquote

        path = unquote(match[2])
        item = next((i for i in self.drive_items.values() if i["drive"] == match[1] and i["path"] == path), None)
        return _json(200, item) if item else _json(404, {"error": {"code": "itemNotFound", "message": path}})

    def _upload(self, match: re.Match[str], body: Any) -> Response:
        from urllib.parse import unquote

        path = f"{self.drive_items_by_id()[match[2]]['path']}/{unquote(match[3])}"
        item = {"id": self._new_id("file"), "drive": match[1], "path": path, "size": len(body),
                "webUrl": f"https://contoso.sharepoint.com/{path}"}
        self.drive_items = {k: v for k, v in self.drive_items.items() if (v["drive"], v["path"]) != (match[1], path)}
        self.drive_items[item["id"]] = item
        return _json(201, item)

    def drive_items_by_id(self) -> dict[str, dict[str, Any]]:
        return self.drive_items


def _http(tenant: FakeTenant) -> JsonHttp:
    return JsonHttp(lambda scope: "test-token", transport=tenant, sleep=lambda seconds: None)


def _settings(*, tenant_domain: str = "contoso.example", **fabric: Any) -> Settings:
    return Settings.model_validate({
        "tenant": {"tenant_id": "00000000-0000-0000-0000-000000000001", "tenant_domain": tenant_domain},
        "apps": {"daemon_client_id": "11111111-2222-3333-4444-555555555555"},
        "fabric": {"capacity": "fcdemo64", **fabric},
        "workiq": {"sites": {"planning": "https://contoso.sharepoint.com/sites/eval-planning",
                             "all_company": "https://contoso.sharepoint.com/sites/eval-all-company"}},
    })


def _deploy(tenant: FakeTenant, golden_dir: Path, repo_root: Path, **run: Any) -> FabricDeployment:
    plan = build_plan(_settings(), load_golden_set(golden_dir))
    http = _http(tenant)
    deployment = FabricDeployment(plan, FabricClient(http), GraphClient(http), repo_root / "fabric" / "notebooks",
                                  report=lambda line: None)
    deployment.run(**run)
    return deployment


# --- evals deploy fabric -----------------------------------------------------------------------


def test_fabric_deployment_from_an_empty_tenant(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    result = _deploy(tenant, golden_dir, repo_root).result

    assert [w["displayName"] for w in tenant.workspaces] == ["ws-eval-certified", "ws-eval-sandbox", "ws-eval-results"]
    assert {w["capacityId"] for w in tenant.workspaces} == {"cap-1"}
    assert set(result.lakehouse_ids) == {"certified", "sandbox", "results"}
    assert [name for name, _ in tenant.notebook_runs] == [
        "nb_01_generate_data", "nb_02_build_models", "nb_03_validate_and_snapshot"]
    assert result.snapshot == {"cases": {"REV-001": {"value": "12840000.00"}}, "errors": {}}
    assert result.warnings == []


def test_personas_are_viewers_and_the_daemon_reads_logs(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    result = _deploy(tenant, golden_dir, repo_root).result
    roles = {
        (name, assignment["principal"]["id"], assignment["role"])
        for name, workspace_id in {"certified": result.workspace_ids["certified"],
                                   "sandbox": result.workspace_ids["sandbox"],
                                   "results": result.workspace_ids["results"]}.items()
        for assignment in tenant.roles[workspace_id]
    }

    assert ("certified", "user:eval.exec%40contoso.example", "Viewer") in roles
    assert ("certified", "user:eval.east%40contoso.example", "Viewer") in roles
    assert ("sandbox", "user:eval.noaccess%40contoso.example", "Viewer") in roles
    assert not any(principal.startswith("user:eval.noaccess") for name, principal, _ in roles if name == "certified")
    assert ("results", "sp:11111111-2222-3333-4444-555555555555", "Contributor") in roles


def test_notebook_parameters_carry_rls_and_the_snapshot_cases(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    _deploy(tenant, golden_dir, repo_root)
    runs = {name: {p["name"]: p for p in body["parameters"]} for name, body in tenant.notebook_runs}

    assert json.loads(runs["nb_01_generate_data"]["security_user_region_json"]["value"]) == {
        "eval.east@contoso.example": ["East"]}
    assert runs["nb_02_build_models"]["all_regions_members"]["value"] == "eval.exec@contoso.example"
    assert runs["nb_02_build_models"]["region_scope_members"]["value"] == "eval.east@contoso.example"
    assert runs["nb_02_build_models"]["_inlineInstallationEnabled"] == {
        "name": "_inlineInstallationEnabled", "value": True, "type": "Boolean"}
    cases = json.loads(runs["nb_03_validate_and_snapshot"]["cases_json"]["value"])
    assert {case["case_id"] for case in cases} >= {"REV-001", "OPS-003", "JNT-002"}
    assert {case["persona"] for case in cases} == {"exec", "east"}
    assert "X-001" not in {case["case_id"] for case in cases}, "composite cases have no single reference query"
    lakehouse = tenant.notebook_runs[0][1]["executionData"]["computeConfiguration"]["defaultLakehouse"]
    assert lakehouse["referenceType"] == "ById"


def test_personas_get_build_on_the_models_they_can_see(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    _deploy(tenant, golden_dir, repo_root)
    grants = {(dataset, upn) for dataset, upn, right in tenant.dataset_users if right == "ReadExplore"}

    assert ("ds:Sales Analytics", "eval.east@contoso.example") in grants
    assert ("ds:Sales Sandbox", "eval.noaccess@contoso.example") in grants
    assert ("ds:Sales Analytics", "eval.noaccess@contoso.example") not in grants
    assert ("ds:Sales Sandbox", "eval.east@contoso.example") not in grants


def test_a_second_run_creates_nothing_new(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    _deploy(tenant, golden_dir, repo_root, run_notebooks=False)
    before = len(tenant.workspaces), sum(len(items) for items in tenant.items.values())
    tenant.calls.clear()

    result = _deploy(tenant, golden_dir, repo_root, run_notebooks=False).result

    assert (len(tenant.workspaces), sum(len(i) for i in tenant.items.values())) == before
    created = [url for url in tenant.creates() if not url.endswith(("/updateDefinition", "/enableDataCollection"))]
    assert created == [], created
    assert "not run (--no-run)" in result.warnings[0]


def test_a_higher_workspace_role_is_reported_not_downgraded(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    _deploy(tenant, golden_dir, repo_root, run_notebooks=False)
    certified = tenant.workspaces[0]["id"]
    for assignment in tenant.roles[certified]:
        if assignment["principal"]["id"] == "user:eval.east%40contoso.example":
            assignment["role"] = "Contributor"

    result = _deploy(tenant, golden_dir, repo_root, run_notebooks=False).result

    assert any("east is Contributor" in w and "row-level security" in w for w in result.warnings)


def test_plan_needs_a_capacity_and_a_tenant_domain(golden_dir: Path) -> None:
    golden = load_golden_set(golden_dir)

    with pytest.raises(SetupError, match="capacity"):
        build_plan(_settings(capacity=""), golden)
    with pytest.raises(SetupError, match="tenant_domain"):
        build_plan(_settings(tenant_domain=""), golden)


def test_paused_capacity_stops_the_deployment(golden_dir: Path, repo_root: Path) -> None:
    tenant = FakeTenant()
    tenant._routes.insert(0, ("GET", re.compile(rf"{FABRIC}/capacities$"), lambda m, _: _json(200, {"value": [
        {"id": "cap-1", "displayName": "fcdemo64", "state": "Paused"}]})))

    with pytest.raises(SetupError, match="is Paused: resume it first"):
        _deploy(tenant, golden_dir, repo_root)


# --- evals deploy workiq -----------------------------------------------------------------------


def _seeder(tenant: FakeTenant, repo_root: Path, golden_dir: Path) -> WorkIQSeeder:
    golden = load_golden_set(golden_dir)
    pack = load_content_pack(repo_root / CONTENT_FILE, golden)
    return WorkIQSeeder(GraphClient(_http(tenant)), pack, golden, dict(_settings().workiq.sites),
                        repo_root / DOCUMENTS_DIR, report=lambda line: None)


def test_workiq_seeding_creates_folders_and_uploads_documents(repo_root: Path, golden_dir: Path) -> None:
    tenant = FakeTenant()
    seeded = _seeder(tenant, repo_root, golden_dir).seed()
    paths = {(item["drive"], item["path"]) for item in tenant.drive_items.values()}

    assert ("drive:eval-planning", "Planning/FY2025/FY2025 Revenue Targets - APPROVED.docx") in paths
    assert ("drive:eval-planning", "Planning/FY2025/FY2025 Service Level Objectives.docx") in paths
    assert ("drive:eval-all-company", "Finance Drafts/FY2025 revenue - DRAFT.docx") in paths
    assert [document.key for document in seeded] == ["fy25_revenue_targets", "fy25_service_objectives",
                                                      "fy25_revenue_draft"]


def test_workiq_seeding_twice_replaces_files(repo_root: Path, golden_dir: Path) -> None:
    tenant = FakeTenant()
    _seeder(tenant, repo_root, golden_dir).seed()
    _seeder(tenant, repo_root, golden_dir).seed()  # folders now answer 409 and are looked up by path

    files = [item for item in tenant.drive_items.values() if item["path"].endswith(".docx")]
    assert len(files) == 3
    assert _seeder(tenant, repo_root, golden_dir).verify() == []


def test_workiq_verify_reports_missing_and_stale_files(repo_root: Path, golden_dir: Path) -> None:
    tenant = FakeTenant()
    _seeder(tenant, repo_root, golden_dir).seed()
    for item in tenant.drive_items.values():
        if item["path"].endswith("DRAFT.docx"):
            item["size"] = 1
    tenant.drive_items = {k: v for k, v in tenant.drive_items.items() if "Service Level" not in v["path"]}

    problems = _seeder(tenant, repo_root, golden_dir).verify()

    assert any("FY2025 Service Level Objectives.docx is missing" in p for p in problems)
    assert any("FY2025 revenue - DRAFT.docx differs" in p for p in problems)


def test_workiq_seeding_needs_every_site_url(repo_root: Path, golden_dir: Path) -> None:
    golden = load_golden_set(golden_dir)
    pack = load_content_pack(repo_root / CONTENT_FILE, golden)
    seeder = WorkIQSeeder(GraphClient(_http(FakeTenant())), pack, golden, {"planning": "https://x"},
                          repo_root / DOCUMENTS_DIR)

    with pytest.raises(SetupError, match=r"\[workiq.sites\].*all_company"):
        seeder.seed()


# --- rest: retries, errors, long-running operations, jobs ---------------------------------------


def _scripted(*responses: Response) -> tuple[JsonHttp, list[float]]:
    queue = list(responses)
    slept: list[float] = []
    http = JsonHttp(lambda scope: "test-token", transport=lambda *args: queue.pop(0), sleep=slept.append)
    return http, slept


def test_throttling_is_retried_after_the_advertised_delay() -> None:
    http, slept = _scripted(_json(429, retry_after="7"), _json(503), _json(200, {"ok": True}))

    assert http.get("https://api.fabric.microsoft.com/v1/x", scope="s") == {"ok": True}
    assert slept == [7.0, 4.0]


def test_errors_carry_the_service_code() -> None:
    http, _ = _scripted(_json(400, {"errorCode": "InvalidInput", "message": "Bad capacity"}))

    with pytest.raises(HttpError, match="400 InvalidInput: Bad capacity") as caught:
        http.get("https://api.fabric.microsoft.com/v1/x?secret=1", scope="s")
    assert caught.value.code == "InvalidInput"
    assert "secret" not in str(caught.value), "query strings are left out of error messages"


def test_lists_follow_continuation_links() -> None:
    http, _ = _scripted(
        _json(200, {"value": [1, 2], "continuationUri": "https://api.fabric.microsoft.com/v1/x?c=2"}),
        _json(200, {"value": [3], "@odata.nextLink": "https://graph.microsoft.com/v1.0/x?n=3"}),
        _json(200, {"value": [4]}),
    )

    assert list(http.paged("https://api.fabric.microsoft.com/v1/x", scope="s")) == [1, 2, 3, 4]


def test_failed_operations_and_jobs_raise_with_the_reason() -> None:
    http, _ = _scripted(_json(200, {"status": "Failed", "error": {"errorCode": "CapacityNotActive"}}))
    accepted = _json(202, location="https://api.fabric.microsoft.com/v1/operations/1")
    with pytest.raises(SetupError, match="CapacityNotActive"):
        http.wait_for_operation(accepted, scope="s")

    http, _ = _scripted(_json(200, {"status": "InProgress"}), _json(200, {"status": "Failed", "failureReason": {
        "message": "AssertionError: Deployment validation failed"}}))
    with pytest.raises(SetupError, match="Deployment validation failed"):
        http.wait_for_job("https://api.fabric.microsoft.com/v1/job", scope="s", timeout_s=600)


def test_production_transport_refuses_plain_http() -> None:
    with pytest.raises(SetupError, match="non-HTTPS"):
        urllib_transport("GET", "http://api.fabric.microsoft.com/v1/x", {}, None)
