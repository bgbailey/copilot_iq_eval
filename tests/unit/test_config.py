"""Unit tests for settings loading (copilot_evals.config)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from copilot_evals.config import SETTINGS_ENV_VAR, load_settings, settings_path


def test_example_settings_file_is_valid(repo_root: Path) -> None:
    settings = load_settings(repo_root / "config" / "settings.example.toml")

    assert settings.fabric.certified_workspace == "ws-eval-certified"
    assert settings.evidence.max_wait_s == 900
    assert "ws-eval-sandbox" in settings.evidence.monitoring
    assert settings.evaluation.backend == "foundry"
    assert settings.fabric.gold_lakehouse == "lh_gold"
    assert set(settings.workiq.sites) == {"planning", "all_company"}


def test_deploy_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[fabric]\ncapacity = "fcdemo64"\nenable_monitoring = false\n\n'
        '[workiq.sites]\nplanning = "https://contoso.sharepoint.com/sites/eval-planning"\n',
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.fabric.capacity == "fcdemo64"
    assert settings.fabric.enable_monitoring is False
    assert settings.fabric.notebook_timeout_s == 3600
    assert settings.workiq.sites == {"planning": "https://contoso.sharepoint.com/sites/eval-planning"}


def test_partial_settings_use_plan_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text('[tenant]\ntenant_domain = "contoso.example"\n', encoding="utf-8")

    settings = load_settings(path)

    assert settings.tenant.tenant_domain == "contoso.example"
    assert settings.chat_api.time_zone == "America/New_York"
    assert settings.azure_openai.max_tool_calls == 12
    assert settings.evaluation.backend == "foundry"


@pytest.mark.parametrize("backend", ["foundry", "local"])
def test_either_evaluation_backend_can_be_selected(tmp_path: Path, backend: str) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(f'[evaluation]\nbackend = "{backend}"\n', encoding="utf-8")

    assert load_settings(path).evaluation.backend == backend


def test_unknown_evaluation_backend_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text('[evaluation]\nbackend = "promptfoo"\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="backend"):
        load_settings(path)


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[fabric]\ncertified_workspce = \"typo\"\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="certified_workspce"):
        load_settings(path)


def test_settings_path_honours_environment_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "custom.toml"
    monkeypatch.setenv(SETTINGS_ENV_VAR, str(override))

    assert settings_path() == override
