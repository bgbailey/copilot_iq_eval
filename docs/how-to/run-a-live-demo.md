# Run a Live Demo Walkthrough

This scripted walkthrough demonstrates how `cfeval` quantifies the impact of semantic model AI-readiness improvements in a demo tenant (`contoso.com`), moving from an untuned baseline model to a governed, AI-ready model with statistically significant proof.

## Demo Narrative Overview

1. **Act 1 — Baseline run (`baseline`)**: Evaluate a clean semantic model with cryptic column names, ambiguous gross/net revenue measures, and a competing `Sales Sandbox` decoy in the workspace. Observe deterministic failures and decoy routing.
2. **Act 2 — Semantic model improvements**: Apply governed semantic model authoring practices (measure descriptions, synonyms, display folders, explicit fiscal-year filters, and certified endorsement).
3. **Act 3 — Tuned candidate run (`tuned`) & paired comparison**: Re-run the exact same golden suite, compare paired verdicts (`cfeval compare`), and review the HTML report or scorecard app.

> **Zero-tenant dry run**: You can rehearse the entire three-act flow offline in under 10 seconds using `--mock --profile baseline` and `--mock --profile tuned` before running live in your demo tenant.

## Before You Start (15 Minutes Ahead)

1. Verify your demo-tenant capacity is active and complete [Prerequisites](../get-started/prerequisites.md) (`eval.tester@contoso.com` signed in via `cfeval login`, Workspace Monitoring active).
2. Seed the Contoso star schema (`samples/contoso/README.md`) or prepare your target semantic model plus an uncertified `Sales Sandbox` decoy model.
3. Run preflight and trace probes so authentication and Eventhouse connections are warm:
   ```bash
   cfeval doctor --strict
   cfeval trace probe
   ```

## Step 1: Capture the Untuned Baseline Run

Run the suite against the initial semantic model configuration and generate the baseline report:

```bash
cfeval run \
  --golden data/golden/contoso-smoke.yaml \
  --run-id demo-baseline \
  --name "Demo Baseline"

cfeval report runs/demo-baseline --out runs/demo-baseline/report.html
```

Highlight three concrete failure modes in `runs/demo-baseline/report.html`:

* **Ambiguous measure selection (`value` gate `FAIL`)**: Copilot picks `Net Revenue` (`$11.95M`) when asked for total revenue (`$12.84M` gross) because neither measure has a business description.
* **Decoy routing (`artifact` / `model` gate `FAIL`)**: Unqualified prompts touch `Sales Sandbox` instead of `Core Sales`, exposed immediately by `SemanticModelLogs` (`RoutingEvidence = engine+citations`).
* **Missing time-intelligence context**: YoY or margin basis-point prompts fail or produce inconsistent DAX across trials.

## Step 2: Apply Semantic Model AI-Readiness Improvements

In Power BI / Microsoft Fabric on the `Core Sales` semantic model (see [Semantic model AI readiness](https://github.com/microsoft/skills-for-fabric/blob/main/skills/semantic-model-authoring/references/semantic-model-ai-readiness.md) and [Copilot settings for semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-semantic-models)):

1. **Add clear measure descriptions and synonyms** distinguishing `Gross Revenue` (default top-line revenue before discounts/returns) from `Net Revenue`.
2. **Hide technical surrogate keys and raw fact columns** so Copilot aggregates governed DAX measures instead of summing raw columns.
3. **Mark `Core Sales` as Certified / Promoted** and disable Copilot on stale `Sales Sandbox` workspaces or models (`R10`).
4. **Configure Copilot AI instructions / schema selection** documenting fiscal calendar (`FY2025`) conventions and standard KPI formulas.

## Step 3: Run the Tuned Candidate and Compare

Re-run the identical golden suite and compute the paired comparison:

```bash
cfeval run \
  --golden data/golden/contoso-smoke.yaml \
  --run-id demo-tuned \
  --name "Demo Tuned"

cfeval compare \
  --baseline runs/demo-baseline \
  --candidate runs/demo-tuned \
  --md-out runs/demo-comparison.md

cfeval gate runs/demo-tuned \
  --baseline runs/demo-baseline \
  --junit runs/demo-tuned/junit.xml \
  --summary-md runs/demo-tuned/gate-summary.md

cfeval report runs/demo-tuned --out runs/demo-tuned/report.html
```
Walk stakeholders through `runs/demo-comparison.md` and `report.html`:

* Show discordant improvements (`FAIL -> PASS`) with **zero regressions** (`PASS -> FAIL = 0`) and the exact paired McNemar $p$-value.
* Inspect the captured `QueryEnd` DAX in `FabricIqQuery` proving `Core Sales` executed cleanly (`DaxErrorCount == 0`) and `Sales Sandbox` was avoided.

## Related Pages

* [First Live Run](../get-started/first-live-run.md)
* [Compare Runs and Gate CI](./compare-runs-and-gate-ci.md)
* [Deploy the Scorecard App](./deploy-the-scorecard-app.md)
