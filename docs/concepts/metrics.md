# Metrics and Statistical Tests

`cfeval` computes all accuracy, reliability, confidence-interval, and paired-comparison statistics using pure Python standard-library functions (`src/cfeval/stats.py` and `src/cfeval/scorers.py`) mirrored identically in TypeScript (`app/overlay/src/eval/metrics.ts`).

## Single-Trial Accuracy (`pass@1`) and Multi-Trial Consistency (`pass^k`)

LLM-backed orchestrators are non-deterministic: a question that passes once may drift on a second attempt if Copilot selects an alternate measure or phrasing. When running $n$ trials per question (`--trials n`) with $c$ trials achieving `Verdict == "PASS"` and target horizon $k$:

* **`pass@k` (`pass_at_k(n, c, k)`)** — unbiased estimator of the probability that **at least one** of $k$ attempts passes (with $k_{\text{eff}} = \min(k, n)$):
  $$\text{pass@}k = 1 - \frac{\binom{n - c}{k_{\text{eff}}}}{\binom{n}{k_{\text{eff}}}}$$
  For $k = 1$, $\text{pass@1} = \frac{c}{n}$, measuring expected first-try user accuracy.
* **`pass^k` (`pass_pow_k(n, c, k)`)** — reliability estimator of the probability that **all $k$ independent trials pass**:
  $$\text{pass}^k = \left(\frac{c}{n}\right)^k$$
  A question passing `2` of `3` trials has $\text{pass@1} = 66.7\%$ but $\text{pass}^3 = 29.6\%$. High-stakes executive and finance scorecards should gate on both `pass@1` and `pass^3` (plus numeric value consistency across trials).

Suite-level `pass@1` and `pass^k` are the unweighted means across all $N$ questions in the golden suite (`INCONCLUSIVE` and `ERROR` count as non-passes, never excluded from $n$ or $N$).

## Wilson 95% Score Confidence Interval

Normal Wald intervals ($\hat{p} \pm z\sqrt{\hat{p}(1-\hat{p})/N}$) collapse to zero width at $0\%$ or $100\%$ and overshoot $[0, 1]$ on typical benchmark sizes ($N = 20\text{--}100$). `cfeval` reports two-sided **Wilson 95% score intervals** ($z = 1.959964$) on pass rates:

$$\frac{\hat{p} + \frac{z^2}{2N} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{N} + \frac{z^2}{4N^2}}}{1 + \frac{z^2}{N}}$$

For example, `8 / 8` passes on a smoke suite yields `[67.6%, 100.0%]` rather than a misleading `100% ± 0%`, making sample-size uncertainty visible in every CLI summary, HTML report, and scorecard header.

## Exact Paired McNemar Test (`cfeval compare`)

Comparing two independent pass rates ignores question-level pairing (easy questions pass in both runs; hard questions fail in both). `cfeval compare --baseline <dirA> --candidate <dirB>` pairs verdicts by `QuestionId` and counts the $2 \times 2$ contingency table:

* $a$: baseline `PASS` $\to$ candidate `PASS`
* $b$: baseline `PASS` $\to$ candidate `FAIL` *(regressions)*
* $c$: baseline `FAIL` $\to$ candidate `PASS` *(improvements)*
* $d$: baseline `FAIL` $\to$ candidate `FAIL`

Using discordant pairs $n_d = b + c$ and $m = \min(b, c)$, `mcnemar_exact_p(b, c)` computes the exact two-sided binomial $p$-value:

$$p = \min\!\left(1,\; \frac{2 \sum_{i=0}^{m} \binom{n_d}{i}}{2^{n_d}}\right)$$

An improvement from `50%` (`21/42`) to `81%` (`34/42`) with `c = 13` improvements and `b = 0` regressions yields $p = 0.00024$, providing statistically rigorous proof that semantic model tuning (descriptions, synonyms, verified measures) improved accuracy without regressions.

## Deterministic Value `MatchKind` Taxonomy

`src/cfeval/scorers.py` records why each `value` check passed, failed, or stayed inconclusive via `MatchKind`:

| `MatchKind` | Verdict | When Applied |
|---|---|---|
| `exact_match` | `PASS` | Extracted scalar equals `expected` within floating-point epsilon **or** within configured exact tolerance `max(abs_tol, |expected| * rel_tol)`. |
| `display_rounded` | `PASS` | Answer uses human display scaling or coarse percentage formatting (for example `$12.8M` for `12,840,000`, where unit-in-the-last-place `ulp = 100,000`), and `|actual - expected| <= min(0.5 * ulp, |expected| * display_tol)`. |
| `ranked_list_match` / `set_match` / `table_match` / `record_match` / `direction_match` / `categorical_match` / `facts_match` | `PASS` | Structured v2 expectation matched all required items, order, table cells, record fields, or trend direction with zero forbidden items. |
| `abstention_verified` / `clarification_verified` | `PASS` | Out-of-scope prompt cleanly abstained without fabricating figures (`abstention`), or ambiguous prompt asked a clarifying question (`clarification`). |
| `citation_only` | `PASS` | `case_type: citation_only` returned a non-empty grounded response (routing graded by `artifact` gate). |
| `mismatch` / `wrong_order` / `missing_items` / `table_mismatch` / `record_mismatch` / `direction_mismatch` / `forbidden_item` | `FAIL` | Extracted value or structure contradicted ground truth beyond configured tolerances. |
| `hallucinated_on_abstention` | `FAIL` | Target stated numeric metrics or confident claims on an `abstention` case instead of declining. |
| `no_number` / `ambiguous` / `range_rejected` | `FAIL` | Scalar prompt returned no compatible number, multiple conflicting un-disambiguated numbers, or only an interval range. |
| `no_expectation` | `INCONCLUSIVE` | Golden question has neither a calibrated `expected` value nor a resolved `reference_dax` ground truth. |

## Why `LatencyMs` and `DaxTotalMs` Are Non-Additive

`cfeval` records three timing columns per turn—never subtract one from another as if they formed a sequential waterfall:

* **`LatencyMs`**: End-to-end client wall-clock duration (`ResponseReceivedUtc - RequestSentUtc`), covering Graph transport, Copilot orchestration, model discovery, DAX execution, and answer generation.
* **`DaxTotalMs`**: Sum of `DurationMs` across all correlated `QueryEnd` events in `SemanticModelLogs`. When Copilot or a report visual context dispatches multiple DAX queries **concurrently**, `DaxTotalMs` can approach or exceed the wall-clock slice spent in Fabric.
* **`DaxCpuMs`**: Sum of engine `CpuTimeMs` across correlated `QueryEnd` events. Because VertiPaq scans execute across multiple CPU cores in parallel, `DaxCpuMs` frequently exceeds `DaxTotalMs`.

Report `LatencyMs` (user-perceived speed), `DaxTotalMs` (summed query duration), and `DaxCpuMs` (capacity CPU work) side by side rather than stacking `LatencyMs - DaxTotalMs` as "LLM latency".

## Related Pages

* [Evidence Tiers and Verdicts](./evidence-and-verdicts.md)
* [Author a Golden Set](../how-to/author-a-golden-set.md)
* [Compare Runs and Gate CI](../how-to/compare-runs-and-gate-ci.md)
