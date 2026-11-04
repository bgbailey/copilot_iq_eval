# Open-source release checklist

The repository starts private. Work through this list before changing its visibility to public, and keep the evidence (for example the scan output) with the release request.

## Approval and ownership

- [ ] Complete Microsoft's open-source release process for the repository, and confirm the GitHub organisation it will be published from.
- [ ] Name the maintainers: update [`.github/CODEOWNERS`](../.github/CODEOWNERS) and the support statement in [SUPPORT.md](../SUPPORT.md).
- [ ] Confirm the licence (MIT) and that the standard files are present: [LICENSE](../LICENSE), [SECURITY.md](../SECURITY.md), [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md), [SUPPORT.md](../SUPPORT.md), [CONTRIBUTING.md](../CONTRIBUTING.md) (CLA) and the Trademarks section in the [README](../README.md).

## Content review

- [ ] **Secrets**: scan the full Git history, not only the latest commit, for example with `gitleaks git` (the pre-commit hook scans new commits only). Rotate anything that was ever committed, even if it was later removed.
- [ ] **Tenant identifiers**: no tenant IDs or domains, user principal names, workspace, item or report IDs, Key Vault names or URLs containing them, in files or history. Search for GUIDs and `@` addresses and review every hit; the only expected GUIDs are placeholders: the all-zero IDs in `config/settings.example.toml`, the `00000000-0000-4000-8000-…` IDs in `evals/evaluators/samples/`, and synthetic IDs in `tests/`.
- [ ] **Customer information**: synthetic Contoso data only. No customer names, meeting notes, figures or screenshots in code, docs, fixtures, issues or pull requests that will become public.
- [ ] **Internal terminology**: [PLAN.md](PLAN.md), the [architecture diagram](architecture/README.md) and the backlog ([tasks.yaml](backlog/tasks.yaml) copies plan text, and so do the issues created from it) mention the internal demo-tenant programme ("MCAPS external tenant": PLAN title, §6 T4, §8 P9.2, §14 Q8), and the plan names its owner. Decide whether to keep or generalise these before publishing.
- [ ] **Recorded fixtures**: every file under `tests/fixtures/` is sanitised, including recorded Foundry output items.
- [ ] **Foundry and model identifiers**: no Foundry project endpoint, account name, dataset or evaluation ID, report URL or Azure OpenAI resource endpoint is committed (they belong in `config/settings.toml` and run outputs, which are gitignored).
- [ ] **Issues and pull requests**: they become public with the repository; review them for tenant identifiers and customer information.

## Repository settings

- [ ] Branch protection on `main` with required reviews and required status checks.
- [ ] Secret scanning and push protection on (available for all public repositories).
- [ ] Dependabot alerts and security updates on.
- [ ] Code scanning (CodeQL) on for Python and GitHub Actions.
- [ ] Workflow permissions default to read-only; `pr-gate.yml` never runs with secrets for pull requests from forks (it runs only on the self-hosted runner, in the `eval-demo` environment, and only when `EVALS_LIVE_ENABLED` is true). Consider required reviewers on the `eval-demo` environment.
- [ ] Every action pinned to a full commit SHA.
- [ ] Description, topics and a social preview image set.

## After publishing

- [ ] Watch the first external issues and pull requests for anything that should have been reported privately (see SECURITY.md).
- [ ] Add a release entry to [CHANGELOG.md](../CHANGELOG.md).
