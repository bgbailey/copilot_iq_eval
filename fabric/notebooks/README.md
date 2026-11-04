# Fabric notebooks

The notebooks `evals deploy fabric` imports into `ws-eval-certified` and runs in order. Conventions (from `.github/copilot-instructions.md`): the parameter cell first, idempotent, no hard-coded workspace or item IDs.

| Notebook | What it does | Task |
|---|---|---|
| [`nb_01_generate_data.ipynb`](nb_01_generate_data.ipynb) | Seeded synthetic gold tables (PLAN §4.1) in `lh_gold`, with calibrated FY2025 figures, plus the stale decoy snapshot in `lh_sandbox` and the `security_user_region` RLS table. | P1.2 |
| [`nb_02_build_models.ipynb`](nb_02_build_models.ipynb) | The four Direct Lake models with semantic-link-labs: friendly names, relationships, a marked date table, measures with descriptions, RLS roles and members. | P1.3 |
| [`nb_03_validate_and_snapshot.ipynb`](nb_03_validate_and_snapshot.ipynb) | Checks the calibrated figures as each persona (the RLS test) and snapshots every golden case's expected value to `Files/eval/expected_snapshot.json`. | P1.7 |

## Sources and builds

Each notebook is built from a Python source in [`src/`](src), where reviews and diffs are easy to read:

```bash
uv run python scripts/build_notebooks.py           # rebuild the .ipynb files after editing src/
uv run python scripts/build_notebooks.py --check   # CI: fail if a committed notebook is stale
```

Cell markers in the sources: `# %% [markdown]`, `# %% [parameters]` (tagged `parameters`, so Fabric injects run parameters after it), `# %% [logic]` (plain Python that [`tests/unit/test_notebooks.py`](../../tests/unit/test_notebooks.py) runs outside Fabric) and `# %%` (Spark or Fabric-only code).

## Parameters

`evals deploy fabric` sets these from `config/settings.toml` and `evals/golden/personas.yaml`; the defaults suit a manual run with the default names.

| Notebook | Parameter | Default | Set by the deployment to |
|---|---|---|---|
| nb_01 | `security_user_region_json` | `{}` | each `RegionScope` persona's UPN and regions |
| nb_01 | `sandbox_workspace`, `sandbox_lakehouse` | `ws-eval-sandbox`, `lh_sandbox` | `[fabric]` names |
| nb_01 | `seed`, `sales_rows`, `incident_count` | `20261103`, 500,000, 6,000 | unchanged |
| nb_02 | `certified_workspace`, `sandbox_workspace`, `gold_lakehouse`, `sandbox_lakehouse` | default names | `[fabric]` names |
| nb_02 | `all_regions_members`, `region_scope_members` | empty | persona UPNs by `rls_role` |
| nb_02 | `direct_lake_mode` | `sql_endpoint` | unchanged (see [Troubleshooting](../README.md#troubleshooting)) |
| nb_03 | `exec_upn`, `east_upn` | empty | persona UPNs |
| nb_03 | `cases_json` | `[]` | single-model `answer` cases with their reference DAX |

## Run one by hand

Open the notebook in `ws-eval-certified`, attach `lh_gold` as the default lakehouse, edit the parameters cell and select **Run all**. nb_02 and nb_03 need the parameters above; nb_01 runs with its defaults.
