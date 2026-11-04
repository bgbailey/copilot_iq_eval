"""``evals deploy fabric``: the Fabric estate the golden set targets, from nothing to validated.

PLAN §4.1-§4.3 and docs/deployment.md. Every step is idempotent: items are found by display name
and created only when missing, notebooks are updated in place, and the notebooks rebuild their
tables and models deterministically. Re-running the command is the way to repair a deployment.

Steps:

1.  Identities: persona UPNs (personas.yaml with ``[tenant] tenant_domain``) and object IDs, and the
    daemon app's service principal if ``[apps] daemon_client_id`` is set.
2.  Capacity: ``[fabric] capacity``, by display name or ID; it must be active.
3.  Workspaces: certified, sandbox and results, each on the capacity.
4.  Workspace roles: each persona gets **Viewer** on the workspaces personas.yaml lists, because
    row-level security applies only to Viewers. The daemon gets Viewer on the certified and
    sandbox workspaces (engine logs) and Contributor on the results workspace.
5.  Lakehouses: gold (certified), sandbox (sandbox) and results (results), without schemas.
6.  Workspace monitoring (preview API) on the certified and sandbox workspaces, if enabled.
7.  Notebooks nb_01-nb_03 imported into the certified workspace.
8.  nb_01 generates the data; nb_02 builds the models, RLS roles and role members.
9.  Each persona gets Read and Build (ReadExplore) on the models in its workspaces.
10. nb_03 validates the calibrated figures as each persona and snapshots the expected values,
    which are downloaded to ``runs/deploy/expected_snapshot.json``.

What stays manual is returned in ``DeployResult.manual_steps`` and printed by the CLI.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copilot_evals.config import Settings
from copilot_evals.golden import GoldenSet
from copilot_evals.schemas import Behavior
from copilot_evals.setup.fabric import FabricClient
from copilot_evals.setup.graph import GraphClient
from copilot_evals.setup.rest import HttpError, SetupError

NOTEBOOKS = ("nb_01_generate_data", "nb_02_build_models", "nb_03_validate_and_snapshot")
SNAPSHOT_PATH = "Files/eval/expected_snapshot.json"
OUTPUT_DIR = Path("runs") / "deploy"

#: Workspace roles that already include Viewer rights; an existing higher role is never downgraded.
_ROLE_RANK = {"Viewer": 0, "Contributor": 1, "Member": 2, "Admin": 3}

MANUAL_STEPS = (
    "Prep data for AI on each certified model: AI data schema, AI instructions and verified answers (PLAN §4.2).",
    "Endorse Sales Analytics, Finance and Service Operations as Certified (or Promoted); leave Sales Sandbox "
    "unendorsed. There is no API for endorsement (PLAN §6 T11).",
    "Create one report per model, named as in evals/golden/models.yaml `report` (PLAN §4.2).",
    "Check the Fabric tenant settings for Copilot and data agents (PLAN §6 T1-T5).",
    "Copy the monitoring Eventhouse query URI and database into [evidence.monitoring] (printed above when "
    "monitoring is ready; spike S2 confirms the tables).",
)


@dataclass(frozen=True)
class DeployPersona:
    key: str
    upn: str
    workspaces: tuple[str, ...]
    rls_role: str | None
    regions: tuple[str, ...]


@dataclass(frozen=True)
class DeployPlan:
    """Everything the deployment needs, resolved from settings and the golden set before any API call."""

    capacity: str
    workspaces: dict[str, str]  # certified / sandbox / results -> display name
    lakehouses: dict[str, str]  # certified / sandbox / results -> display name
    personas: tuple[DeployPersona, ...]
    daemon_app_id: str
    enable_monitoring: bool
    notebook_timeout_s: int
    models: dict[str, str]  # model display name -> workspace display name
    snapshot_cases: tuple[dict[str, str], ...]

    def describe(self) -> list[str]:
        """The plan in words, for ``--dry-run``."""
        lines = [f"capacity: {self.capacity}"]
        for role, name in self.workspaces.items():
            lines.append(f"workspace {name} ({role}) with lakehouse {self.lakehouses[role]}")
        for persona in self.personas:
            rls = f"{persona.rls_role} {list(persona.regions) or ''}".strip() if persona.rls_role else "no model role"
            lines.append(f"persona {persona.key} {persona.upn}: Viewer on {', '.join(persona.workspaces)}; {rls}")
        if self.daemon_app_id:
            lines.append(f"daemon app {self.daemon_app_id}: Viewer on certified and sandbox, Contributor on results")
        if self.enable_monitoring:
            lines.append(f"workspace monitoring on {self.workspaces['certified']} and {self.workspaces['sandbox']}")
        lines.append(f"notebooks {', '.join(NOTEBOOKS)} in {self.workspaces['certified']}, run in order")
        lines.append(f"semantic models: {', '.join(self.models)}")
        lines.append(f"expected-value snapshot: {len(self.snapshot_cases)} golden cases")
        return lines


@dataclass
class DeployResult:
    workspace_ids: dict[str, str] = field(default_factory=dict)
    lakehouse_ids: dict[str, str] = field(default_factory=dict)
    notebook_ids: dict[str, str] = field(default_factory=dict)
    dataset_ids: dict[str, str] = field(default_factory=dict)
    monitoring: dict[str, dict[str, str]] = field(default_factory=dict)
    snapshot: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    manual_steps: list[str] = field(default_factory=lambda: list(MANUAL_STEPS))


def build_plan(settings: Settings, golden: GoldenSet) -> DeployPlan:
    """Resolve the deployment from settings and the golden set; raise SetupError if something is missing."""
    fabric = settings.fabric
    if not fabric.capacity or fabric.capacity.startswith("<"):
        raise SetupError("[fabric] capacity is empty: set the capacity display name or ID in config/settings.toml")
    domain = settings.tenant.tenant_domain
    if not domain or "<" in domain:
        raise SetupError("[tenant] tenant_domain is empty: it fills the persona UPNs in personas.yaml")
    workspaces = {
        "certified": fabric.certified_workspace,
        "sandbox": fabric.sandbox_workspace,
        "results": fabric.results_workspace,
    }
    personas = tuple(
        DeployPersona(
            key=key,
            upn=persona.resolve_upn(domain),
            workspaces=tuple(persona.workspaces),
            rls_role=persona.rls_role,
            regions=tuple(persona.regions),
        )
        for key, persona in golden.personas.items()
    )
    unknown = {name for persona in personas for name in persona.workspaces} - set(workspaces.values())
    if unknown:
        raise SetupError(f"personas.yaml names workspaces that are not in [fabric]: {sorted(unknown)}")
    by_key = {persona.key: persona for persona in personas}
    for key in ("exec", "east"):
        if key not in by_key:
            raise SetupError(f"nb_03 validates as the {key!r} persona, which personas.yaml does not define")
    return DeployPlan(
        capacity=fabric.capacity,
        workspaces=workspaces,
        lakehouses={
            "certified": fabric.gold_lakehouse,
            "sandbox": fabric.sandbox_lakehouse,
            "results": fabric.results_lakehouse,
        },
        personas=personas,
        daemon_app_id=settings.apps.daemon_client_id if "0000-0000-0000" not in settings.apps.daemon_client_id else "",
        enable_monitoring=fabric.enable_monitoring,
        notebook_timeout_s=fabric.notebook_timeout_s,
        models={model.display_name: model.workspace for model in golden.models.values()},
        snapshot_cases=tuple(_snapshot_cases(golden, by_key)),
    )


def _snapshot_cases(golden: GoldenSet, personas: dict[str, DeployPersona]) -> list[dict[str, str]]:
    """Single-model answer cases with reference DAX, as nb_03's ``cases_json`` parameter."""
    cases = []
    for case in golden.cases:
        expect = case.expect
        ground_truth = expect.value or expect.table
        dax = ground_truth.reference_dax if ground_truth is not None else None
        if expect.behavior != Behavior.ANSWER or not dax or len(expect.models) != 1:
            continue  # composite and non-answer cases have no single reference query
        cases.append({
            "case_id": case.id,
            "model": golden.models[expect.models[0]].display_name,
            "persona": case.persona,
            "persona_upn": personas[case.persona].upn,  # used to query, never written to the snapshot
            "dax": dax.strip(),
        })
    return cases


