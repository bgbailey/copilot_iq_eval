# AGENTS.md

Guidance for coding agents working in `copilot_iq_eval` (`cfeval` v0.2.0). The engineering roadmap is in `docs/PLAN.md`. Repository rules and invariants are in `.github/copilot-instructions.md`.

## Set up

```bash
python -m pip install -e ".[dev]"
npm --prefix app/standalone ci --no-audit --no-fund
```

## Verify

Everything below runs 100% offline with zero sign-in. Run these commands from the repository root before opening a pull request (`make check` runs the fast repo suite):

```bash
ruff check src tests tools
mypy src/cfeval
python -m pytest -m "not live" -q
python -m cfeval golden-lint
python -m cfeval calibrate-judge --mock --min-kappa 0.70
python -m cfeval run --strict --mock --profile tuned --no-publish
python tools/check_public_wording.py
python tools/check_docs_links.py
python -m cfeval kql --out kql/setup.kql
python tools/gen_app_contract.py
node app/scripts/generate-entities.mjs --metadata app/connectors/evals/metadata.example.json --out app/connectors/evals
python tools/gen_reference_docs.py --check
node app/scripts/dedupe-sample.mjs --check
git diff --exit-code kql/setup.kql app/overlay/src/eval/generated/contract.ts app/connectors/evals/metadata.example.json
npm --prefix app/standalone run typecheck
npm --prefix app/standalone test
npm --prefix app/standalone run build
```

## Boundaries

### Always

- Keep all automated tests offline (`pytest -m "not live"` must never open network connections to Microsoft Graph, Fabric, Power BI, or Microsoft Foundry). Use `--mock`, deterministic fakes, and synthetic fixtures.
- Use synthetic Contoso data (`@contoso.com`) in committed fixtures, sample data, and docs; describe environments as `"demo tenant"` and `"demo Azure subscription"`.
- Regenerate derived files (`kql/setup.kql`, `app/overlay/src/eval/generated/contract.ts`, `app/connectors/evals/*.ts`, `docs/reference/*.md`) from source (`src/cfeval/schema.py`, `cli.py`, `config.py`, `schemas/golden.schema.json`) rather than editing generated files by hand.

### Ask first

- Adding a runtime dependency to `[project].dependencies` in `pyproject.toml`.
- Removing or renaming a column in `src/cfeval/schema.py`.
- Changing the default gate policy in `config/gates.yaml`.
- Running any command against a live Microsoft 365, Fabric, Power BI, or Microsoft Foundry tenant, or starting a work item labelled `type:manual`.

### Never

- Commit tenant IDs, subscription IDs, workspace IDs, item IDs, UPNs, tokens, real answers, screenshots from a real tenant, or `.env` files.
- Commit internal project code names, meeting references, or operator-specific labels enforced by `config/wording-denylist.txt`.
- Add silent authentication fallbacks (`DefaultAzureCredential`, shared `~/.azure`, unverified cached accounts).
- Weaken, skip, or delete a test, release gate, or hygiene check to make a build pass.
- Create, overwrite, pause, or delete Fabric workspaces or capacities in library code or tests.
- Change GitHub repository settings, secrets, branch protection, or releases.

## Behaviour you cannot verify offline

1. Mark the code with `TODO(verify-live): <what to check>`.
2. Add a test marked `@pytest.mark.live`. Live tests are skipped unless `CFEVAL_LIVE=1`, and CI never sets it.
3. List each assumption in the pull request under **Unverified live behaviour**.

## Definition of done

- Every acceptance criterion in the target work item is satisfied.
- All offline verification commands pass, and the pull request shows their summary lines.
- New behaviour has offline unit/contract tests; scoring changes add cases to `tests/data/value_cases.jsonl` (or corresponding scorer test fixtures).
- Documentation and `CHANGELOG.md` are updated when behaviour, CLI flags, or schemas change.
- Each pull request stays focused on one logical work item.
