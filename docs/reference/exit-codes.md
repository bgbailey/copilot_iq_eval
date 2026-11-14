# CLI Exit Codes

`cfeval` uses deterministic process exit codes across `run`, `gate`, `compare`, `doctor`, `login`, `golden`, `trace`, and `judge` subcommands so shell scripts and GitHub Actions workflows can branch cleanly between policy failures, missing telemetry, and bad arguments.

## Exit Code Contract

| Exit Code | Constant / Meaning | Typical Triggers | Recommended CI / Operator Action |
|---:|---|---|---|
| `0` | **Success / Gate Passed** | Command completed cleanly; all active assertions, release thresholds, lint checks, or calibration minimums passed. | Proceed with deployment or semantic model promotion. |
| `1` | **Command Failure or Regression Detected** | `cfeval compare` or `cfeval gate --baseline` observed one or more paired regressions (`PASS -> FAIL`); `golden lint` / `validate` found schema or semantic errors; `doctor --strict` failed preflight; `judge calibrate` fell below `--min-kappa`. | Block the pull request and inspect regressed `QuestionId` rows or validation errors. |
| `2` | **Release Gate Threshold Failed** | `cfeval gate` or `cfeval run --strict` completed with valid evidence, but `OverallPassRate`, `ValuePassRate`, `ArtifactPassRate`, or `pass^k` fell below `config/gates.yaml` minimums, or a `criticality: critical` test case failed (`FAIL`). | Review failing questions, measure descriptions, synonyms, or decoy models before releasing. |
| `3` | **Inconclusive or Error Evidence** | Under `--strict` or `cfeval gate`, one or more turns resolved to `INCONCLUSIVE` (for example Workspace Monitoring KQL logs had not arrived yet) or `ERROR` (upstream HTTP `5xx` / timeout). | Run `cfeval trace probe` or `cfeval rescore runs/<run_id>` after KQL ingestion catches up; never treat `3` as a pass. |
| `4` | **Configuration or Usage Error** | Invalid CLI flags (`argparse`), missing input files, malformed `.env`, or **token claim mismatch** (`tid` / `upn` did not match `CFEVAL_TENANT_ID` / `CFEVAL_EXPECTED_UPN`). | Fix CLI arguments, `.env` settings, or sign in as the expected synthetic test user (`cfeval login`). |

## Examples in CI Shell Steps

```bash
cfeval gate runs/candidate \
  --baseline runs/baseline \
  --junit junit.xml \
  --summary-md summary.md
rc=$?

case "$rc" in
  0) echo "Gate passed." ;;
  1) echo "Paired regression detected against baseline." ; exit 1 ;;
  2) echo "Pass-rate threshold or critical test case failed." ; exit 2 ;;
  3) echo "Telemetry inconclusive or target error — do not promote." ; exit 3 ;;
  4) echo "Configuration or CLI usage error." ; exit 4 ;;
esac
```

## Related Pages

* [CLI Reference](./cli.md)
* [Compare Runs and Gate CI](../how-to/compare-runs-and-gate-ci.md)
* [Evidence Tiers and Verdicts](../concepts/evidence-and-verdicts.md)
