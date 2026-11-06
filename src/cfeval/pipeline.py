"""The run pipeline: ask Copilot Chat -> capture Fabric IQ's DAX -> score -> publish telemetry.

Every row is written to the run folder (JSONL, always) and to any extra sinks
(the Eventhouse). Ask rows stream as they happen; scores, results, stage
timings and the run row are written when the run finishes. EvalRun is submitted
last; asynchronous ingestion and OneLake propagation can still be incomplete.
"""
import json
import math
import random
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from . import __version__
from .artifacts import extract_artifacts, powerbi_artifacts
from .clock import SystemClock, iso, parse_iso
from .foundry import EVALUATOR_NAMES as FOUNDRY_EVALUATOR_NAMES
from .foundry import foundry_row
from .golden import GoldenQuestion
from .scoring import GATE_CHECKS, deterministic_checks, result_row, score_rows, trace_stats
from .scorers import citation_artifacts
from .sinks import FanoutSink, JsonlSink
from .telemetry import Telemetry
from .trace import AskWindow, TraceCollectionError, correlate, query_key, settle_queries, wait_for_ingestion

PAD_SECONDS = 5.0
BACKENDS = ("fabric-native", "foundry")


def new_run_id(clock, rng=None):
    return "run-%s-%06x" % (clock.now().strftime("%Y%m%d-%H%M%S"), (rng or random).getrandbits(24))


