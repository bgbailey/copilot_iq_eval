# Convenience wrappers around uv. Every recipe is a plain `uv run ...` command, so on Windows you can
# run the same commands directly without make. See CONTRIBUTING.md#development-setup.

.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test validate score-sample generated check build precommit backlog-dry-run deploy-plan clean

help: ## Show the available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Create .venv with runtime and dev dependencies and install the git hooks
	uv sync
	uv run pre-commit install

lint: ## Lint with ruff
	uv run ruff check

format: ## Format with ruff and apply safe lint fixes
	uv run ruff format
	uv run ruff check --fix

typecheck: ## Type-check src/ with mypy --strict
	uv run mypy src

test: ## Run unit and contract tests with coverage
	uv run pytest --cov --cov-report=term-missing

validate: ## Validate the golden set and the evaluator definitions offline
	uv run evals validate --strict

score-sample: ## Score the sample evaluation rows on the local backend (no Azure needed)
	uv run evals score evals/evaluators/samples/eval-items.jsonl

generated: ## Check the built notebooks and Work IQ documents match their sources
	uv run python scripts/build_notebooks.py --check
	uv run python scripts/build_workiq_documents.py --check

build: ## Rebuild the notebooks and Work IQ documents from their sources
	uv run python scripts/build_notebooks.py
	uv run python scripts/build_workiq_documents.py

check: lint typecheck test validate score-sample generated ## Run everything CI runs (except the infra job)

deploy-plan: ## Print the Fabric and Work IQ deployment plans from config/settings.toml (no sign-in, no changes)
	uv run evals deploy fabric --dry-run
	uv run evals deploy workiq --dry-run

precommit: ## Run every pre-commit hook against every file
	uv run pre-commit run --all-files

backlog-dry-run: ## Preview the labels, milestones and issues the backlog would create in GitHub
	uv run python scripts/bootstrap_github.py --dry-run

clean: ## Remove caches and build outputs
	rm -rf .mypy_cache .pytest_cache .ruff_cache .coverage htmlcov build dist out
