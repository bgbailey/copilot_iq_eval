"""Unit tests for the ``evals`` command line (copilot_evals.cli)."""

from pathlib import Path

from typer.testing import CliRunner

from copilot_evals import __version__
from copilot_evals.cli import app

runner = CliRunner()


def test_version_option_prints_the_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_validate_passes_on_the_committed_definitions(golden_dir: Path, evaluators_dir: Path) -> None:
    args = ["validate", "--golden-dir", str(golden_dir), "--evaluators-dir", str(evaluators_dir), "--strict"]

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "OK" in result.output
    assert "foundry, local" in result.output


def test_validate_fails_when_golden_files_are_missing(tmp_path: Path, evaluators_dir: Path) -> None:
    result = runner.invoke(app, ["validate", "--golden-dir", str(tmp_path), "--evaluators-dir", str(evaluators_dir)])

    assert result.exit_code == 1


def test_validate_fails_when_evaluator_files_are_missing(golden_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--golden-dir", str(golden_dir), "--evaluators-dir", str(tmp_path)])

    assert result.exit_code == 1


def test_score_runs_the_sample_rows_on_the_local_backend(evaluators_dir: Path, tmp_path: Path) -> None:
    items = evaluators_dir / "samples" / "eval-items.jsonl"
    args = ["score", str(items), "--evaluators-dir", str(evaluators_dir), "--out", str(tmp_path)]

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "local backend" in result.output
    assert "routing_match" in result.output
    assert "Attempts:" in result.output
    assert (tmp_path / "evaluator_results.jsonl").read_text(encoding="utf-8").count("\n") == 7 * 6
    assert '"backend": "local"' in (tmp_path / "evaluation_run.json").read_text(encoding="utf-8")


def test_score_names_the_bad_line_of_an_invalid_items_file(evaluators_dir: Path, tmp_path: Path) -> None:
    items = tmp_path / "eval_items.jsonl"
    items.write_text('{"attempt_id": "not a row"}\n', encoding="utf-8")

    result = runner.invoke(app, ["score", str(items), "--evaluators-dir", str(evaluators_dir)])

    assert result.exit_code == 1
    assert "eval_items.jsonl:1" in result.output


def test_score_on_foundry_says_the_client_is_not_built_yet(evaluators_dir: Path) -> None:
    items = evaluators_dir / "samples" / "eval-items.jsonl"

    result = runner.invoke(app, ["score", str(items), "--backend", "foundry"])

    assert result.exit_code == 2
    assert "P2.7" in result.output


def _deploy_settings(tmp_path: Path) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[tenant]\ntenant_id = "00000000-0000-0000-0000-000000000001"\ntenant_domain = "contoso.example"\n\n'
        '[fabric]\ncapacity = "fcdemo64"\n\n'
        '[workiq.sites]\nplanning = "https://contoso.sharepoint.com/sites/eval-planning"\n'
        'all_company = "https://contoso.sharepoint.com/sites/eval-all-company"\n',
        encoding="utf-8",
    )
    return path


def test_deploy_fabric_dry_run_prints_the_plan(tmp_path: Path, golden_dir: Path) -> None:
    settings = str(_deploy_settings(tmp_path))
    args = ["deploy", "fabric", "--dry-run", "--settings", settings, "--golden-dir", str(golden_dir)]

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "persona east eval.east@contoso.example: Viewer on ws-eval-certified; RegionScope" in result.output
    assert "Dry run" in result.output


def test_deploy_fabric_without_a_capacity_fails_before_signing_in(tmp_path: Path, golden_dir: Path) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text('[tenant]\ntenant_domain = "contoso.example"\n', encoding="utf-8")

    result = runner.invoke(app, ["deploy", "fabric", "--settings", str(settings), "--golden-dir", str(golden_dir)])

    assert result.exit_code == 1
    assert "[fabric] capacity is empty" in result.output


def test_deploy_workiq_dry_run_lists_every_upload(tmp_path: Path, golden_dir: Path, repo_root: Path) -> None:
    args = [
        "deploy", "workiq", "--dry-run", "--settings", str(_deploy_settings(tmp_path)), "--golden-dir", str(golden_dir),
        "--content", str(repo_root / "workiq" / "content.yaml"),
        "--documents-dir", str(repo_root / "workiq" / "documents"),
    ]

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert result.output.count("upload ") == 3
    assert "FY2025 revenue - DRAFT.docx" in result.output
