"""``evals deploy``: set up a demo tenant (docs/deployment.md).

* ``evals deploy fabric``  Workspaces, lakehouses, notebooks, data, semantic models, RLS, permissions
                           and a validation run (``fabric_deploy``).
* ``evals deploy workiq``  The Work IQ documents, uploaded to their SharePoint sites (``workiq``).

Both print their plan first, accept ``--dry-run`` (no sign-in, no API call) and are safe to re-run.
Run them from the repository root after ``uv sync --extra setup``.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from copilot_evals.config import Settings, load_settings, settings_path
from copilot_evals.golden import GoldenSet, GoldenSetError, load_golden_set
from copilot_evals.setup.auth import AzureIdentityTokens
from copilot_evals.setup.fabric import FabricClient
from copilot_evals.setup.fabric_deploy import OUTPUT_DIR, DeployResult, FabricDeployment, build_plan
from copilot_evals.setup.graph import GraphClient
from copilot_evals.setup.rest import JsonHttp, SetupError
from copilot_evals.setup.workiq import WorkIQSeeder, load_content_pack, seeding_plan

DEFAULT_GOLDEN_DIR = Path("evals/golden")
DEFAULT_NOTEBOOKS_DIR = Path("fabric/notebooks")
DEFAULT_CONTENT_FILE = Path("workiq/content.yaml")
DEFAULT_DOCUMENTS_DIR = Path("workiq/documents")

console = Console()
err_console = Console(stderr=True)

deploy_app = typer.Typer(
    name="deploy",
    help="Set up a demo tenant: the Fabric estate and the Work IQ documents (docs/deployment.md).",
    no_args_is_help=True,
)


class SignInMode(StrEnum):
    DEVICE_CODE = "device-code"
    AZURE_CLI = "azure-cli"


SettingsOption = Annotated[
    Path | None,
    typer.Option("--settings", help="Settings file. Default: $COPILOT_EVALS_SETTINGS or config/settings.toml."),
]
GoldenOption = Annotated[Path, typer.Option("--golden-dir", help="Folder holding the golden set.")]
DryRunOption = Annotated[bool, typer.Option("--dry-run", help="Print the plan; no sign-in, no changes.")]
SignInOption = Annotated[
    SignInMode, typer.Option("--sign-in", help="device-code (the copilot-eval-setup app) or azure-cli (az login).")
]


def _fail(message: str, code: int = 1) -> typer.Exit:
    err_console.print(f"[bold red]error[/] {escape(message)}", soft_wrap=True)
    return typer.Exit(code=code)


def _load(settings_file: Path | None, golden_dir: Path) -> tuple[Settings, GoldenSet]:
    try:
        return load_settings(settings_file or settings_path()), load_golden_set(golden_dir)
    except FileNotFoundError as exc:
        raise _fail(f"{exc.filename} not found: cp config/settings.example.toml config/settings.toml") from exc
    except (GoldenSetError, ValueError) as exc:
        raise _fail(str(exc)) from exc


def _http(settings: Settings, sign_in: SignInMode) -> JsonHttp:
    """Sign in as the operator (azure-identity is imported only now, so --dry-run never needs it)."""
    tokens = AzureIdentityTokens(
        "device-code" if sign_in == SignInMode.DEVICE_CODE else "azure-cli",
        tenant_id=settings.tenant.tenant_id,
        client_id=settings.apps.setup_client_id,
    )
    return JsonHttp(tokens)


def _report(line: str) -> None:
    """One progress line from a deployment step."""
    console.print(f"  {escape(line)}", soft_wrap=True)


def _print_result(result: DeployResult) -> None:
    for name, details in result.monitoring.items():
        console.print(f"[bold]Monitoring[/] {name}: Eventhouse {details['eventhouse_id']}, database "
                      f"{escape(details['database'])}. Copy its query URI into [evidence.monitoring.{name}].")
    for warning in result.warnings:
        console.print(f"[yellow]warning[/] {escape(warning)}", soft_wrap=True)
    console.print("\n[bold]Still to do by hand[/] (docs/deployment.md):")
    for number, step in enumerate(result.manual_steps, start=1):
        console.print(f"  {number}. {escape(step)}", soft_wrap=True)


@deploy_app.command("fabric")
def deploy_fabric(
    settings_file: SettingsOption = None,
    golden_dir: GoldenOption = DEFAULT_GOLDEN_DIR,
    notebooks_dir: Annotated[Path, typer.Option("--notebooks-dir", help="Built notebooks.")] = DEFAULT_NOTEBOOKS_DIR,
    dry_run: DryRunOption = False,
    run: Annotated[bool, typer.Option("--run/--no-run", help="Run the notebooks after importing them.")] = True,
    sign_in: SignInOption = SignInMode.DEVICE_CODE,
) -> None:
    """Create or update the Fabric estate, build the semantic models and validate them as each persona."""
    settings, golden = _load(settings_file, golden_dir)
    try:
        plan = build_plan(settings, golden)
    except SetupError as exc:
        raise _fail(str(exc)) from exc
    console.print("[bold]Fabric deployment plan[/]")
    for line in plan.describe():
        console.print(f"  • {escape(line)}", soft_wrap=True)
    if dry_run:
        console.print("[bold]Dry run[/]: nothing was changed.")
        return

    try:
        http = _http(settings, sign_in)
        deployment = FabricDeployment(
            plan, FabricClient(http), GraphClient(http), notebooks_dir, report=_report
        )
        result = deployment.run(run_notebooks=run)
    except SetupError as exc:
        raise _fail(f"{exc}\nRe-run `evals deploy fabric` after fixing it; finished steps are skipped.") from exc

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in vars(result).items() if key != "snapshot"}
    (OUTPUT_DIR / "fabric-deployment.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if result.snapshot is not None:
        (OUTPUT_DIR / "expected_snapshot.json").write_text(json.dumps(result.snapshot, indent=2), encoding="utf-8")
    console.print(f"[bold green]Fabric deployed.[/] IDs and the snapshot are in {OUTPUT_DIR.as_posix()}/")
    _print_result(result)


@deploy_app.command("workiq")
def deploy_workiq(
    settings_file: SettingsOption = None,
    golden_dir: GoldenOption = DEFAULT_GOLDEN_DIR,
    content_file: Annotated[Path, typer.Option("--content", help="The content pack.")] = DEFAULT_CONTENT_FILE,
    documents_dir: Annotated[Path, typer.Option("--documents-dir", help="Built .docx files.")] = DEFAULT_DOCUMENTS_DIR,
    dry_run: DryRunOption = False,
    verify: Annotated[bool, typer.Option("--verify", help="Only check that the uploaded files are current.")] = False,
    sign_in: SignInOption = SignInMode.DEVICE_CODE,
) -> None:
    """Upload the Work IQ documents to their SharePoint sites (workiq/content.yaml, PLAN §4.4)."""
    settings, golden = _load(settings_file, golden_dir)
    try:
        pack = load_content_pack(content_file, golden)
        sites = {key: url for key, url in settings.workiq.sites.items() if "<" not in url}
        if dry_run:
            console.print("[bold]Work IQ seeding plan[/]")
            for line in seeding_plan(pack, golden, sites, documents_dir):
                console.print(f"  • {escape(line)}", soft_wrap=True)
            console.print("[bold]Dry run[/]: nothing was changed.")
            return
        seeder = WorkIQSeeder(
            GraphClient(_http(settings, sign_in)), pack, golden, sites, documents_dir, report=_report
        )
        if verify:
            problems = seeder.verify()
            for problem in problems:
                console.print(f"[red]problem[/] {escape(problem)}", soft_wrap=True)
            if problems:
                raise typer.Exit(code=1)
            console.print("[bold green]All Work IQ documents are uploaded and current.[/]")
            return
        seeded = seeder.seed()
    except SetupError as exc:
        raise _fail(str(exc)) from exc

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "workiq-documents.json").write_text(json.dumps([vars(d) for d in seeded], indent=2), encoding="utf-8")
    listing = f"{OUTPUT_DIR.as_posix()}/workiq-documents.json"
    console.print(f"[bold green]{len(seeded)} documents uploaded.[/] URLs are in {listing}")
    console.print(
        "Copilot finds new documents once the Microsoft 365 semantic index has processed them. Allow up to a "
        "day before running the joint cases; spike S8 measures the delay (spikes/README.md)."
    )
