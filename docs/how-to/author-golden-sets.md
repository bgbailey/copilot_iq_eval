# How to Author Golden Sets (Schema v2)

Golden sets live in YAML (`version: 2`, recommended) or legacy CSV (`version: 1` backward-compatible). A strong golden set spans multiple personas, question shapes, paraphrases, and negative/abstention controls.

## Minimal `version: 2` YAML Template

```yaml
version: 2
suite: finance-core-v1
description: Certified Finance semantic model regression suite.
defaults:
  surface: fabric-iq
  gates: [value, artifact, model]
  rel_tol: 0.005

questions:
  - id: FIN-01
    question: What was net revenue in FY2025 after discounts and returns?
    paraphrases:
      - Give me FY25 net revenue net of discounts and product returns.
      - After subtracting discounts and returns, what was FY2025 net revenue?
    case_type: scalar
    expected: 11950000
    unit: currency
    rel_tol: 0.005
    expected_artifact: Finance
    expected_model: Contoso FY25 Sales Model
    decoys:
      - Finance Sandbox Draft
    reference_dax: EVALUATE ROW("NetRevenue", [Net Revenue])
    criticality: critical
    persona: finance-analyst
    intent:
      measure: headline_kpi
      date_context: FY2025
    tags: [revenue, fy25, core]
```

## Choosing the Right `case_type`

| `case_type` | Required Expectation Fields | Example Question |
|---|---|---|
| `scalar` | `expected: <number>`, `unit: currency\|percent\|bps\|count\|hours\|days` | *"What was gross margin % in FY2025?"* |
| `ranked_list` | `expect: {items: [...], top_n: 3, ordered: true}` | *"Rank the top 3 product categories by FY2025 gross revenue."* |
| `set` | `expect: {items: [...]}` | *"Which regions exceeded their FY2025 annual sales quota?"* |
| `table` | `expect: {key: region, rows: [{region: EMEA, gross_revenue: 3780000}, ...]}` | *"Provide a regional table of FY2025 gross revenue and gross margin %."* |
| `record` | `expect: {fields: {sev1_incidents: 312, mttr_hours: 6.4}}` | *"Report the FY2025 reliability summary: Sev1 incidents and MTTR hours."* |
| `direction` | `expect: {direction: up\|down\|flat}` | *"Did gross margin % trend upward, downward, or flat from Q1 to Q4 FY2025?"* |
| `citation_only` | `gates: [value, artifact]`, `expected_artifact: <name>` | *"Summarize the GPU capacity mitigation plan citing the Q3 Board Prep Deck."* |
| `abstention` | `expected: null`, `gates: [value]` | *"What are competitor engineering salary benchmarks?"* (not in model) |

## Authoring Checklist

1. **Verify every expected value from source data first.** Run your `reference_dax` (or SQL/document check) directly against the certified source before blaming Copilot for a mismatch.
2. **Include 2+ paraphrases on critical KPIs.** Business stakeholders rarely phrase questions identically; paraphrases expose brittle measure synonyms.
3. **Include decoy and abstention controls.** At least 10% of cases should test refusal on out-of-scope/PII prompts (`abstention`) or disambiguation against stale sandbox models (`decoys`).
4. **Target 30–50 questions for statistically meaningful diffs.** An 8-question suite (`contoso-smoke.yaml`) is ideal for fast smoke checks, while 40+ questions (`contoso.yaml`) narrow Wilson 95% CIs enough to detect ~10–15% routing shifts.
5. **Validate schema before running:**

   ```powershell
   python -m cfeval validate-golden data/golden/contoso.yaml
   ```

See [Golden Schema Reference](../reference/golden-schema.md) for the complete field specification.
