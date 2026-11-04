# Source of fabric/notebooks/nb_03_validate_and_snapshot.ipynb. Build with: python scripts/build_notebooks.py
# %% [markdown]
# # nb_03 · Validate the deployment and snapshot the expected values
#
# Backlog task **P1.7** · PLAN §4.2, §9.6.1. Run after nb_02. It queries the semantic models the
# way the evaluation runner will, as each persona (row-level security applied), and:
#
# 1. **validates** the figures nb_01 calibrates exactly: FY2025 gross revenue for the exec persona
#    (all regions) and for the east persona (East only, which proves RLS), and the FY2025 Sev1 mean
#    time to resolve. A failure stops the run with the difference;
# 2. **snapshots** the reference DAX of every single-model `answer` case in the golden set to
#    `Files/eval/expected_snapshot.json` in the attached lakehouse. `evals deploy fabric` downloads
#    it to `runs/deploy/`. It names personas by key, never by user name, so it can be committed as
#    `evals/golden/expected_snapshot.json` for the frozen ground-truth mode (PLAN §5.3). The runner
#    still computes expected values live on every run (PLAN §9.6.1).
#
# Queries run with `effective_user_name`, so the account running this notebook needs Build
# permission on the models (workspace Admin or Member has it).

# %% [parameters]
certified_workspace = "ws-eval-certified"
exec_upn = ""  # filled in by evals deploy fabric
east_upn = ""
cases_json = "[]"  # [{"case_id", "model", "persona", "persona_upn", "dax"}], filled in by evals deploy fabric
output_path = "/lakehouse/default/Files/eval/expected_snapshot.json"

# %% [logic]
import json
from decimal import Decimal

# Figures nb_01 calibrates to the cent; they hold for any seed (PLAN §4.1, workiq/content.yaml).
CALIBRATED_CHECKS = [
    {
        "check": "FY2025 gross revenue, all regions",
        "model": "Sales Analytics",
        "persona": "exec",
        "dax": "EVALUATE ROW(\"v\", CALCULATE([Gross Revenue], 'Date'[Fiscal Year] = \"FY2025\"))",
        "expected": "12840000.00",
        "places": 2,
    },
    {
        "check": "FY2025 gross revenue, East only (row-level security)",
        "model": "Sales Analytics",
        "persona": "east",
        "dax": "EVALUATE ROW(\"v\", CALCULATE([Gross Revenue], 'Date'[Fiscal Year] = \"FY2025\"))",
        "expected": "4200000.00",
        "places": 2,
    },
    {
        "check": "FY2025 Sev1 mean time to resolve, hours",
        "model": "Service Operations",
        "persona": "exec",
        "dax": "EVALUATE ROW(\"v\", CALCULATE([MTTR Hours], 'Date'[Fiscal Year] = \"FY2025\", "
        "'Incident'[Severity] = 1))",
        "expected": "7.20",
        "places": 2,
    },
]


def to_decimal(value) -> Decimal:
    """A DAX result cell as a Decimal (None becomes 0, so a blank result fails the check)."""
    return Decimal(str(value)) if value is not None else Decimal(0)


def check_result(check: dict, value) -> str | None:
    """None when the value matches the calibrated figure, else a description of the difference."""
    quantum = Decimal(1).scaleb(-check["places"])
    actual = to_decimal(value).quantize(quantum)
    expected = Decimal(check["expected"])
    return None if actual == expected else f"{check['check']}: expected {expected}, got {actual}"


def snapshot_entry(frame) -> dict:
    """A query result as a snapshot entry: one value, or a key -> value table (PLAN §9.6.1)."""
    rows = frame.to_dict(orient="records")
    columns = list(frame.columns)
    if len(columns) == 1 and len(rows) <= 1:
        return {"value": str(to_decimal(rows[0][columns[0]])) if rows else None}
    key_column, value_column = columns[0], columns[-1]
    return {"table": {str(row[key_column]): str(to_decimal(row[value_column])) for row in rows}}


# %%
from pathlib import Path  # noqa: E402

import sempy.fabric as fabric  # noqa: E402

PERSONAS = {"exec": exec_upn, "east": east_upn}


def run_dax(model: str, dax: str, upn: str):
    if not upn:
        raise ValueError("persona UPN parameter is empty; run this notebook from evals deploy fabric")
    return fabric.evaluate_dax(dataset=model, dax_string=dax, workspace=certified_workspace,
                               effective_user_name=upn)


failures = []
for check in CALIBRATED_CHECKS:
    frame = run_dax(check["model"], check["dax"], PERSONAS[check["persona"]])
    value = frame.iloc[0, 0] if len(frame) else None
    problem = check_result(check, value)
    print(("FAIL  " if problem else "PASS  ") + check["check"] + f" = {value}")
    if problem:
        failures.append(problem)
if failures:
    raise AssertionError("Deployment validation failed:\n" + "\n".join(failures))

snapshot = {"workspace": certified_workspace, "cases": {}, "errors": {}}
for case in json.loads(cases_json):
    try:
        entry = snapshot_entry(run_dax(case["model"], case["dax"], case["persona_upn"]))
        snapshot["cases"][case["case_id"]] = {"model": case["model"], "persona": case["persona"], **entry}
    except Exception as error:  # noqa: BLE001 - one bad case must not hide the others
        snapshot["errors"][case["case_id"]] = f"{type(error).__name__}: {error}"

Path(output_path).parent.mkdir(parents=True, exist_ok=True)
Path(output_path).write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
print(f"Snapshot: {len(snapshot['cases'])} cases, {len(snapshot['errors'])} errors -> {output_path}")