def percentile(values, p):
    """Linear interpolation between closest ranks (same as numpy's default and the app)."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def _accuracy(scores):
    decided = [s for s in scores if s in (0.0, 1.0)]
    return round(sum(decided) / len(decided), 4) if decided else None


def run_metrics(results):
    """Run-level metrics over EvalResult rows (one backend)."""
    n = len(results)
    ok = [r for r in results if r["Verdict"] != "ERROR"]
    return {
        "asks": n,
        "pass": sum(1 for r in results if r["Verdict"] == "PASS"),
        "fail": sum(1 for r in results if r["Verdict"] == "FAIL"),
        "inconclusive": sum(1 for r in results if r["Verdict"] == "INCONCLUSIVE"),
        "error": n - len(ok),
        "PassRate": round(sum(1 for r in results if r["Verdict"] == "PASS") / n, 4) if n else None,
        "ValueAccuracy": _accuracy([r["ValueScore"] for r in ok]),
        "ArtifactAccuracy": _accuracy([r["ArtifactScore"] for r in ok]),
        "ModelAccuracy": _accuracy([r["ModelScore"] for r in ok]),
        "DecoyRate": round(sum(r["DecoyHit"] for r in ok) / len(ok), 4) if ok else None,
        "LatencyP50Ms": percentile([r["LatencyMs"] for r in ok], 50),
        "LatencyP95Ms": percentile([r["LatencyMs"] for r in ok], 95),
    }


def ask_row(run_id, ask_id, q, attempt, res, explain_mode, test_user):
    answer = res.answer.text if res.answer else ""
    attributions = res.answer.attributions if res.answer else []
    artifacts = extract_artifacts(attributions, answer) if res.ok else []
    cited = citation_artifacts(artifacts)
    return {
        "RunId": run_id, "AskId": ask_id, "QuestionId": q.id, "Attempt": attempt, "Question": q.question,
        "TestUser": test_user, "ConversationId": res.conversation_id, "AskStartUtc": res.started,
        "AskEndUtc": res.ended, "LatencyMs": res.answer.latency_ms if res.answer else None,
        "Status": "ok" if res.ok else "error", "HttpStatus": res.http_status, "Error": res.error or "",
        "Answer": answer, "AnswerChars": len(answer), "Artifacts": artifacts,
        "ArtifactNames": "; ".join(sorted({a["name"] for a in cited if a.get("name")})),
        "PowerBiCited": len(powerbi_artifacts(cited)), "ExplainMode": explain_mode, "Why": res.why_text or "",
        "WhyJson": res.why_json, "WhyLatencyMs": res.explain.latency_ms if res.explain else None,
        "AttributionCount": len(attributions or []),
    }


def question_from_row(row):
    """Rebuild a GoldenQuestion from an EvalQuestion row (used by rescore)."""
    return GoldenQuestion(
        id=row["QuestionId"], question=row["Question"], category=row.get("Category") or "",
        expected_artifact=row.get("ExpectedArtifact") or "", artifact_aliases=row.get("ArtifactAliases") or "",
        expected_model=row.get("ExpectedModel") or "", decoys=row.get("Decoys") or "",
        expected_value=row.get("ExpectedValue"), unit=row.get("Unit") or "number",
        rel_tol=row.get("RelTol") if row.get("RelTol") is not None else 0.005,
        abs_tol=row.get("AbsTol") if row.get("AbsTol") is not None else 0.0,
        expected_answer=row.get("ExpectedAnswer") or "", reference_dax=row.get("ReferenceDax") or "",
        criticality=row.get("Criticality") or "standard")


@dataclass
class RunOutcome:
    run_id: str
    folder: Path
    status: str
    metrics: dict
    results: list
    run_row: dict
    foundry: dict = None
    sink_errors: list = field(default_factory=list)

    def summary_text(self):
        return (self.folder / "summary.md").read_text(encoding="utf-8")


class EvalHarness:
    """Runs the golden set against Copilot Chat and scores it with one or both backends."""

    def __init__(self, *, chat, questions, backends=("fabric-native",), local_backend=None, foundry_runner=None,
                 monitoring=None, watermark=None, clock=None, extra_sinks=(), output_dir="runs",
                 test_user="", trace_user="", explain_mode="followup", repeats=1, pause_seconds=20.0,
                 trace_wait_seconds=300.0, trace_poll_seconds=20.0, trace_settle_seconds=40.0,
                 golden_name="", golden_hash="",
                 judge_model="", surface="copilot-chat-api", host="local", run_name="", notes="",
                 settings_public=None, log=print, rng=None, run_id=None):
        unknown = set(backends) - set(BACKENDS)
        if unknown or not backends:
            raise ValueError("backends must be from %s" % (BACKENDS,))
        if "fabric-native" in backends and local_backend is None:
            raise ValueError("the fabric-native backend needs a LocalBackend")
        if "foundry" in backends and foundry_runner is None:
            raise ValueError("the foundry backend needs a Foundry runner")
        self.chat = chat
        self.questions = list(questions)
        self.backends = tuple(backends)
        self.local = local_backend
        self.foundry = foundry_runner
        self.monitoring = monitoring
        self.watermark = watermark
        self.clock = clock or SystemClock()
        self.rng = rng or random.Random()
        self.run_id = run_id or new_run_id(self.clock, self.rng)
        self.folder = Path(output_dir) / self.run_id
        self.jsonl = JsonlSink(self.folder)
        self.sink = FanoutSink(self.jsonl, *extra_sinks, on_error=log)
        self.telemetry = Telemetry(self.run_id, self.clock)
        if self.local is not None:
            self.local.telemetry, self.local.clock = self.telemetry, self.clock
        self.test_user = test_user
        self.trace_user = trace_user or test_user
        self.explain_mode = explain_mode
        self.repeats = max(1, int(repeats))
        self.pause_seconds = pause_seconds
        self.trace_wait_seconds = trace_wait_seconds
        self.trace_poll_seconds = trace_poll_seconds
        self.trace_settle_seconds = trace_settle_seconds
        if (not all(math.isfinite(v) for v in (trace_wait_seconds, trace_poll_seconds, trace_settle_seconds))
                or trace_wait_seconds < 0 or trace_poll_seconds <= 0 or trace_settle_seconds <= 0):
            raise ValueError("trace wait must be non-negative; poll and settle intervals must be positive")
        self.golden_name = golden_name
        self.golden_hash = golden_hash
        self.judge_model = judge_model
        self.surface = surface
        self.host = host
        self.run_name = run_name or "%s %s" % ("+".join(self.backends), self.clock.now().strftime("%Y-%m-%d %H:%M"))
        self.notes = notes
        self.settings_public = settings_public or {}
        self.log = log
        self.started = None

    # ---- pipeline ---------------------------------------------------------------------------------
    def run(self):
        self.started = self.clock.now()
        self._write_manifest()
        self.sink.write("EvalQuestion", [q.to_row(self.run_id) for q in self.questions])
        asks = self.collect()
        traces, trace_rows = self.capture_trace(asks)
        return self.finish(asks, traces, trace_rows, status="completed")

    def rescore(self):
        """Re-capture DAX and re-score an existing run folder (for example after a trace timeout).

        Appends new EvalScore / EvalResult rows (later ScoredUtc) and only DAX rows not
        captured before; readers take the latest score per ask and backend.
        """
        manifest_path = self.folder / "run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        self.started = parse_iso(manifest.get("started_utc")) or self.clock.now()
        _questions, asks = load_run(self.folder)
        if not asks:
            raise ValueError("no asks found in %s" % self.folder)
        traces, rows = self.capture_trace(asks)
        def identity(r):
            return (r["AskId"], iso(parse_iso(r["QueryTimeUtc"])) if isinstance(r["QueryTimeUtc"], str)
                    else iso(r["QueryTimeUtc"]), r["WorkspaceId"], r["ItemId"], r["CorrelationId"])
        seen = {identity(r) for r in self.jsonl.read("FabricIqQuery")}
        rows = [r for r in rows if identity(r) not in seen]
        return self.finish(asks, traces, rows, status="rescored")

    def collect(self):
        asks, total = [], self.repeats * len(self.questions)
        n = 0
        for attempt in range(1, self.repeats + 1):
            for q in self.questions:
                n += 1
                ask_id = "%s-%s-%d" % (self.run_id, q.id, attempt)
                with self.telemetry.stage("copilot.ask", ask_id, question_id=q.id) as info:
                    res = self.chat.ask(q.question, self.explain_mode)
                    info["status"] = "ok" if res.ok else "error"
                if res.answer is not None:
                    self.telemetry.event("copilot.answer", res.answer.latency_ms, ask_id)
                if res.explain is not None:
                    self.telemetry.event("copilot.why", res.explain.latency_ms, ask_id)
                row = ask_row(self.run_id, ask_id, q, attempt, res, self.explain_mode, self.test_user)
                self.sink.write("EvalAsk", [row])
                asks.append(row)
                self.log("[%d/%d] %s %s  %s  %s" % (
                    n, total, q.id, "ok " if res.ok else "ERR", "%.1fs" % ((row["LatencyMs"] or 0) / 1000.0),
                    (row["ArtifactNames"] or res.error or "(no citations)")[:70]))
                if n < total and self.pause_seconds:
                    self.clock.sleep(self.pause_seconds)
        return asks

    def capture_trace(self, asks, send_watermark=True):
        empty = {"status": "disabled", "queries": [], "models": [], "stats": trace_stats([], None)}
        traces = {a["AskId"]: dict(empty) for a in asks}
        if self.monitoring is None or not asks:
            return traces, []
        pad = timedelta(seconds=PAD_SECONDS)
        windows = [AskWindow(a["AskId"], parse_iso(a["AskStartUtc"]), parse_iso(a["AskEndUtc"])) for a in asks]
        first, last = min(w.start for w in windows), max(w.end for w in windows)
        deadline = self.clock.monotonic() + self.trace_wait_seconds
        marker = None
        if self.watermark is not None and send_watermark:
            marker = "%s-wm-%06x" % (self.run_id, self.rng.getrandbits(24))
            try:
                with self.telemetry.stage("trace.watermark"):
                    self.watermark.send(marker)
            except Exception as exc:  # fall back to the newest-event check
                self.log("DAX watermark query failed (%s); falling back to the newest logged event." % exc)
                marker = None
        queries, caught, settled, capture_error = [], None, False, False

        def fetch():
            nonlocal queries
            with self.telemetry.stage("trace.fetch") as info:
                try:
                    found = self.monitoring.fetch(self.trace_user, first - pad, last + pad)
                except TraceCollectionError as exc:
                    exc.queries = list({query_key(q): q for q in queries + exc.queries}.values())
                    raise
                queries = list({query_key(q): q for q in queries + found}.values())
                info["queries"] = len(found)
                return queries

        try:
            with self.telemetry.stage("trace.wait") as info:
                caught = wait_for_ingestion(self.monitoring, last + pad, self.clock,
                                            max(0, deadline - self.clock.monotonic()),
                                            self.trace_poll_seconds, marker=marker, since=first - pad, log=self.log)
                if caught:
                    queries, settled = settle_queries(fetch, self.clock, deadline, self.trace_poll_seconds,
                                                      self.trace_settle_seconds)
                else:
                    queries = fetch()
                info.update(progress=caught or "timeout", settled=settled, queries=len(queries))
        except Exception as exc:
            self.log("DAX capture failed: %s" % exc)
            queries = getattr(exc, "queries", queries)
            capture_error = True
        queries = list({query_key(q): q for q in queries}.values())
        by_ask = correlate(windows, queries, PAD_SECONDS, PAD_SECONDS)
        rows = []
        for a, w in zip(asks, windows):
            found = by_ask.get(a["AskId"], [])
            status = "error" if capture_error else "observed" if settled and found else "pending"
            traces[a["AskId"]] = {"status": status, "queries": found, "stats": trace_stats(found, w.start),
                                  "models": sorted({x.item_name for x in found if x.item_name})}
            for x in found:
                rows.append({
                    "RunId": self.run_id, "AskId": a["AskId"], "QueryTimeUtc": x.query_time,
                    "OffsetMs": round((x.query_time - w.start).total_seconds() * 1000.0, 1),
                    "WorkspaceId": x.workspace_id, "ItemId": x.item_id, "ItemName": x.item_name,
                    "ApplicationName": x.application_name, "OperationName": x.operation_name,
                    "DurationMs": x.duration_ms, "Dax": x.dax, "DaxChars": len(x.dax or ""),
                    "CorrelationId": x.correlation_id})
        captured = sum(1 for t in traces.values() if t["queries"])
        self.log("DAX capture: %d queries for %d of %d asks (%s; %s). Time-window correlation is observational." %
                 (len(rows), captured, len(asks), caught or "timeout", "settled" if settled else "not settled"))
        return traces, rows

    def score(self, asks, traces):
        qmap = {q.id: q for q in self.questions}
        items = [{"q": qmap[a["QuestionId"]], "ask": a, "artifacts": a["Artifacts"] or [], "trace": traces[a["AskId"]]}
                 for a in asks]
        scores, results, foundry_meta = [], {}, None
        for backend in self.backends:
            if backend == "fabric-native":
                with self.telemetry.stage("score.local"):
                    s, r = self.local.evaluate(self.run_id, items)
            else:
                with self.telemetry.stage("score.foundry") as info:
                    s, r, foundry_meta = self._score_foundry(items)
                    info.update(eval_id=foundry_meta.get("eval_id"), foundry_run_id=foundry_meta.get("run_id"))
            scores += s
            results[backend] = r
        return scores, results, foundry_meta

    def _score_foundry(self, items):
        ok = [it for it in items if it["ask"]["Status"] == "ok"]
        rows = [foundry_row(it["q"], it["ask"], it["artifacts"], it["trace"]) for it in ok]
        try:
            meta = self.foundry.run(rows, "%s %s" % (self.run_name, self.run_id)) if rows else {
                "status": "skipped", "scores": {}}
        except Exception as exc:
            operation = dict(getattr(self.foundry, "last_operation", {}))
            meta = dict(operation, service_status=operation.get("status", "unknown"), status="error", scores={},
                        error="%s: %s" % (type(exc).__name__, str(exc)[:1000]))
        service_status = meta.get("status", "unknown")
        expected_checks = self.foundry.checks()
        unexpected = set(meta.get("scores", {})) - {it["ask"]["AskId"] for it in ok}
        errors = {}
        now = self.clock.now()
        scores, results = [], []
        for it in items:
            q, ask, artifacts, trace = it["q"], it["ask"], it["artifacts"], it["trace"]
            checks = {}
            backend_error = ""
            if ask["Status"] == "ok":
                returned = meta.get("scores", {}).get(ask["AskId"]) or {}
                missing = [
                    c for c in expected_checks
                    if not isinstance(returned.get(c), dict)
                    or isinstance(returned[c].get("score"), bool)
                    or not isinstance(returned[c].get("score"), (int, float))
                    or not math.isfinite(returned[c]["score"])
                    or not 0 <= returned[c]["score"] <= 1
                    or returned[c].get("error")
                ]
                if service_status != "completed":
                    backend_error = meta.get("error") or "Foundry run status is %s" % service_status
                elif unexpected:
                    backend_error = "Foundry returned scores for unexpected ask IDs"
                elif missing:
                    backend_error = "Foundry did not return valid scores for: " + ", ".join(missing)
                if backend_error:
                    errors[ask["AskId"]] = backend_error
                local = deterministic_checks(q, ask, artifacts, trace)
                for check, res in returned.items():
                    merged = dict(res)
                    if check in local and merged.get("score") == local[check].get("score"):
                        extra = {k: v for k, v in local[check].items() if k not in ("score", "outcome", "reason")}
                        merged.update(extra)
                        if not merged.get("reason"):
                            merged["reason"], merged["reason_source"] = local[check]["reason"], "local-replay"
                    elif check in local and not merged.get("reason"):
                        merged["reason"] = "Foundry score differs from local replay; inspect the original evaluator run."
                        merged["reason_source"] = "scorer-divergence"
                    checks[check] = merged
            scores += score_rows(self.run_id, ask, "foundry", checks, now, FOUNDRY_EVALUATOR_NAMES)
            results.append(result_row(self.run_id, q, ask, artifacts, trace, checks, "foundry", now, GATE_CHECKS,
                                      backend_error=backend_error))
        if errors:
            meta.setdefault("service_status", service_status)
            if service_status == "completed":
                meta["status"] = "partial"
            meta["errors"] = errors
            meta["error"] = "; ".join(sorted(set(errors.values())))[:2000]
            self.log("Foundry backend error: " + meta["error"])
            if meta.get("operation_path"):
                Path(meta["operation_path"]).write_text(
                    json.dumps({k: v for k, v in meta.items() if k != "scores"}, indent=2, default=str),
                    encoding="utf-8")
        return scores, results, {k: v for k, v in meta.items() if k != "scores"}

    def finish(self, asks, traces, trace_rows, status="completed"):
        full_run = status == "completed"
        scores, results, foundry_meta = self.score(asks, traces)
        all_results = [r for rows in results.values() for r in rows]
        if any(r["Verdict"] == "ERROR" for r in all_results):
            status = "partial" if any(r["Verdict"] != "ERROR" for r in all_results) else "failed"
        primary = results[self.backends[0]]
        metrics = run_metrics(primary)
        with self.telemetry.stage("publish.results"):
            self.sink.write("FabricIqQuery", trace_rows)
            self.sink.write("EvalScore", scores)
            for backend in self.backends:
                self.sink.write("EvalResult", results[backend])
        ended = self.clock.now()
        if full_run:
            self.telemetry.event("run.total", (ended - self.started).total_seconds() * 1000.0)
        self.sink.write("EvalEvent", self.telemetry.drain())
        fm = foundry_meta or {}
        run_row = {
            "RunId": self.run_id, "RunName": self.run_name, "EvalOption": "+".join(self.backends),
            "Surface": self.surface, "StartedUtc": self.started, "EndedUtc": ended, "Status": status,
            "Host": self.host, "HarnessVersion": __version__, "GoldenSetName": self.golden_name,
            "GoldenSetHash": self.golden_hash, "QuestionCount": len(self.questions), "AskCount": len(asks),
            "Repeats": self.repeats, "ExplainMode": self.explain_mode, "TraceEnabled": int(self.monitoring is not None),
            "TestUser": self.test_user, "JudgeModel": self.judge_model, "FoundryEvalId": fm.get("eval_id", ""),
            "FoundryRunId": fm.get("run_id", ""), "FoundryReportUrl": fm.get("report_url", ""),
            "PassRate": metrics["PassRate"], "ValueAccuracy": metrics["ValueAccuracy"],
            "ArtifactAccuracy": metrics["ArtifactAccuracy"], "ModelAccuracy": metrics["ModelAccuracy"],
            "LatencyP50Ms": metrics["LatencyP50Ms"], "LatencyP95Ms": metrics["LatencyP95Ms"],
            "Notes": self.notes + ("\nFoundry error: " + fm["error"] if fm.get("error") else ""),
        }
        self.sink.write("EvalRun", [run_row])
        self._write_summary(run_row, metrics, results, fm)
        self.log("Run %s %s: pass rate %s (%d pass, %d fail, %d inconclusive, %d error). Results in %s" % (
            self.run_id, status, _pct(metrics["PassRate"]), metrics["pass"], metrics["fail"],
            metrics["inconclusive"], metrics["error"], self.folder))
        return RunOutcome(self.run_id, self.folder, status, metrics, primary, run_row, fm or None, list(self.sink.errors))

    # ---- files ------------------------------------------------------------------------------------
    def _write_manifest(self):
        manifest = {"run_id": self.run_id, "run_name": self.run_name, "backends": list(self.backends),
                    "started_utc": iso(self.started), "harness_version": __version__, "surface": self.surface,
                    "host": self.host, "golden_set": self.golden_name, "golden_hash": self.golden_hash,
                    "settings": self.settings_public}
        (self.folder / "run.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    def _write_summary(self, run_row, metrics, results, fm):
        lines = ["# Copilot x Fabric IQ evaluation: %s" % self.run_name, "",
                 "Run `%s` | %s | %s | %d asks | harness %s" % (self.run_id, run_row["EvalOption"], self.surface,
                                                                run_row["AskCount"], __version__), ""]
        lines += ["| Metric | Value |", "|---|---|"]
        for key in ("PassRate", "ValueAccuracy", "ArtifactAccuracy", "ModelAccuracy", "DecoyRate"):
            lines.append("| %s | %s |" % (key, _pct(metrics[key])))
        for key in ("LatencyP50Ms", "LatencyP95Ms"):
            lines.append("| %s | %s |" % (key, "-" if metrics[key] is None else "%.1f s" % (metrics[key] / 1000.0)))
        if fm.get("report_url"):
            lines += ["", "Foundry evaluation report: %s" % fm["report_url"]]
        if fm.get("error"):
            lines += ["", "Foundry backend error: %s" % fm["error"]]
        for backend, rows in results.items():
            lines += ["", "## Results (%s)" % backend, "",
                      "| Question | Try | Verdict | Value | Artifact | Model | Latency | DAX | Why it failed |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for r in rows:
                lines.append("| %s | %s | **%s** | %s | %s | %s | %s | %s | %s |" % (
                    r["QuestionId"], r["Attempt"], r["Verdict"], _mark(r["ValueScore"]), _mark(r["ArtifactScore"]),
                    _mark(r["ModelScore"]), "-" if r["LatencyMs"] is None else "%.1f s" % (r["LatencyMs"] / 1000.0),
                    r["DaxQueryCount"], (r["Reasons"] or "").replace("|", "/")[:160]))
        lines += ["", "## Evidence gaps / still thin", "",
                  "DAX is correlated by user/time, not a Copilot engine request ID; settled capture is observational."]
        if self.surface == "simulated":
            lines.append("This run is simulated. It is not evidence of live Copilot, Fabric IQ or Foundry execution.")
        (self.folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value):
    return "-" if value is None else "%.0f%%" % (value * 100)


def _mark(score):
    return {1.0: "pass", 0.0: "fail", 0.5: "?"}.get(score, "-" if score is None else "%.2f" % score)


def load_run(folder):
    """Read a run folder back: (questions, asks) with datetimes parsed."""
    sink = JsonlSink(folder)
    questions = [question_from_row(r) for r in sink.read("EvalQuestion")]
    asks = sink.read("EvalAsk")
    for a in asks:
        a["AskStartUtc"], a["AskEndUtc"] = parse_iso(a["AskStartUtc"]), parse_iso(a["AskEndUtc"])
    return questions, asks
