---
applyTo: "fabric/**"
---

# Fabric notebooks, item definitions and KQL

- **Edit the notebook sources, never the `.ipynb` files.** Each notebook in `fabric/notebooks/` is built from `fabric/notebooks/src/nb_*.py` by `uv run python scripts/build_notebooks.py`; CI fails if they differ. Cell markers: `# %% [markdown]`, `# %% [parameters]`, `# %% [logic]` (plain Python, run by `tests/unit/test_notebooks.py` outside Fabric) and `# %%` (Spark or Fabric-only).
- Keep model definitions as data in nb_02's logic cell, and keep every golden-set `reference_dax` resolvable against them; the notebook tests check both.
- FY2025 gross revenue by region and the FY2025 Sev1 mean time to resolve are calibrated to exact figures that the Work IQ documents and nb_03 rely on (`workiq/content.yaml`, PLAN §4.4). Change them only together with `evals/golden/models.yaml`.
- Notebooks are PySpark. The first code cell is the parameter cell; every notebook is idempotent (re-running updates rather than duplicates) and contains no hard-coded workspace, Lakehouse or item IDs.
- Synthetic data uses numpy seed `20261103`. The fiscal year starts 1 July: `Fiscal Year` labels look like `FY2025`, `Fiscal Quarter` labels like `FY2025 Q2` (PLAN §4.1).
- Semantic models expose business-friendly names (`Date`, `Region`, `Product`, `Customer`, `Service`, `Sales`, `GL`, `Incident`); every measure and column has a description; technical keys are hidden; `security_user_region` stays hidden (PLAN §4.2).
- Build and change models with semantic-link-labs (`sempy_labs`); `fabric/items/` is written by Fabric Git integration, so don't hand-edit TMDL there.
- KQL files are parameterised with `{placeholders}` that `evidence/correlate.py` fills in. Keep the `eval-gt` and `eval-hb` exclusions: they keep ground-truth and heartbeat queries out of routing evidence (PLAN §9.5).
