"""Harness settings: non-secret, tenant-specific values loaded from ``config/settings.toml``.

Copy ``config/settings.example.toml`` to ``config/settings.toml`` (gitignored) and fill it in. The
path can be overridden with the ``COPILOT_EVALS_SETTINGS`` environment variable.

What does *not* belong here:

* Secrets. Token caches and the daemon certificate live in Azure Key Vault (PLAN §11).
* API contracts. Endpoints, scopes, headers and field names live in ``config/contracts.yaml`` and
  are confirmed by the Phase 0 spikes (PLAN §0 step 5).
* Evaluation logic. Every check is an evaluator defined in ``evals/evaluators/``; this file only
  chooses where the evaluators run (``[evaluation] backend``).

Every section has defaults taken from the plan, so a partial file is valid. Unknown keys are
rejected, so a typo fails fast instead of being silently ignored.
"""

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SETTINGS_PATH = Path("config/settings.toml")
SETTINGS_ENV_VAR = "COPILOT_EVALS_SETTINGS"


class _Section(BaseModel):
    """Base class for a settings section: unknown keys are errors, values are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TenantSettings(_Section):
    """The Microsoft Entra ID tenant that hosts the demo."""

    tenant_id: str = ""
    tenant_domain: str = ""  # fills the {tenant_domain} placeholder in personas.yaml


class AzureSettings(_Section):
    """Azure resources used by the harness (PLAN §6 T5)."""

    subscription_id: str = ""
    key_vault_url: str = ""


class AppSettings(_Section):
    """Entra ID app registrations (PLAN §11). Client IDs are not secrets; certificates stay in Key Vault."""

    public_client_id: str = ""  # copilot-eval-public: delegated persona tokens
    daemon_client_id: str = ""  # copilot-eval-daemon: app-only telemetry and results access
    daemon_certificate_name: str = "copilot-eval-daemon"  # certificate name in Key Vault
    setup_client_id: str = ""  # copilot-eval-setup: delegated, signs in the operator for `evals deploy`


class FabricSettings(_Section):
    """Fabric capacity, workspaces and lakehouses (PLAN §4.1, §9.8). `evals deploy fabric` creates them."""

    capacity: str = ""  # display name or ID of the capacity that hosts the workspaces
    certified_workspace: str = "ws-eval-certified"
    sandbox_workspace: str = "ws-eval-sandbox"
    results_workspace: str = "ws-eval-results"
    gold_lakehouse: str = "lh_gold"  # in the certified workspace: the tables behind the certified models
    sandbox_lakehouse: str = "lh_sandbox"  # in the sandbox workspace: the stale decoy copy
    results_lakehouse: str = "lh_eval"  # in the results workspace: the evaluation results store
    enable_monitoring: bool = True  # workspace monitoring on the certified and sandbox workspaces (PLAN §9.5)
    notebook_timeout_s: int = Field(default=3600, ge=60)  # per notebook run during deployment


class WorkIQSettings(_Section):
    """SharePoint sites for the Work IQ content pack (workiq/content.yaml, PLAN §4.4)."""

    # Content-pack site key -> site URL, for example planning = "https://contoso.sharepoint.com/sites/eval-planning".
    sites: dict[str, str] = Field(default_factory=dict)


class MonitoringEventhouse(_Section):
    """Workspace-monitoring Eventhouse that receives a workspace's ``SemanticModelLogs`` (PLAN §9.5)."""

    query_uri: str = ""
    database: str = ""


class EvidenceSettings(_Section):
    """Engine-log correlation (PLAN §9.5). Monitoring Eventhouses are keyed by workspace name."""

    max_wait_s: int = Field(default=900, ge=0)
    poll_interval_s: int = Field(default=20, ge=1)
    window_before_s: int = Field(default=5, ge=0)
    window_after_s: int = Field(default=30, ge=0)
    monitoring: dict[str, MonitoringEventhouse] = Field(default_factory=dict)