class FabricDeployment:
    """Runs the plan against a tenant. ``report`` receives one line per action."""

    def __init__(
        self,
        plan: DeployPlan,
        fabric: FabricClient,
        graph: GraphClient,
        notebooks_dir: Path,
        report: Callable[[str], None] = print,
    ) -> None:
        self._plan = plan
        self._fabric = fabric
        self._graph = graph
        self._notebooks_dir = notebooks_dir
        self._report = report
        self.result = DeployResult()

    def run(self, *, run_notebooks: bool = True) -> DeployResult:
        principals = self._resolve_identities()
        capacity_id = self._capacity_id()
        for role, name in self._plan.workspaces.items():
            self.result.workspace_ids[role] = self._ensure_workspace(name, capacity_id)
        self._assign_roles(principals)
        for role, name in self._plan.lakehouses.items():
            self.result.lakehouse_ids[role] = self._ensure_lakehouse(self.result.workspace_ids[role], name)
        if self._plan.enable_monitoring:
            for role in ("certified", "sandbox"):
                self._ensure_monitoring(role)
        for name in NOTEBOOKS:
            self.result.notebook_ids[name] = self._import_notebook(name)
        if run_notebooks:
            self._run_notebook("nb_01_generate_data", self._nb01_parameters())
            self._run_notebook("nb_02_build_models", self._nb02_parameters())
            self._grant_dataset_access()
            self._run_notebook("nb_03_validate_and_snapshot", self._nb03_parameters())
            self._download_snapshot()
        else:
            self.result.warnings.append("notebooks imported but not run (--no-run): run nb_01, nb_02, nb_03 in order")
        return self.result

    # --- steps ---------------------------------------------------------------------------------

    def _resolve_identities(self) -> dict[str, tuple[str, str]]:
        """Persona key (and 'daemon') -> (object ID, principal type)."""
        principals = {p.key: (self._graph.user_id(p.upn), "User") for p in self._plan.personas}
        if self._plan.daemon_app_id:
            principals["daemon"] = (self._graph.service_principal_id(self._plan.daemon_app_id), "ServicePrincipal")
        self._report(f"identities: {len(principals)} resolved")
        return principals

    def _capacity_id(self) -> str:
        wanted = self._plan.capacity.lower()
        for capacity in self._fabric.capacities():
            if wanted in {str(capacity.get("id", "")).lower(), str(capacity.get("displayName", "")).lower()}:
                if capacity.get("state") != "Active":
                    raise SetupError(f"capacity {self._plan.capacity} is {capacity.get('state')}: resume it first")
                self._report(f"capacity: {capacity['displayName']} ({capacity.get('sku', '?')})")
                return str(capacity["id"])
        raise SetupError(
            f"capacity {self._plan.capacity!r} not found, or you are not one of its admins or contributors"
        )

    def _ensure_workspace(self, name: str, capacity_id: str) -> str:
        existing = next((w for w in self._fabric.workspaces() if w.get("displayName") == name), None)
        if existing is None:
            created = self._fabric.create_workspace(name, capacity_id, "copilot-fabriciq-evals (PLAN §4.1)")
            self._report(f"workspace {name}: created")
            return str(created["id"])
        workspace_id = str(existing["id"])
        if str(existing.get("capacityId", "")).lower() != capacity_id.lower():
            self._fabric.assign_to_capacity(workspace_id, capacity_id)
            self._report(f"workspace {name}: assigned to the capacity")
        else:
            self._report(f"workspace {name}: exists")
        return workspace_id

    def _assign_roles(self, principals: dict[str, tuple[str, str]]) -> None:
        wanted: dict[str, dict[str, str]] = {role: {} for role in self._plan.workspaces}
        by_name = {name: role for role, name in self._plan.workspaces.items()}
        for persona in self._plan.personas:
            for name in persona.workspaces:
                wanted[by_name[name]][persona.key] = "Viewer"
        if "daemon" in principals:
            wanted["certified"]["daemon"] = "Viewer"
            wanted["sandbox"]["daemon"] = "Viewer"
            wanted["results"]["daemon"] = "Contributor"
        for role, assignments in wanted.items():
            workspace_id = self.result.workspace_ids[role]
            current = {
                str(a.get("principal", {}).get("id")): str(a.get("role"))
                for a in self._fabric.role_assignments(workspace_id)
            }
            for key, workspace_role in assignments.items():
                principal_id, principal_type = principals[key]
                have = current.get(principal_id)
                if have is None:
                    self._fabric.add_role_assignment(workspace_id, principal_id, principal_type, workspace_role)
                    self._report(f"role: {key} is {workspace_role} on {self._plan.workspaces[role]}")
                elif have != workspace_role:
                    self.result.warnings.append(
                        f"{key} is {have} on {self._plan.workspaces[role]}, expected {workspace_role}"
                        + ("; row-level security does not apply above Viewer" if workspace_role == "Viewer" else "")
                    )

    def _ensure_lakehouse(self, workspace_id: str, name: str) -> str:
        lakehouses = self._fabric.items(workspace_id, "Lakehouse")
        existing = next((i for i in lakehouses if i.get("displayName") == name), None)
        if existing is not None:
            self._report(f"lakehouse {name}: exists")
            return str(existing["id"])
        created = self._fabric.create_lakehouse(workspace_id, name, "copilot-fabriciq-evals (PLAN §4.1)")
        if "id" not in created:  # some long-running creations return no result body: look it up
            created = next(i for i in self._fabric.items(workspace_id, "Lakehouse") if i.get("displayName") == name)
        self._report(f"lakehouse {name}: created")
        return str(created["id"])

    def _ensure_monitoring(self, role: str) -> None:
        """Workspace monitoring (preview API): reuse the workspace's Monitoring item or create one, then enable it."""
        workspace_id = self.result.workspace_ids[role]
        name = self._plan.workspaces[role]
        try:
            existing = next(iter(self._fabric.items(workspace_id, "Monitoring")), None)
            item = existing or self._fabric.create_monitoring(workspace_id, f"{name}-monitoring")
            if "id" not in item:
                item = next(iter(self._fabric.items(workspace_id, "Monitoring")))
            if self._fabric.enable_monitoring(workspace_id, str(item["id"])):
                self._report(f"monitoring {name}: {'on' if existing else 'created and on'}")
            else:
                self._report(f"monitoring {name}: another monitoring item already collects")
        except (HttpError, StopIteration) as error:
            self.result.warnings.append(
                f"workspace monitoring on {name} could not be turned on by API ({error}); turn it on in "
                "Workspace settings > Monitoring"
            )
            return
        eventhouse = next(iter(self._fabric.items(workspace_id, "Eventhouse")), None)
        database = next(iter(self._fabric.items(workspace_id, "KQLDatabase")), None)
        if eventhouse and database:
            self.result.monitoring[name] = {
                "eventhouse_id": str(eventhouse["id"]),
                "database": str(database["displayName"]),
            }

    def _import_notebook(self, name: str) -> str:
        workspace_id = self.result.workspace_ids["certified"]
        ipynb = (self._notebooks_dir / f"{name}.ipynb").read_text(encoding="utf-8")
        existing = next((i for i in self._fabric.items(workspace_id, "Notebook") if i.get("displayName") == name), None)
        if existing is not None:
            self._fabric.update_notebook(workspace_id, str(existing["id"]), ipynb)
            self._report(f"notebook {name}: updated")
            return str(existing["id"])
        created = self._fabric.create_notebook(workspace_id, name, ipynb, "copilot-fabriciq-evals (PLAN §4)")
        if "id" not in created:
            created = next(i for i in self._fabric.items(workspace_id, "Notebook") if i.get("displayName") == name)
        self._report(f"notebook {name}: imported")
        return str(created["id"])

    def _run_notebook(self, name: str, parameters: dict[str, tuple[object, str]]) -> None:
        workspace_id = self.result.workspace_ids["certified"]
        self._report(f"run {name}: started (this can take several minutes)")
        location, first_poll_s = self._fabric.run_notebook(
            workspace_id, self.result.notebook_ids[name], parameters, self.result.lakehouse_ids["certified"]
        )
        self._fabric.wait_for_job(location, timeout_s=self._plan.notebook_timeout_s, first_poll_s=first_poll_s)
        self._report(f"run {name}: completed")

    def _nb01_parameters(self) -> dict[str, tuple[object, str]]:
        scope = {p.upn: list(p.regions) for p in self._plan.personas if p.rls_role == "RegionScope"}
        return {
            "security_user_region_json": (json.dumps(scope), "Text"),
            "sandbox_workspace": (self._plan.workspaces["sandbox"], "Text"),
            "sandbox_lakehouse": (self._plan.lakehouses["sandbox"], "Text"),
        }

    def _nb02_parameters(self) -> dict[str, tuple[object, str]]:
        def members(role: str) -> str:
            return ",".join(p.upn for p in self._plan.personas if p.rls_role == role)

        return {
            "certified_workspace": (self._plan.workspaces["certified"], "Text"),
            "sandbox_workspace": (self._plan.workspaces["sandbox"], "Text"),
            "gold_lakehouse": (self._plan.lakehouses["certified"], "Text"),
            "sandbox_lakehouse": (self._plan.lakehouses["sandbox"], "Text"),
            "all_regions_members": (members("AllRegions"), "Text"),
            "region_scope_members": (members("RegionScope"), "Text"),
            # Allows nb_02's pinned %pip install in a non-interactive run (fabric/README.md).
            "_inlineInstallationEnabled": (True, "Boolean"),
        }

    def _nb03_parameters(self) -> dict[str, tuple[object, str]]:
        upn = {p.key: p.upn for p in self._plan.personas}
        return {
            "certified_workspace": (self._plan.workspaces["certified"], "Text"),
            "exec_upn": (upn["exec"], "Text"),
            "east_upn": (upn["east"], "Text"),
            "cases_json": (json.dumps(list(self._plan.snapshot_cases)), "Text"),
        }

    def _grant_dataset_access(self) -> None:
        by_name = {name: role for role, name in self._plan.workspaces.items()}
        for workspace_name in sorted(set(self._plan.models.values())):
            workspace_id = self.result.workspace_ids[by_name[workspace_name]]
            datasets = {str(d.get("name")): str(d.get("id")) for d in self._fabric.datasets(workspace_id)}
            for model, home in self._plan.models.items():
                if home != workspace_name:
                    continue
                if model not in datasets:
                    raise SetupError(f"semantic model {model} not found in {workspace_name}: check the nb_02 run")
                self.result.dataset_ids[model] = datasets[model]
                for persona in self._plan.personas:
                    if workspace_name in persona.workspaces:
                        self._fabric.grant_dataset_access(workspace_id, datasets[model], persona.upn)
                        self._report(f"model {model}: Read and Build for {persona.key}")

    def _download_snapshot(self) -> None:
        raw = self._fabric.read_onelake_file(
            self.result.workspace_ids["certified"], self.result.lakehouse_ids["certified"], SNAPSHOT_PATH
        )
        self.result.snapshot = json.loads(raw)
        errors = self.result.snapshot.get("errors", {}) if self.result.snapshot else {}
        for case_id, message in errors.items():
            self.result.warnings.append(f"snapshot {case_id}: {message}")
        self._report(f"snapshot: {len(self.result.snapshot.get('cases', {}))} cases" if self.result.snapshot else "")
