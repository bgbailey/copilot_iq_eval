# Compare Runs and Gate CI

Before promoting semantic model edits—measure descriptions, synonyms, verified DAX patterns, display folders, or row-level security changes—compare the candidate evaluation run against a known baseline and enforce deterministic release thresholds in CI.

## Compare Baseline vs. Candidate (`cfeval compare`)

Run paired question-by-question comparison across any two run directories (mock, imported transcript, or live demo-tenant runs):

```bash
cfeval compare \
  --baseline runs/20261113T090000Z_baseline \
  --candidate runs/20261113T101500Z_tuned \
  --md-out runs/comparison_tuned_vs_baseline.md
```

`cfeval compare` pairs rows by `QuestionId` and reports:

* **Overall and per-gate deltas**: `OverallPassRate`, `ValuePassRate`, `ArtifactPassRate`, `ModelPassRate`, `pass@1`, and `pass^k` with Wilson 95% confidence intervals.
* **Discordant pair breakdown**: exact counts of **improvements** (`FAIL -> PASS`) and **regressions** (`PASS -> FAIL`), listing every regressed `QuestionId` first.
* **Exact paired McNemar $p$-value**: tests whether net improvements over regressions are statistically significant ($p < 0.05$).
* **Eventhouse persistence**: when `--publish` is enabled, writes a summary row into `EvalComparisons` so the scorecard app renders side-by-side diffs.

## Enforce Release Thresholds (`cfeval gate`)

Use `cfeval gate` to evaluate a completed run directory (optionally paired against `--baseline`) against `config/gates.yaml` and emit standard CI artifacts:

```bash
cfeval gate runs/20261113T101500Z_tuned \
  --baseline runs/20261113T090000Z_baseline \
  --junit junit.xml \
  --summary-md summary.md
```

Default policy checks (`config/gates.yaml`) verify:

* Minimum `OverallPassRate`, `ValuePassRate`, and `ArtifactPassRate` thresholds.
* Zero critical case failures (`criticality: critical` in your golden YAML).
* Zero regressions (`PASS -> FAIL`) relative to `--baseline` when a baseline is supplied.
* Zero `INCONCLUSIVE` or `ERROR` rows when strict gating is active.

Exit codes follow [CLI Exit Codes](../reference/exit-codes.md):

* `0` — all active release gates passed.
* `1` — regression detected against `--baseline` or command validation failed.
* `2` — release gate threshold failed (pass rate below floor or critical test failed).
* `3` — `INCONCLUSIVE` or `ERROR` evidence prevented complete grading.
* `4` — invalid CLI arguments or missing configuration/files.

## GitHub Actions Integration

Because live Microsoft 365 Copilot Chat evaluations require interactive delegated user tokens (`R2`), standard pull-request CI runs **offline** against committed transcripts or mock profiles while scheduled/pre-release workflows gate imported transcripts or pre-captured demo-tenant runs:

```yaml
name: Evaluate Golden Transcript Gate

on:
  pull_request:

permissions:
  contents: read

jobs:
  eval-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: "3.12"

      - name: Install cfeval
        run: pip install -e .

      - name: Score transcript and evaluate CI gate
        run: |
          cfeval golden lint data/golden/contoso-smoke.yaml
          cfeval run --target transcript-import \
            --transcript samples/contoso/transcript_sample.jsonl \
            --golden data/golden/contoso-smoke.yaml \
            --run-id ci-candidate \
            --no-publish
          cfeval gate runs/ci-candidate \
            --junit junit.xml \
            --summary-md "$GITHUB_STEP_SUMMARY"

      - name: Upload JUnit report
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: cfeval-junit
          path: junit.xml
```

Writing `--summary-md "$GITHUB_STEP_SUMMARY"` renders the pass-rate table, Wilson 95% interval, and per-question failures directly on the GitHub Actions run summary tab.

## Related Pages

* [CLI Exit Codes](../reference/exit-codes.md)
* [Metrics and Statistical Tests](../concepts/metrics.md)
* [Author a Golden Set](./author-a-golden-set.md)
