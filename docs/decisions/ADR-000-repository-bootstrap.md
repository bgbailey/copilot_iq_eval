# ADR-000: Repository bootstrap conventions

- **Status:** Accepted
- **Date:** 2026-11-03
- **Plan sections:** §0, §5.1, §7, §8, §10, Appendix A, Appendix B

## Context

The repository was bootstrapped from the implementation plan (docs/PLAN.md, version 1.0) before any Phase 0 spike ran. The bootstrap had to make a few choices the plan leaves open, and the repository will become public, so it must never hold tenant-specific data. This ADR records those choices so that later tasks build on them deliberately.

## Decision

1. **Tenant-agnostic repository.** Nothing that identifies a tenant is committed.
   - Persona UPNs in `evals/golden/personas.yaml` are templates (`eval.exec@{tenant_domain}`); the domain comes from `config/settings.toml`, which is gitignored.
   - `report_url` and `model_url` in `evals/golden/models.yaml` stay empty; model keys are resolved to ItemIds and URLs at run time (P2.2).
   - Spike outputs (`spikes/out/`), run outputs (`out/`) and token caches (`.cache/`) are gitignored. ADRs carry sanitised summaries.

2. **Golden-set schema additions.** PLAN §5.1 defines the case schema; the bootstrap adds only what the plan's own examples need:
   - `expect.value.composite`: the name of a Python ground-truth resolver, as an alternative to `reference_dax`, for values no single query can produce. PLAN Appendix B case X-001 computes its ground truth "by a Python composite of two reference queries (ground_truth/composite.py)".
   - `expect.table.n`, required when `match: top_n`.
   - `models.yaml` holds a `documents` section for document decoys (case field `doc_decoys`) and a `decoy` flag on models.
   - Personas carry `workspaces` (PLAN §9.5 rule 3 sends heartbeats only to workspaces the persona can access) and `purpose`.

3. **Live workflows wired but disabled.** `pr-gate.yml`, `nightly.yml` and `reconcile.yml` follow PLAN §10 but run only when the repository variable `EVALS_LIVE_ENABLED` is `true`, because they need a tenant, a self-hosted runner and commands that later phases add. `ci.yml` runs from the first commit.

4. **Action versions.** Workflows use the latest major version of each action at bootstrap time (`actions/checkout@v7`, `astral-sh/setup-uv@v10`, `actions/upload-artifact@v7`, `actions/setup-node@v7`, `azure/login@v3`). PLAN §10 asks for SHA pinning before production use; that is part of P9.1.

5. **Lockfile.** `uv.lock` is generated with `uv lock` when the repository is first created. CI installs with `--locked` when the lockfile exists and resolves fresh (with a warning) until then.

6. **Backlog as code.** Every task in PLAN §8 is data in `docs/backlog/tasks.yaml`, with the plan's text copied verbatim, and `scripts/bootstrap_github.py` creates the issues (PLAN §0 step 3). Two tasks are added because the plan describes their output but no task builds it:
   - **P0.2** Infrastructure as code: `infra/` appears in the PLAN §7 layout.
   - **P1.8** Author the full golden set: PLAN §5.2 targets 44 cases and the demo exit criteria need at least 40, while the plan seeds 10.

7. **Copilot instructions.** `.github/copilot-instructions.md` is PLAN Appendix A, unchanged. Extra guidance lives in path-specific files under `.github/instructions/`, so Appendix A stays the single repository-wide rule set.

## Consequences

- The repository can be made public without scrubbing configuration; the release checklist (docs/open-source-release.md) still requires a full history scan.
- Tasks P2.2 (online validation) and P2.4 (composite resolvers) must implement the schema additions above.
- The live workflows show as skipped until `EVALS_LIVE_ENABLED` is set; this is expected.

### Open issue found during bootstrap

PLAN §9.6.1 says '"$13M" for 12.84M fails at a 5% cap', but with the stated rule `(step / 2) / |expected| > max_display_rel` the half-step is 0.5M / 12.84M = 3.9%, which is under 5%, so that answer would pass. Either the rule should use the full display step (1M / 12.84M = 7.8%) or the example is wrong. Task P2.5 must settle this, with an ADR, before writing the numeric fixtures.

## Contracts updated

`config/contracts.yaml` created with the values documented in PLAN §9, every entry `status: documented`, and `TODO(spike-Sx)` markers where a spike must confirm a value.
