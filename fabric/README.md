# Fabric assets

The governed semantic layer the tests run against: synthetic Contoso data, four Direct Lake semantic models (three certified, one decoy) and the KQL that turns engine logs into routing evidence. Fabric supplies the expected values and the routing evidence, and hosts the business scorecard; the evaluators decide the verdicts, run by Microsoft Foundry Evaluations or locally ([ADR-009](../docs/decisions/ADR-009-two-evaluation-backends.md)).

**Deploy it with one command:** `uv run evals deploy fabric` creates the workspaces and lakehouses, imports and runs the notebooks below, and grants the personas their access ([docs/deployment.md](../docs/deployment.md#4-deploy-the-fabric-estate)).

| Path | What it holds | Built by |
|---|---|---|
| [`notebooks/`](notebooks/README.md) | The three deployment notebooks, built from the sources in `notebooks/src/`. | P1.2, P1.3, P1.7 |
| [`items/`](items/README.md) | Item definitions exported by Fabric Git integration (TMDL, reports). | P1.5 |
| [`kql/semantic_model_logs.kql`](kql/semantic_model_logs.kql) | The routing oracle: which models a persona queried during an attempt window. | Bootstrap (PLAN §9.5) |
| [`kql/heartbeat.kql`](kql/heartbeat.kql) | Completeness check: has the attempt's heartbeat query been ingested yet? | Bootstrap (PLAN §9.5) |

## Workspaces (PLAN §4.1)

| Workspace | Contents | Monitoring | Personas (Viewer) |
|---|---|---|---|
| `ws-eval-certified` | Lakehouse `lh_gold`; the notebooks; Sales Analytics, Finance and Service Operations models and reports | Enabled | `exec`, `east` |
| `ws-eval-sandbox` | Lakehouse `lh_sandbox`; the Sales Sandbox decoy model | Enabled, so decoy hits are visible | `exec`, `noaccess` |
| `ws-eval-results` | Lakehouse `lh_eval`; a copy of each run's evaluation results, from either backend, and the scorecard | Not needed | none |

Personas are **Viewers**, because row-level security applies only to Viewers; the deployment reports a higher role rather than downgrading it.

## The data

Synthetic and seeded (`20261103`), so expected values are reproducible. The fiscal year runs July to June: FY2025 is 1 July 2024 to 30 June 2025. A few FY2025 figures are **calibrated to the cent**, so the seeded Work IQ documents can compare against them ([PLAN §4.4](../docs/PLAN.md#44-work-iq-content-joint-work-iq--fabric-iq-cases-adr-010)):

| Figure | Value | Compared with (document) |
|---|---|---|
| Gross revenue, all regions | $12,840,000.00 | target $12,500,000: beaten by 2.7% |
| Gross revenue by region | East $4,200,000 · West $3,600,000 · Central $2,940,000 · International $2,100,000 | regional targets: West misses, the others beat theirs |
| Sev1 mean time to resolve | 7.2 hours | objective 6 hours: missed |

## The models (PLAN §4.2)

| Model | Tables | Key measures | RLS |
|---|---|---|---|
| **Sales Analytics** | Date, Region, Product, Customer, Sales | Gross Revenue, Units, Orders, Avg Order Value, Gross Revenue FYTD / PY / YoY % | `AllRegions`, `RegionScope` |
| **Finance** | Date, Region, GL | Net Revenue, COGS, Gross Margin, Gross Margin %, Operating Expense, Operating Margin % | `AllRegions`, `RegionScope` |
| **Service Operations** | Date, Region, Service, Incident | Incidents, Sev1 Incidents, MTTR Hours, Impacted Customers | `AllRegions`, `RegionScope` |
| **Sales Sandbox** (decoy) | Date, Sales (to 31 March 2025, +3%) | Revenue, Units | none |

Every measure and key column has a business description, keys are hidden, and `Date` is marked as the date table. `RegionScope` filters `Region` through the hidden `security_user_region` table (one row per persona and region, written by nb_01 from `personas.yaml`). The model definitions are plain data in nb_02, and [`tests/unit/test_notebooks.py`](../tests/unit/test_notebooks.py) checks that every measure and column the golden-set DAX names exists in its target model.

Prep data for AI, endorsement and the reports have no API and stay manual ([docs/deployment.md](../docs/deployment.md#4-deploy-the-fabric-estate)).

## Troubleshooting

- **nb_02 stops because semantic-link-labs could not be installed.** Fabric can block inline `%pip install` in non-interactive runs. The deployment passes `_inlineInstallationEnabled`, which pipelines honour; if the job API does not, create a Fabric environment with the public library `semantic-link-labs==0.18.0`, attach it to nb_02, and re-run `evals deploy fabric`. Running nb_02 once by hand also works.
- **A persona's query fails while yours works.** Direct Lake over OneLake uses the querying user's identity to read the files. nb_02 therefore defaults to Direct Lake on the SQL analytics endpoint (`direct_lake_mode = "sql_endpoint"`), which workspace Viewers can read. nb_03 checks this as the `east` persona before anything depends on it.
- **nb_03 reports a calibrated figure that differs.** For all regions, the data or a measure is wrong: re-run nb_01 and nb_02. For East only, RLS is not applied as planned: check that `east` is a Viewer and a `RegionScope` member.
