# How to Configure CI Regression Gates

Use `cfeval` in GitHub Actions or Azure Pipelines to block semantic-model, prompt, MCP-server, or scorer regressions before changes ship.

## Threshold Policy (`config/gates.yaml`)

Define release thresholds in [`config/gates.yaml`](../../config/gates.yaml):

```yaml
min_pass_rate: 0.85
min_critical_pass_rate: 1.0
min_value_accuracy: 0.85
min_routing_accuracy: 0.85
max_CriticalFailures: 0
max_p95_latency_ms: 45000
require_zero_errors: true
```

## Offline Scorer & Harness Gate (Every Pull Request)

Run offline mock smoke checks, reference-doc drift checks, link checks, and public-wording checks on every pull request with zero cloud secrets:

```yaml
name: cfeval-pr-gate
on: [pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e ".[dev]"
      - run: pytest
      - run: python samples/contoso/seed_contoso.py --verify
      - run: python tools/gen_reference_docs.py --check
      - run: python tools/check_docs_links.py
      - run: python tools/check_public_wording.py
      - run: >
          python -m cfeval run --mock --mock-profile tuned
          --golden data/golden/contoso.yaml
          --gates config/gates.yaml
          --junit runs/ci-tuned/junit.xml
          --no-publish
```

## Comparing Candidate vs Baseline Runs

When evaluating an updated semantic model description, custom instruction file, or MCP server build against a stored baseline run:

```powershell
python -m cfeval compare runs/baseline-prod runs/candidate-pr --fail-on-regression
```

## Exit Codes

| Exit Code | Meaning | Recommended CI Action |
|---|---|---|
| `0` | All configured quality gates passed and zero runtime errors occurred | Pass workflow |
| `2` | Evaluation completed, but one or more quality gates in `gates.yaml` failed | Fail PR / block promotion; upload HTML + JUnit artifacts |
| `3` | Runtime, authentication, trace-collection, or publication error | Mark job failed / alert platform owner |
| `64` | Invalid CLI arguments or malformed configuration/golden file | Fail fast |
