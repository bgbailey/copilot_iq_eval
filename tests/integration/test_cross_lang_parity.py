"""Cross-language parity tests between Python cfeval metrics/HTML report and TypeScript scorecard (M1-12, M2-06)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cfeval.cli import build_harness
from cfeval.config import Settings
from cfeval.golden import sample_golden_path
from cfeval.pipeline import deterministic_run_id, run_metrics
from cfeval.report import render_html_report

REPO_ROOT = Path(__file__).resolve().parents[2]
STANDALONE_DIR = REPO_ROOT / "app" / "standalone"
OVERLAY_EVAL_DIR = REPO_ROOT / "app" / "overlay" / "src" / "eval"

_NODE_PARITY_SCRIPT = """
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [runsRoot, overlayEvalDir] = process.argv.slice(1);
const metricsMod = await import(pathToFileURL(path.join(overlayEvalDir, 'metrics.ts')).href);
const normalizeMod = await import(pathToFileURL(path.join(overlayEvalDir, 'normalize.ts')).href);
const contractMod = await import(pathToFileURL(path.join(overlayEvalDir, 'generated', 'contract.ts')).href);

const { kpis, filterResults, runSummaries } = metricsMod;
const { normalizeRows } = normalizeMod;
const { COLUMNS } = contractMod;

function readJsonl(filePath) {
  if (!fs.existsSync(filePath)) return [];
  return fs
    .readFileSync(filePath, 'utf8')
    .split(/\\r?\\n/)
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line));
}

const runDirs = fs
  .readdirSync(runsRoot, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => path.join(runsRoot, d.name))
  .sort();

const rawRuns = [];
const rawQuestions = [];
const rawResults = [];

for (const dir of runDirs) {
  rawRuns.push(...readJsonl(path.join(dir, 'EvalRun.jsonl')));
  rawQuestions.push(...readJsonl(path.join(dir, 'EvalQuestion.jsonl')));
  rawResults.push(...readJsonl(path.join(dir, 'EvalResult.jsonl')));
}

const runs = normalizeRows(rawRuns, COLUMNS.EvalRun);
const questions = normalizeRows(rawQuestions, COLUMNS.EvalQuestion);
const results = normalizeRows(rawResults, COLUMNS.EvalResult);

const perRun = {};
for (const run of runs) {
  const runId = run.runId;
  const scoped = filterResults(results, { runId, backend: 'fabric-native' });
  perRun[runId] = kpis(scoped, true);
}

const summaries = runSummaries(runs, results, 'fabric-native');
const overall = kpis(filterResults(results, { backend: 'fabric-native' }), true);

process.stdout.write(JSON.stringify({ perRun, summaries, overall }));
"""


def test_python_typescript_and_html_report_metrics_parity(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    settings = Settings(
        golden_set=str(sample_golden_path()),
        output_dir=runs_dir,
        repeats=2,
        pause_seconds=0.0,
        trace_wait_seconds=180.0,
        trace_poll_seconds=15.0,
        trace_settle_seconds=10.0,
        test_user_upn="parity.runner@contoso.com",
    )

    profiles = ("baseline", "improving", "tuned")
    base_time = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    py_by_run: dict[str, dict[str, Any]] = {}
    html_by_run: dict[str, str] = {}
    all_py_results: list[dict[str, Any]] = []

    for idx, profile in enumerate(profiles):
        run_id = deterministic_run_id(7, profile, "fabric-native", idx, start=base_time)
        harness = build_harness(
            settings,
            option="fabric-native",
            mock=True,
            trace=True,
            publish=False,
            run_name=f"Parity {profile}",
            profile=profile,
            seed=7,
            start=base_time,
            repeats=2,
            run_id=run_id,
            log=lambda *_a, **_k: None,
        )
        outcome = harness.run()
        py_metrics = run_metrics(outcome.results)
        compare_dir = next(iter(py_by_run.values()))["folder"] if py_by_run else None
        report_path = render_html_report(
            outcome.folder,
            outcome.folder / "report.html",
            compare_dir=compare_dir,
        )
        py_by_run[run_id] = {
            "folder": outcome.folder,
            "metrics": py_metrics,
            "run_row": outcome.run_row,
            "stats": outcome.stats,
        }
        all_py_results.extend(outcome.results)
        html_by_run[run_id] = report_path.read_text(encoding="utf-8")

    proc = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            _NODE_PARITY_SCRIPT,
            str(runs_dir),
            str(OVERLAY_EVAL_DIR),
        ],
        cwd=str(STANDALONE_DIR),
        check=True,
        capture_output=True,
        text=True,
    )
    ts_payload = json.loads(proc.stdout)
    ts_per_run: dict[str, dict[str, Any]] = ts_payload["perRun"]
    ts_summaries: dict[str, dict[str, Any]] = {s["runId"]: s for s in ts_payload["summaries"]}

    assert set(ts_per_run) == set(py_by_run)

    field_pairs = (
        ("PassRate", "passRate"),
        ("ValueAccuracy", "valueAccuracy"),
        ("ArtifactAccuracy", "artifactAccuracy"),
        ("ModelAccuracy", "modelAccuracy"),
        ("LatencyP50Ms", "latencyP50"),
        ("LatencyP95Ms", "latencyP95"),
    )

    for run_id, py_bundle in py_by_run.items():
        py_m = py_bundle["metrics"]
        ts_m = ts_per_run[run_id]
        ts_sum = ts_summaries[run_id]

        for py_key, ts_key in field_pairs:
            assert py_m[py_key] is not None, f"{run_id}: Python {py_key} is None"
            assert ts_m[ts_key] is not None, f"{run_id}: TypeScript {ts_key} is None"
            assert abs(float(py_m[py_key]) - float(ts_m[ts_key])) <= 1e-6, (
                f"{run_id} {py_key} mismatch: py={py_m[py_key]} vs ts={ts_m[ts_key]}"
            )
            assert abs(float(py_m[py_key]) - float(ts_sum[ts_key])) <= 1e-6

        # Verify repeatability pass^k agreement between Python EvalRun/stats and TypeScript summary
        assert abs(float(py_bundle["run_row"]["PassPowK"]) - float(ts_sum["passPowK"])) <= 1e-6

        # Verify rendered HTML report agrees with the computed PassRate, pass^k, and Latency p50/p95
        html_doc = html_by_run[run_id]
        expected_pass_pct = f"{float(ts_m['passRate']) * 100.0:.1f}%"
        expected_pow_pct = f"pass^2: {float(py_bundle['stats']['mean_pass_pow_k']) * 100.0:.1f}%"
        expected_p50_str = f"p50: {float(ts_m['latencyP50']):.0f} ms"
        expected_p95_str = f"p95: {float(ts_m['latencyP95']):.0f} ms"

        assert expected_pass_pct in html_doc
        assert expected_pow_pct in html_doc
        assert expected_p50_str in html_doc
        assert expected_p95_str in html_doc

    # Multi-run aggregate parity check across all 3 runs combined (48 asks total)
    py_overall_pass_rate = sum(1 for r in all_py_results if r["Verdict"] == "PASS") / len(all_py_results)
    assert abs(py_overall_pass_rate - float(ts_payload["overall"]["passRate"])) <= 1e-6
    assert ts_payload["overall"]["asks"] == len(all_py_results)
    assert pytest.approx(py_by_run[list(py_by_run)[-1]]["metrics"]["PassRate"], abs=1e-6) == 1.0
