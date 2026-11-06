"""Settings from environment variables or a .env file."""
import os
from dataclasses import dataclass, field, fields
from pathlib import Path


def read_dotenv(path):
    """Minimal .env reader (KEY=VALUE, # comments). Returns a dict; doesn't touch os.environ."""
    values = {}
    if not path or not Path(path).exists():
        return values
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split(" #", 1)[0].strip().strip('"').strip("'")
    return values


@dataclass
class Settings:
    # Explicit operator identity/profile; never infer these from an ambient login
    tenant_id: str = ""
    tenant_label: str = ""             # optional tenant display name and domain for browser context
    auth_run_label: str = ""           # optional task/run prefix; login adds a unique suffix
    azure_subscription_id: str = ""
    azure_config_dir: str = ""
    operator_upn: str = ""
    operator_object_id: str = ""

    # Copilot Chat (delegated sign-in as the test user)
    client_id: str = ""
    test_user_upn: str = ""
    test_user_object_id: str = ""
    time_zone: str = "America/New_York"
    token_cache: str = ".cache/msal_token_cache.json"   # file path, or "keyvault"
    key_vault_url: str = ""
    token_cache_secret: str = "cfeval-msal-token-cache"

    # Run behaviour
    golden_set: str = "data/golden/golden_questions.csv"
    explain_mode: str = "followup"     # followup | inline | off
    repeats: int = 1
    pause_seconds: float = 20.0
    output_dir: str = "runs"

    # Telemetry Eventhouse (KQL database)
    eventhouse_query_uri: str = ""
    eventhouse_ingest_uri: str = ""
    eventhouse_database: str = "copilot_eval"
    eventhouse_workspace_id: str = ""
    eventhouse_database_id: str = ""  # Fabric KQL database item GUID, not its display/engine name

    # Existing app lakehouse and its SQL analytics endpoint (setup/rehearsal entrypoints)
    lakehouse_workspace_id: str = ""
    lakehouse_id: str = ""
    lakehouse_shortcut_path: str = "Tables"
    sql_endpoint_id: str = ""
    sql_endpoint_server: str = ""
    sql_endpoint_database: str = ""
    sql_schema: str = "dbo"
    sql_odbc_driver: str = "ODBC Driver 18 for SQL Server"
    demo_app_url: str = ""

    # DAX capture: workspace monitoring Eventhouse
    monitoring_query_uri: str = ""
    monitoring_database: str = ""
    monitoring_sources: str = ""      # optional JSON list of {query_uri, database}
    trace_wait_seconds: float = 300.0
    trace_poll_seconds: float = 20.0
    trace_settle_seconds: float = 40.0
    trace_user: str = ""               # defaults to test_user_upn
    # Workspace that holds the semantic models: used for the DAX watermark query and golden refresh
    semantic_model_workspace_id: str = ""

    # Option 1: Foundry model as judge
    judge_endpoint: str = ""           # https://<resource>.openai.azure.com or https://<resource>.services.ai.azure.com
    judge_deployment: str = "gpt-5-mini"
    judge_api_key: str = ""
    judge_api_key_secret: str = ""     # Key Vault secret name (used in Fabric notebooks)
    judge_gates_verdict: bool = False  # True: a judge 'incorrect' also fails the ask

    # Option 2: Foundry Evaluations
    foundry_project_endpoint: str = ""  # https://<account>.services.ai.azure.com/api/projects/<project>
    foundry_eval_deployment: str = "gpt-5-mini"
    # Fabric notebooks can't use the Azure CLI: give Foundry a service principal whose secret is in Key Vault
    foundry_sp_client_id: str = ""
    foundry_sp_secret_name: str = ""
    foundry_builtin_evaluators: bool = True  # add builtin.coherence and builtin.similarity

    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, env_file=".env", **overrides):
        """Settings from environment variables, then the .env file (the file wins), then overrides."""
        env = dict(os.environ)
        env.update(read_dotenv(env_file))
        values = {}
        for f in fields(cls):
            if f.name == "extra":
                continue
            raw = env.get(f.name.upper())
            if raw is None or raw == "":
                continue
            if f.type in ("bool", bool):
                values[f.name] = raw.strip().lower() in ("1", "true", "yes", "on")
            elif f.type in ("int", int):
                values[f.name] = int(raw)
            elif f.type in ("float", float):
                values[f.name] = float(raw)
            else:
                values[f.name] = raw
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    @property
    def effective_trace_user(self):
        return self.trace_user or self.test_user_upn

    @property
    def telemetry_enabled(self):
        return bool(self.eventhouse_query_uri and self.eventhouse_database)

    @property
    def trace_enabled(self):
        return bool(self.monitoring_sources.strip() or (self.monitoring_query_uri and self.monitoring_database))

    @property
    def judge_enabled(self):
        return bool(self.judge_endpoint and self.judge_deployment)

    @property
    def foundry_enabled(self):
        return bool(self.foundry_project_endpoint and self.foundry_eval_deployment)

    def public(self):
        """Run settings without keys, auth identity/profile details or cache locators."""
        hidden = {
            "judge_api_key", "extra", "tenant_id", "tenant_label", "auth_run_label", "client_id",
            "azure_subscription_id", "azure_config_dir", "operator_upn", "operator_object_id",
            "test_user_upn", "test_user_object_id", "token_cache", "token_cache_secret", "key_vault_url",
            "judge_api_key_secret", "foundry_sp_client_id", "foundry_sp_secret_name",
        }
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in hidden}
