# Contributing

Contributions are welcome across targets, deterministic scorers, statistical analyses, golden-set tooling,
documentation, and the React scorecard overlay.

By participating in this project, you agree to abide by the [Code of Conduct](./CODE_OF_CONDUCT.md).

## Offline Development Setup

All routine development, testing, linting, and scorecard verification run **100% offline** against synthetic
Contoso fixtures and the simulated tenant. No cloud sign-in, Microsoft Graph access, Fabric capacity, or
Microsoft Foundry endpoint is required.

Prerequisites:

* **Python 3.11 or 3.12**
* **Node.js 22+** (CI builds and tests with Node 24 LTS)

```bash
git clone https://github.com/bgbailey/copilot_iq_eval
cd copilot_iq_eval

# Python package + dev toolchain
python -m pip install --upgrade pip build
pip install -e ".[dev]"

# Standalone React scorecard toolchain
npm --prefix app/standalone ci
```

If you use VS Code Dev Containers or GitHub Codespaces, open the repository directly—`.devcontainer/devcontainer.json`
provisions Python 3.12, Node.js 22, and all offline dependencies automatically.

## Verification Gates

Run the full offline verification suite before opening a pull request (`make verify`, or the individual commands below):

```bash
# Python lint, static types, unit/contract/e2e tests, golden-suite lint, and judge calibration
ruff check src tests tools
mypy src/cfeval
pytest --cov=cfeval --cov-report=term-missing
python -m cfeval golden-lint
python -m cfeval calibrate-judge --mock --min-kappa 0.70

# Repository hygiene, documentation links, and generated reference docs
python tools/check_public_wording.py
python tools/check_docs_links.py
python tools/gen_reference_docs.py --check

# Scorecard sample deduplication, node:test suites, TypeScript check, and Vite build
node app/scripts/dedupe-sample.mjs --check
npm --prefix app/standalone test
npm --prefix app/standalone run typecheck
npm --prefix app/standalone run build
```

Optional pre-commit hooks can be enabled locally with `pre-commit install` (see `.pre-commit-config.yaml`).

## Architecture & Ground Rules

1. **Zero tenant secrets or real customer data.** Commit synthetic Contoso examples only (`contoso.com` / synthetic
   identifiers). Never include real tenant IDs, workspace GUIDs from live tenants, user emails, tokens, or real
   organization answers in code, fixtures, issues, or pull requests.
2. **Offline by default.** Unit, contract, and end-to-end tests in CI must never call external endpoints. Live tenant
   validation tests must be marked `@pytest.mark.live` so they are skipped unless `CFEVAL_LIVE=1` is explicitly set.
3. **Honest status semantics.** Incomplete or missing evidence is `INCONCLUSIVE`; failed execution is `ERROR`. Neither
   may ever be coerced into `PASS`.
4. **Standard-library scorers.** Keep `src/cfeval/scorers.py` and `src/cfeval/stats.py` free of third-party runtime
   dependencies so deterministic evaluators remain portable into restricted execution sandboxes (including Azure AI
   Foundry custom code evaluators under the 256 KB limit).
5. **Pure scorecard logic.** Keep `app/overlay/src/eval/metrics.ts`, `normalize.ts`, and `format.ts` free of browser or
   network side effects and covered by `app/standalone/tests/*.test.mjs`.
6. **Single telemetry schema source.** When changing tables or columns in `src/cfeval/schema.py` (additive changes only
   for OneLake compatibility), regenerate all derived artifacts and commit them together:
   * `python tools/gen_app_contract.py`
   * `python -m cfeval kql --out kql/setup.kql`
   * `python tools/gen_reference_docs.py`
   * `node app/scripts/generate-entities.mjs --metadata app/connectors/evals/metadata.example.json --out app/connectors/evals`

## Adding Targets & Authoring Golden Suites

* **New evaluation targets:** Implement the `Target` protocol in `src/cfeval/targets/` (such as `copilot-chat`,
  `transcript-import`, `mcp-agent`, or `fabric-data-agent`), register the target identifier, and add offline contract
  tests using deterministic fakes or recorded synthetic transcripts. Never fabricate undocumented upstream API fields.
* **Golden suites & personas:** Author cases in YAML conforming to `schemas/golden.schema.json` (see
  `data/golden/contoso.yaml` and `data/golden/contoso-work.yaml`). Define clear `intent`, `expectation` (including
  reference DAX and tolerances for numeric checks), `routing` targets/decoys, and optional persona keys from
  `config/personas.yaml`. Validate with `python -m cfeval golden-lint`.

## Versioning & Changelog

This project follows [Semantic Versioning](https://semver.org/) and documents notable changes in
[CHANGELOG.md](./CHANGELOG.md) using the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

## Pull Request Checklist

* [ ] Focused change with unit/contract tests covering new behavior and edge cases (`pytest` and `npm test` pass).
* [ ] `ruff check src tests tools`, `mypy src/cfeval`, and `npm --prefix app/standalone run typecheck` pass cleanly.
* [ ] `python -m cfeval golden-lint` and `node app/scripts/dedupe-sample.mjs --check` exit `0`.
* [ ] `python tools/check_public_wording.py`, `python tools/check_docs_links.py`, and `python tools/gen_reference_docs.py --check` exit `0`.
* [ ] Zero tenant IDs, real user identities, credentials, or non-synthetic answers appear anywhere in the diff.
* [ ] Documentation and `CHANGELOG.md` are updated if CLI flags, schema columns, or scoring semantics changed.