class EvaluationSettings(_Section):
    """Where the evaluators in ``evals/evaluators/`` run (ADR-009, PLAN §9.11, §9.12).

    ``foundry`` runs them in Microsoft Foundry Evaluations; ``local`` runs them in the harness process
    with no Foundry project. ``evals run --backend`` overrides this for one run.
    """

    backend: Literal["foundry", "local"] = "foundry"


class FoundrySettings(_Section):
    """Microsoft Foundry project for the Foundry backend (ADR-007, PLAN §9.11).

    Used only when ``evaluation.backend`` is ``foundry``. The project hosts the evaluator catalog,
    the evaluation runs and their results, and a report page per run.
    """

    endpoint: str = ""
    judge_deployment: str = "gpt-5-mini"  # AI judge, extraction step, and deployment_name for code-based evaluators
    eval_name_prefix: str = "copilot-fabriciq-evals"
    dataset_name_prefix: str = "copilot-fabriciq-evals"
    poll_interval_s: int = Field(default=10, ge=1)
    run_timeout_s: int = Field(default=1800, ge=60)


class AzureOpenAISettings(_Section):
    """Model deployments called directly through the Azure OpenAI v1 API (PLAN §9.3.1, §9.12).

    The L1 reference orchestrator uses them on both backends. The local backend also uses the judge
    deployment for the AI judge and the extraction step. The endpoint can be an Azure OpenAI or a
    Microsoft Foundry resource; sign-in uses Microsoft Entra ID (config/contracts.yaml: azure_openai_v1).
    """

    endpoint: str = ""  # https://<resource>.openai.azure.com/openai/v1/
    orchestrator_model: str = "gpt-5-mini"  # L1 reference orchestrator (PLAN §9.3.1)
    max_tool_calls: int = Field(default=12, ge=1)
    judge_model: str = "gpt-5-mini"  # AI judge and extraction step on the local backend
    judge_max_workers: int = Field(default=8, ge=1)  # rows scored in parallel by the local backend
    timeout_s: int = Field(default=120, ge=1)


class AgentSettings(_Section):
    """The declarative agent driven by the Agent Evaluations CLI (PLAN §9.3.2)."""

    m365_title_id: str = ""
    m365_agent_id: str = ""
    cli_timeout_s: int = Field(default=600, ge=1)


class ChatApiSettings(_Section):
    """Microsoft 365 Copilot Chat API adapter (PLAN §9.3.3)."""

    time_zone: str = "America/New_York"
    max_requests_per_second: float = Field(default=1.0, gt=0)
    read_timeout_s: int = Field(default=180, ge=1)


class AlertSettings(_Section):
    """Teams alerting when a gate fails (P8.3). Holds the Key Vault secret *name*, never the URL."""

    teams_webhook_keyvault_name: str | None = None


class Settings(_Section):
    """All harness settings. Sections map one-to-one to the tables in ``settings.example.toml``."""

    tenant: TenantSettings = Field(default_factory=TenantSettings)
    azure: AzureSettings = Field(default_factory=AzureSettings)
    apps: AppSettings = Field(default_factory=AppSettings)
    fabric: FabricSettings = Field(default_factory=FabricSettings)
    workiq: WorkIQSettings = Field(default_factory=WorkIQSettings)
    evidence: EvidenceSettings = Field(default_factory=EvidenceSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)
    foundry: FoundrySettings = Field(default_factory=FoundrySettings)
    azure_openai: AzureOpenAISettings = Field(default_factory=AzureOpenAISettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    chat_api: ChatApiSettings = Field(default_factory=ChatApiSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)


def settings_path() -> Path:
    """Return the settings file path: ``$COPILOT_EVALS_SETTINGS`` if set, else ``config/settings.toml``."""
    override = os.environ.get(SETTINGS_ENV_VAR)
    return Path(override) if override else DEFAULT_SETTINGS_PATH


def load_settings(path: Path | None = None) -> Settings:
    """Load and validate settings from a TOML file.

    Args:
        path: Settings file to read. Defaults to ``settings_path()``.

    Returns:
        The validated settings.

    Raises:
        FileNotFoundError: The settings file does not exist.
        pydantic.ValidationError: The file has unknown keys or invalid values.
    """
    with (path or settings_path()).open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    return Settings.model_validate(data)
