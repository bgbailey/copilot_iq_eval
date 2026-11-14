PYTHON ?= python
NPM ?= npm

.PHONY: install lint typecheck test app-test docs demo-data verify check

install:
	$(PYTHON) -m pip install --upgrade pip build
	$(PYTHON) -m pip install -e ".[dev]"
	$(NPM) --prefix app/standalone ci

lint:
	ruff check src tests tools
	ruff format --check src tests tools
	$(PYTHON) -m cfeval golden-lint
	$(PYTHON) tools/check_public_wording.py
	node app/scripts/dedupe-sample.mjs --check

typecheck:
	mypy src/cfeval
	$(NPM) --prefix app/standalone run typecheck

test:
	pytest -m "not live" --cov=cfeval --cov-report=term-missing

app-test:
	node app/scripts/dedupe-sample.mjs --check
	$(NPM) --prefix app/standalone test
	$(NPM) --prefix app/standalone run typecheck
	$(NPM) --prefix app/standalone run build

docs:
	$(PYTHON) tools/gen_reference_docs.py --check
	$(PYTHON) tools/check_docs_links.py

demo-data:
	$(PYTHON) -m cfeval demo-data --as-of 2026-11-13T12:00:00Z --app-json app/overlay/public/sample-data/evals.json
	node app/scripts/dedupe-sample.mjs --check

check:
	ruff check src tests tools
	ruff format --check src tests tools
	mypy src/cfeval
	pytest -m "not live" --cov=cfeval --cov-report=term-missing
	$(PYTHON) -m cfeval golden-lint
	$(PYTHON) tools/check_public_wording.py
	$(PYTHON) tools/check_docs_links.py
	$(PYTHON) tools/gen_reference_docs.py --check
	node app/scripts/dedupe-sample.mjs --check

verify: check app-test
	$(PYTHON) -m cfeval calibrate-judge --mock --min-kappa 0.70
