"""Shared pytest fixtures. Unit tests never touch the network or a tenant."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    """Absolute path of the repository root."""
    return REPO_ROOT


@pytest.fixture
def golden_dir(repo_root: Path) -> Path:
    """The committed golden set."""
    return repo_root / "evals" / "golden"


@pytest.fixture
def evaluators_dir(repo_root: Path) -> Path:
    """The committed evaluators and evaluation definition, run by either backend (ADR-009)."""
    return repo_root / "evals" / "evaluators"
