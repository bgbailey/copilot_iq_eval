# Author a Golden Set

A golden set (called a **test set** in Microsoft's evaluation guidance) defines the business prompts, ground-truth answers, numeric tolerances, certified artifacts, and decoy guardrails that `cfeval` evaluates on every run.

## Suite Sizing Guidance

Align your golden suite size to your deployment stage ([Agent evaluation overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluation-overview)):

| Stage | Recommended Size | Composition Guidance |
|---|---|---|
| **Prototype / Smoke** | **20 – 50** test cases | Core KPIs across primary semantic models, 2–4 decoy traps, and 3–5 abstention/clarification checks (plus an 8-case subset for rapid smoke checks). |
| **Pre-production** | **50 – 100** test cases | Add YoY/QoQ time intelligence, ratios/margins (`%` and `bps`), ranked lists, multi-filter slices, persona variations, and unstructured Work IQ prompts. |
| **Production gate** | **100+** test cases | Stratified coverage across every certified semantic model, paraphrase pairs, historical regression cases, and critical executive questions (`criticality: critical`). |

## Authoring Test Cases in v2 YAML

Golden suites use `version: 2` YAML validated against [`schemas/golden.schema.json`](../../schemas/golden.schema.json) (see [Golden Schema Reference](../reference/golden-schema.md) and [`data/golden/contoso.yaml`](../../data/golden/contoso.yaml)):

```yaml
version: 2
suite: contoso-sales-eval
defaults:
  surface: copilot-chat
  gates: [value, artifact, model]
  rel_tol: 0.005
  display_tol: 0.01

questions:
  - id: Q01
    question: "Using the Core Sales report, what was Contoso total gross revenue in FY2025?"
    case_type: scalar
    category: named-source
    criticality: critical
    persona: finance-analyst
    intent:
      measure: Gross Revenue
      grouping: Total
      date_context: FY2025
      filters: []
    expected: 12840000
    unit: currency
    currency: USD
    rel_tol: 0.005
    abs_tol: 0
    display_tol: 0.01
    expected_artifact: Core Sales
    expected_model: Core Sales
    decoys:
      - Sales Sandbox
      - Legacy FY24 Copy
    reference_dax: |
      EVALUATE
      ROW(
        "ExpectedValue",
        CALCULATE([Gross Revenue], dim_date[fiscal_year] = "FY2025")
      )
```

Follow the [Power BI Copilot prompt structure](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-ask-data-question): state the **measure**, **grouping**, **date context**, and **filters** explicitly on deterministic cases, and use separate `clarification` cases to test underspecified prompts.

## Choosing Single-Cell `reference_dax`

Instead of hand-maintaining static numbers when demo-tenant data refreshes, attach a `reference_dax` query that returns a **single row and single scalar value** via `EVALUATE ROW("ExpectedValue", ...)`:

* Reference canonical model measures (`[Gross Revenue]`, `[Gross Margin %]`) rather than duplicating raw column arithmetic so ground truth reflects your semantic model's governed business logic.
* Refresh expected values directly from the live semantic model via Power BI `executeQueries`:
  ```bash
  cfeval golden-refresh --golden data/golden/custom.yaml
  ```
* Keep `reference_dax` deterministic and free of `NOW()` / `TODAY()` unless paired with an explicit `--as-of` anchor.

## Setting `rel_tol`, `abs_tol`, and `display_tol`

`cfeval` distinguishes exact numeric precision from executive display rounding (`src/cfeval/scorers.py`):

* **`rel_tol`** *(default `0.005` = `0.5%`)*: Allowed relative difference `|actual - expected| <= rel_tol * |expected|` on unscaled numbers. Use `0.001`–`0.005` for currency/counts.
* **`abs_tol`** *(default `0.0`)*: Allowed absolute difference in target units—essential near zero or on percentage/basis-point measures (for example `abs_tol: 0.001` for `0.1` percentage points on `unit: percent`, or `abs_tol: 1.0` on `unit: bps`).
* **`display_tol`** *(default `0.01` = `1.0%`)*: Caps unit-in-the-last-place (`0.5 * ulp`) rounding when Copilot formats `$12,840,000` as `$12.8M` (`ulp = 100,000`, half-ULP = `50,000 <= 1%` of `12.84M` -> `MatchKind = display_rounded`). Set `display_tol: 0` when exact unrounded figures are mandatory.

## Adding Decoys, Refusals (`abstention`), and Clarifications

A balanced suite tests **restraint and routing**, not just happy-path lookups:

* **Decoys (`decoys`)**: List stale sandboxes, personal copies, or draft decks (such as `Sales Sandbox` or `Draft Pricing v0.docx`). If Copilot cites a decoy or `SemanticModelLogs` shows a `QueryEnd` against a decoy model, `DecoyAvoided` fails (`Verdict = FAIL`) even if the number happens to match.
* **Refusals (`case_type: abstention`)**: Ask for data absent from governed sources (competitor salaries, uncollected PII, unannounced M&A). Set `expected: null` and `gates: [value]`. Stating fabricated figures triggers `hallucinated_on_abstention` (`FAIL`).
* **Clarifications (`case_type: clarification`)**: Ask an intentionally ambiguous prompt (for example *"What was margin last quarter?"* when both Gross Margin and Operating Margin exist without a calendar vs. fiscal qualifier) to verify the target asks a clarifying question (`clarification_verified`).

## Scaffolding, Validating, and Linting

Use the golden-set CLI commands before every run or pull request:

```bash
# Scaffold a starter v2 YAML golden set
cfeval golden scaffold --out data/golden/my-suite.yaml

# Validate JSON Schema conformance against schemas/golden.schema.json
cfeval golden validate data/golden/my-suite.yaml

# Run semantic lint checks (unique IDs, valid tolerances, non-contradictory gates, decoy overlap)
cfeval golden lint data/golden/my-suite.yaml
```

*(The top-level alias `cfeval golden-lint --golden data/golden/my-suite.yaml` runs schema + lint checks in one step.)*

## Related Pages

* [Golden Schema Reference](../reference/golden-schema.md)
* [Metrics and Statistical Tests](../concepts/metrics.md)
* [Use with the Evaluations CLI](./use-with-the-evaluations-cli.md)
