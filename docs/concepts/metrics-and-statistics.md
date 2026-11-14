# Metrics and Statistical Methodology

`cfeval` combines deterministic check gates with multi-trial binomial statistics so teams can distinguish genuine grounding improvements from single-run LLM variance.

## Per-Ask Deterministic Gates

Each golden case declares which `gates` determine its overall `verdict` (`PASS` or `FAIL`):

| Gate | Question Answered | Supported Case Types |
|---|---|---|
| **`value`** | Does the answer match the expected ground truth within tolerance? | `scalar`, `ranked_list`, `set`, `table`, `record`, `direction`, `abstention`, `citation_only` (non-empty substantive answer). |
| **`artifact`** | Did the response cite or invoke the expected report, document, or tool—and avoid citing known decoys? | All case types except `abstention`. |
| **`model`** | Did engine telemetry (`SemanticModelLogs`) confirm execution against `expected_model` with zero queries to `decoy_models`? | `fabric-iq` cases evaluated at `engine+citations` tier. |
| **`judge`** *(opt-in)* | Did a calibrated LLM judge rate explanation grounding above threshold? | Advisory by default; hard gate only when `--gate-on-judge` is set. |

### Display-Aware Scalar Matching

Business answers routinely round large currency or percentage figures (`"$12.84M"` for `12,840,000`, `"41.6%"` for `41.6`, `"140 bps"` for `140`). The `scalar` scorer parses unit suffixes (`K`, `M`, `B`, `%`, `bps`, `hours`, `days`) and checks:

```
|actual - expected| <= max(abs_tol, tolerance * |expected|, display_rounding_half_ulp)
```

### Structured & Behavioral Case Types

- **`ranked_list`:** Extracts ordered items (`top_n`) and checks exact rank order when `ordered: true` (plus normalized discounted cumulative gain / overlap diagnostics).
- **`set`:** Order-insensitive membership comparison (`precision`, `recall`, `F1 == 1.0` for exact match).
- **`record` / `table`:** Keyed field or multi-row numeric/string verification using each case's `tolerance`.
- **`direction`:** Classifies directional trend language (`up`, `down`, `flat`) against `expect.direction`.
- **`abstention`:** Passes when the assistant declines to fabricate uncollected, restricted, or out-of-model facts and avoids hallucinating specific figures.

## Multi-Trial Reliability (`pass@k` vs `pass^k`)

When running `trials = k` (`--trials 3` or `--trials 5`):

- **`pass@k` (Capability Discovery):** Fraction of questions where **at least one** of `k` trials passed. High `pass@k` with low `pass^k` indicates prompt sensitivity or intermittent routing drift.
- **`pass^k` (Operational Reliability):** Fraction of questions where **all `k`** trials passed (`1 - empirical_pass_rate^k` gap highlights flakiness). Use `pass^k` for executive readiness gates.

## Confidence Intervals & Paired Run Comparison

- **Wilson 95% Score Interval:** Reported alongside every aggregate pass rate (`[ci_low, ci_high]`). Unlike normal-approximation intervals, Wilson intervals remain well-behaved near `0%`, `100%`, and moderate sample sizes (`N = 22`–`42`).
- **Paired McNemar Test (`cfeval compare`):** Compares two runs on the **exact same golden IDs** by counting discordant pairs:
  - `b` = cases passing in Run A but failing in Run B (regressions)
  - `c` = cases failing in Run A but passing in Run B (improvements)
  - Exact binomial two-sided `p`-value on `(b, c)` tells you whether `Run B` differs significantly (`p < 0.05`) from `Run A`.
- **Judge Calibration (`cfeval calibrate-judge`):** Computes **Cohen's kappa (`κ`)**, precision, recall, and confusion matrix between LLM judge verdicts and human annotations. Require `κ >= 0.70` before gating CI on judge scores.
