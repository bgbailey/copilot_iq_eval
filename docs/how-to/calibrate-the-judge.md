# Calibrate the LLM Judge

Layers 1–4 in `cfeval` (`value`, `artifact`, `model`, `abstention`) are 100% deterministic. Optional Layer 5 (`judge.answer_correctness` and `judge.why_consistency` in `src/cfeval/judge.py`) adds model-assisted grading for narrative accuracy and source-explanation consistency. Before trusting any LLM judge in scorecards, calibrate it against human-labelled turns and verify inter-rater agreement.

## Run Judge Calibration

`cfeval` ships with a synthetic Contoso calibration fixture (`data/judge_calibration/answers.jsonl`, 100% synthetic `@contoso.com` examples) so you can validate agreement both offline (`--mock`) and against a live judge deployment in your demo Azure subscription:

```bash
# Offline calibration check (CI gate default)
cfeval judge calibrate --mock --min-kappa 0.70

# Live calibration against your configured Azure OpenAI / Microsoft Foundry judge model
cfeval judge calibrate --dataset data/judge_calibration/answers.jsonl --min-kappa 0.70
```

*(The alias `cfeval calibrate-judge` accepts the same options.)*

If Cohen's $\kappa$ falls below `--min-kappa`, the command exits non-zero so uncalibrated judge prompts or weak model deployments are caught before scoring runs.

## Interpreting Calibration Metrics

`cfeval judge calibrate` reports four complementary metrics over the $2 \times 2$ confusion matrix comparing judge binary verdicts (`pass` / `fail`) against human labels:

| Metric | Target | What It Measures |
|---|---|---|
| **Raw agreement** | `>= 0.85` | Simple fraction of labelled pairs where judge and human agree: $(TP + TN) / N$. Can look artificially high when `90%` of calibration examples are passes. |
| **Cohen's kappa ($\kappa$)** | **`>= 0.70`** | Chance-corrected agreement: $(\text{Po} - \text{Pe}) / (1 - \text{Pe})$. Discounts agreement expected by random guessing under skewed class priors. `>= 0.70` indicates substantial agreement; `< 0.60` indicates rubric ambiguity or model mismatch. |
| **Fail-class recall** | `>= 0.80` | Fraction of true human `FAIL` turns caught by the judge. Low fail-class recall means an overly sycophantic judge rubber-stamps wrong or ungrounded answers. |
| **Pass-class precision** | `>= 0.85` | Fraction of judge `PASS` verdicts that humans also marked `PASS`. High pass-class precision ensures judge endorsements rarely mask defective explanations. |

Every scored row stamps `JudgeModel` and `JudgePromptHash` (a 16-character SHA-256 digest of the canonical system and grading prompts in `src/cfeval/judge.py`) so prompt edits are auditable across runs.

## Adding Local Labelled Pairs Safely

To calibrate against edge cases from your own domain (custom currency formatting, fiscal-calendar conventions, bilingual phrasing):

1. Create a **gitignored** JSONL file outside tracked directories (for example `runs/local_calibration_labels.jsonl` or `*.local.jsonl`):
   ```json
   {"id": "CAL-01", "question": "What was EMEA net revenue in FY2025?", "expected_answer": "$3.42M net revenue in FY2025", "expected_value": 3420000, "unit": "currency", "rel_tol": 0.005, "answer": "EMEA net revenue totaled $3.42M in FY2025 according to Core Sales.", "human_pass": true, "notes": "Scaled millions matches within display rounding"}
   {"id": "CAL-02", "question": "What was EMEA net revenue in FY2025?", "expected_answer": "$3.42M net revenue in FY2025", "expected_value": 3420000, "unit": "currency", "rel_tol": 0.005, "answer": "EMEA gross revenue was $3.71M in FY2025.", "human_pass": false, "notes": "Returned gross revenue instead of net revenue"}
   ```
2. Include at least **30–50 pairs** with roughly **30%–50% true failures** (wrong measure, wrong fiscal year, decoy source, fabricated abstention) so Cohen's $\kappa$ and fail-class recall have tight variance.
3. **Never commit tenant answers, internal UPNs, or workspace GUIDs** into `data/judge_calibration/answers.jsonl`. Only synthetic Contoso (`@contoso.com`) examples belong in version control.

## Related Pages

* [Metrics and Statistical Tests](../concepts/metrics.md)
* [Known Limitations](../concepts/limitations.md)
* [Threat Model](../responsible-use/threat-model.md)
