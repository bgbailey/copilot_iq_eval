"""The run pipeline: ask Copilot Chat -> capture Fabric IQ's DAX -> score -> publish telemetry.

Every row is written to the run folder (JSONL, always) and to any extra sinks
(the Eventhouse). Ask rows stream as they happen; scores, results, stage
timings and the run row are written when the run finishes. EvalRun is submitted
last; asynchronous ingestion and OneLake propagation can still be incomplete.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import extract_artifacts, powerbi_artifacts
from .clock import SystemClock, iso, parse_iso
from .foundry import EVALUATOR_NAMES as FOUNDRY_EVALUATOR_NAMES
from .foundry import foundry_row
from .golden import GoldenQuestion
from .judge import judge_prompt_hash
from .schema import SCHEMA_VERSION
from .scorers import POWERBI_KINDS, citation_artifacts, load_gate_policy
from .scoring import GATE_CHECKS, deterministic_checks, result_row, score_rows, trace_stats
from .sinks import FanoutSink, JsonlSink
from .stats import summarize_run_stats
from .telemetry import Telemetry
from .trace import (
    AskWindow,
    FabricQuery,
    InMemoryMonitoringSource,
    TraceCollectionError,
    compute_correlation_confidence,
    compute_routing_evidence,
    correlate,
    extract_artifact_ids,
    query_key,
    settle_queries,
    wait_for_ingestion,
)

PAD_SECONDS = 5.0
BACKENDS = ("fabric-native", "foundry")
_UNSET = object()


def new_run_id(clock: Any, rng: Any = None) -> str:
    return "run-%s-%06x" % (clock.now().strftime("%Y%m%d-%H%M%S"), (rng or random).getrandbits(24))


def deterministic_run_id(
    seed: int | str,
    profile: str,
    option: str,
    index: int,
    *,
    start: datetime | None = None,
) -> str:
    """Deterministic RunId for reproducible simulated/demo runs."""
    idx = int(index)
    if start is not None:
        return "run-%s-%02d-%s" % (start.strftime("%Y%m%d-%H%M%S"), idx + 1, profile)
    digest = hashlib.sha256(f"{seed}|{profile}|{option}|{idx}".encode()).hexdigest()[:6]
    return "run-sim-%02d-%s-%s" % (idx + 1, profile, digest)


def percentile(values: Sequence[float | int | None], p: float) -> float | None:
    """Linear interpolation between closest ranks (same as numpy's default and the app)."""
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


class _DeterministicTelemetry(Telemetry):
    """Simulated-clock telemetry that omits host wall-clock jitter from DurationMs."""

    def _elapsed(self, t0_wall: float, t0_clock: float) -> float:
        return (self.clock.monotonic() - t0_clock) * 1000.0


def _accuracy(scores: Sequence[float | None]) -> float | None:
    decided = [s for s in scores if s in (0.0, 1.0)]
    return round(sum(decided) / len(decided), 4) if decided else None


def run_metrics(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
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


def _is_work_iq_question(q: Any) -> bool:
    exp_model = (getattr(q, "expected_model", "") or "").strip()
    if exp_model:
        return False
    exp_art = (getattr(q, "expected_artifact", "") or "").strip()
    if not exp_art:
        return False
    q_gates = [str(g).strip().lower() for g in (getattr(q, "gates", None) or ())]
    return "model" not in q_gates


def _normalize_turn_response(res: Any) -> dict[str, Any]:
    """Normalize either chat.AskResult or interfaces.TargetTurn into a common structure."""
    ans_obj = getattr(res, "answer", None)
    exp_obj = getattr(res, "explain", None)
    if ans_obj is not None:
        answer_text = ans_obj.text or ""
        attributions = list(ans_obj.attributions or [])
        latency_ms = ans_obj.latency_ms
    else:
        answer_text = str(getattr(res, "answer_text", "") or "")
        attributions = list(getattr(res, "attributions", None) or [])
        latency_ms = getattr(res, "latency_ms", None)

    why_latency_ms = exp_obj.latency_ms if exp_obj is not None else getattr(res, "why_latency_ms", None)
    http_status = int(getattr(res, "http_status", 200) or 0)
    error = str(getattr(res, "error", "") or "")
    if hasattr(res, "ok"):
        ok = bool(res.ok)
    else:
        ok = not error and (http_status == 0 or 200 <= http_status < 300)

    return {
        "ok": ok,
        "answer_text": answer_text,
        "attributions": attributions,
        "pre_artifacts": list(getattr(res, "artifacts", None) or []),
        "conversation_id": str(getattr(res, "conversation_id", "") or ""),
        "started": getattr(res, "started", None),
        "ended": getattr(res, "ended", None),
        "latency_ms": latency_ms,
        "why_text": str(getattr(res, "why_text", "") or ""),
        "why_json": getattr(res, "why_json", None),
        "why_latency_ms": why_latency_ms,
        "http_status": http_status,
        "error": error,
        "tool_calls": list(getattr(res, "tool_calls", None) or []),
        "routing_evidence": str(getattr(res, "routing_evidence", "") or ""),
    }


def ask_row(
    run_id: str,
    ask_id: str,
    q: Any,
    attempt: int,
    res: Any,
    explain_mode: str,
    test_user: str,
    target: str = "copilot-chat",
    persona: str = "",
) -> dict[str, Any]:
    norm = _normalize_turn_response(res)
    answer = norm["answer_text"]
    attributions = norm["attributions"]
    if norm["ok"]:
        artifacts = extract_artifacts(attributions, answer)
        seen_urls = {(a.get("kind"), (a.get("item_id") or a.get("url") or "").lower()) for a in artifacts}
        for extra_art in norm["pre_artifacts"]:
            if isinstance(extra_art, dict):
                key = (extra_art.get("kind"), (extra_art.get("item_id") or extra_art.get("url") or "").lower())
                if key not in seen_urls:
                    artifacts.append(dict(extra_art))
                    seen_urls.add(key)
    else:
        artifacts = []

    if target == "transcript-import":
        for art in artifacts:
            if str(art.get("attribution_type") or "").lower() == "citation" and str(
                art.get("attribution_source") or ""
            ).lower() not in ("", "model", "grounding"):
                art["attribution_source"] = "model"

    pbi_count = len(powerbi_artifacts(citation_artifacts(artifacts)))
    if _is_work_iq_question(q):
        for art in artifacts:
            if art.get("kind") and art.get("kind") not in POWERBI_KINDS:
                art["detected_kind"] = art["kind"]
                art["kind"] = ""

    cited = citation_artifacts(artifacts)
    eff_persona = persona or getattr(q, "persona", "") or ""
    return {
        "RunId": run_id,
        "AskId": ask_id,
        "QuestionId": q.id,
        "Attempt": attempt,
        "Question": q.question,
        "TestUser": test_user,
        "ConversationId": norm["conversation_id"],
        "AskStartUtc": norm["started"],
        "AskEndUtc": norm["ended"],
        "LatencyMs": norm["latency_ms"],
        "Status": "ok" if norm["ok"] else "error",
        "HttpStatus": norm["http_status"],
        "Error": norm["error"],
        "Answer": answer,
        "AnswerChars": len(answer),
        "Artifacts": artifacts,
        "ArtifactNames": "; ".join(sorted({a["name"] for a in cited if a.get("name")})),
        "PowerBiCited": pbi_count,
        "ExplainMode": explain_mode,
        "Why": norm["why_text"],
        "WhyJson": norm["why_json"],
        "WhyLatencyMs": norm["why_latency_ms"],
        "AttributionCount": len(attributions or []),
        "Target": target or "copilot-chat",
        "Persona": eff_persona,
    }


def _split_semi(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [part.strip() for part in str(raw).split(";") if part.strip()]


def question_from_row(row: dict[str, Any], meta: dict[str, Any] | None = None) -> GoldenQuestion:
    """Rebuild a GoldenQuestion from an EvalQuestion row (used by rescore)."""
    q_meta = dict((meta or {}).get(row["QuestionId"]) or {})
    raw_intent = row.get("Intent")
    intent_dict: dict[str, Any] = {}
    if isinstance(raw_intent, dict):
        intent_dict = dict(raw_intent)
    elif isinstance(raw_intent, str) and raw_intent.strip():
        try:
            parsed_intent = json.loads(raw_intent)
            if isinstance(parsed_intent, dict):
                intent_dict = parsed_intent
        except ValueError:
            intent_dict = {}

    expect_dict = dict(q_meta.get("expect") or {})
    display_tol = float(q_meta.get("display_tol", 0.01))
    currency = str(q_meta.get("currency") or "")
    paraphrases = list(q_meta.get("paraphrases") or _split_semi(row.get("Paraphrase")))

    return GoldenQuestion(
        id=row["QuestionId"],
        question=row["Question"],
        category=row.get("Category") or "",
        expected_artifact=row.get("ExpectedArtifact") or "",
        artifact_aliases=row.get("ArtifactAliases") or "",
        expected_model=row.get("ExpectedModel") or "",
        decoys=row.get("Decoys") or "",
        expected_value=row.get("ExpectedValue"),
        unit=row.get("Unit") or "number",
        rel_tol=float(row["RelTol"]) if row.get("RelTol") is not None else 0.005,
        abs_tol=float(row["AbsTol"]) if row.get("AbsTol") is not None else 0.0,
        expected_answer=row.get("ExpectedAnswer") or "",
        reference_dax=row.get("ReferenceDax") or "",
        criticality=row.get("Criticality") or "standard",
        expected_artifact_id=row.get("ExpectedArtifactId") or "",
        case_type=row.get("CaseType") or "scalar",
        expect=expect_dict,
        display_tol=display_tol,
        currency=currency,
        persona=row.get("Persona") or "",
        tags=_split_semi(row.get("Tags")),
        intent=intent_dict,
        gates=_split_semi(row.get("Gates")),
        paraphrases=paraphrases,
    )


@dataclass
class RunOutcome:
    run_id: str
    folder: Path
    status: str
    metrics: dict[str, Any]
    results: list[dict[str, Any]]
    run_row: dict[str, Any]
    foundry: dict[str, Any] | None = None
    sink_errors: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def summary_text(self) -> str:
        return (self.folder / "summary.md").read_text(encoding="utf-8")


class EvalHarness:
    """Runs the golden set against a target/Copilot Chat and scores it with one or both backends."""

    def __init__(
        self,
        *,
        chat: Any = None,
        target: Any = None,
        questions: Sequence[GoldenQuestion],
        backends: Sequence[str] = ("fabric-native",),
        local_backend: Any = None,
        foundry_runner: Any = None,
        monitoring: Any = _UNSET,
        watermark: Any = None,
        clock: Any = None,
        extra_sinks: Sequence[Any] = (),
        output_dir: str | Path = "runs",
        test_user: str = "",
        trace_user: str = "",
        explain_mode: str = "followup",
        repeats: int = 1,
        pause_seconds: float = 20.0,
        trace_wait_seconds: float = 300.0,
        trace_poll_seconds: float = 20.0,
        trace_settle_seconds: float = 40.0,
        golden_name: str = "",
        golden_hash: str = "",
        judge_model: str = "",
        surface: str | None = None,
        target_name: str = "",
        gate_profile: str = "auto",
        gates: Sequence[str] | str = (),
        persona: str = "",
        shard: tuple[int, int] = (0, 1),
        max_questions: int | None = None,
        max_wall_seconds: float | None = None,
        resume: bool = False,
        host: str = "local",
        run_name: str = "",
        notes: str = "",
        settings_public: dict[str, Any] | None = None,
        log: Callable[[str], Any] = print,
        rng: Any = None,
        run_id: str | None = None,
    ) -> None:
        unknown = set(backends) - set(BACKENDS)
        if unknown or not backends:
            raise ValueError("backends must be from %s" % (BACKENDS,))
        if "fabric-native" in backends and local_backend is None:
            raise ValueError("the fabric-native backend needs a LocalBackend")
        if "foundry" in backends and foundry_runner is None:
            raise ValueError("the foundry backend needs a Foundry runner")

        self.target = target
        self.chat = chat if chat is not None else target
        if target is not None and not target_name:
            self.target_name = str(getattr(target, "name", "") or "copilot-chat")
        else:
            self.target_name = target_name or "copilot-chat"

        if surface is None:
            target_surf = str(getattr(target, "surface", "") or "copilot-chat-api")
            self.surface = target_surf if target is not None else "copilot-chat-api"
        else:
            self.surface = surface

        shard_idx, shard_total = int(shard[0]), int(shard[1])
        if shard_total < 1 or not (0 <= shard_idx < shard_total):
            raise ValueError(
                "invalid shard (%d, %d): expected 0 <= index < total and total >= 1" % (shard_idx, shard_total)
            )
        self.shard = (shard_idx, shard_total)
        self.max_questions = None if max_questions is None else max(0, int(max_questions))
        self.max_wall_seconds = None if max_wall_seconds is None else float(max_wall_seconds)
        self.resume = bool(resume)
        self.gate_profile = gate_profile or "auto"
        if isinstance(gates, str):
            self.gates: tuple[str, ...] = tuple(g.strip() for g in gates.split(",") if g.strip())
        else:
            self.gates = tuple(str(g).strip() for g in (gates or ()) if str(g).strip())
        self.persona = persona or ""

        all_questions = list(questions)
        sharded = [q for idx, q in enumerate(all_questions) if idx % shard_total == shard_idx]
        if self.max_questions is not None:
            sharded = sharded[: self.max_questions]
        self.all_questions = all_questions
        self.questions = sharded

        self.backends = tuple(backends)
        self.local = local_backend
        self.foundry = foundry_runner
        if monitoring is _UNSET:
            self.monitoring = (
                getattr(target, "monitoring", None)
                if (target is not None and getattr(target, "supports_engine_trace", False))
                else None
            )
        else:
            self.monitoring = monitoring
        self.watermark = watermark
        self.clock = clock or SystemClock()
        self.rng = rng or random.Random()
        self.run_id = run_id or new_run_id(self.clock, self.rng)
        self.folder = Path(output_dir) / self.run_id
        self.jsonl = JsonlSink(self.folder)
        self.sink = FanoutSink(self.jsonl, *extra_sinks, on_error=log)
        telemetry_cls = _DeterministicTelemetry if hasattr(self.clock, "advance") else Telemetry
        self.telemetry = telemetry_cls(self.run_id, self.clock)
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
        if (
            not all(math.isfinite(v) for v in (trace_wait_seconds, trace_poll_seconds, trace_settle_seconds))
            or trace_wait_seconds < 0
            or trace_poll_seconds <= 0
            or trace_settle_seconds <= 0
        ):
            raise ValueError("trace wait must be non-negative; poll and settle intervals must be positive")
        self.golden_name = golden_name
        self.golden_hash = golden_hash
        self.judge_model = judge_model
        self.host = host
        self.run_name = run_name or "%s %s" % ("+".join(self.backends), self.clock.now().strftime("%Y-%m-%d %H:%M"))
        self.notes = notes
        self.settings_public = settings_public or {}
        self.log = log
        self.started: datetime | None = None
        self._tool_traces: dict[str, dict[str, Any]] = {}

    def _effective_policy_surface(self) -> str:
        if self.surface in ("work-iq", "work_iq"):
            return "work-iq"
        if self.target_name in ("mcp-agent", "fabric-iq-mcp-reference"):
            return "tool_call"
        return self.surface

    def _judge_gates_verdict(self) -> bool:
        if self.local is not None and "judge_answer" in getattr(self.local, "gate", ()):
            return True
        return bool(self.settings_public.get("judge_gates_verdict", False))

    def _resolve_question_policy(self, q: GoldenQuestion, trace: dict[str, Any] | None = None) -> dict[str, Any]:
        default_status = "observed" if self.monitoring is not None else "disabled"
        trace_status = str((trace or {}).get("status") or default_status).lower()
        trace_enabled = trace_status != "disabled"
        eff_surface = self._effective_policy_surface()
        judge_gates = self._judge_gates_verdict()

        raw_q_gates = tuple(str(g).strip() for g in (getattr(q, "gates", None) or ()) if str(g).strip())
        if self.gates:
            case_gates: Sequence[str] | None = self.gates
        elif self.gate_profile != "auto":
            if raw_q_gates == ("value",) and not (q.expected_artifact or q.expected_model):
                case_gates = raw_q_gates
            else:
                case_gates = None
        elif raw_q_gates:
            if not trace_enabled and "model" in raw_q_gates:
                stripped = tuple(g for g in raw_q_gates if g != "model")
                case_gates = None if raw_q_gates == GATE_CHECKS else (stripped or ("value",))
            elif eff_surface == "tool_call" and raw_q_gates == GATE_CHECKS:
                case_gates = None
            else:
                case_gates = raw_q_gates
        else:
            case_gates = None

        return load_gate_policy(
            self.gate_profile,
            trace_enabled=trace_enabled,
            surface=eff_surface,
            case_gates=case_gates,
            judge_gates_verdict=judge_gates,
        )

    def _invoke_driver_ask(self, q: GoldenQuestion, attempt: int, persona: str) -> Any:
        if self.chat is None:
            raise ValueError("EvalHarness requires a chat client or target to collect answers")
        ask_fn = self.chat.ask
        try:
            sig = inspect.signature(ask_fn)
            params = sig.parameters
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            kwargs: dict[str, Any] = {}
            if "explain_mode" in params or has_var_kw:
                kwargs["explain_mode"] = self.explain_mode
            if "attempt" in params:
                kwargs["attempt"] = attempt
            if "persona" in params:
                kwargs["persona"] = persona
            if "explain_mode" in params and params["explain_mode"].kind == inspect.Parameter.POSITIONAL_ONLY:
                return ask_fn(q.question, self.explain_mode)
            if kwargs:
                return ask_fn(q.question, **kwargs)
        except (TypeError, ValueError):
            pass
        return ask_fn(q.question, self.explain_mode)

    # ---- pipeline ---------------------------------------------------------------------------------
    def run(self) -> RunOutcome:
        self.started = self.clock.now()
        self._write_manifest()
        existing_qids: set[str] = set()
        if self.resume and (self.folder / "EvalQuestion.jsonl").exists():
            existing_qids = {str(r.get("QuestionId")) for r in self.jsonl.read("EvalQuestion")}
        new_q_rows = [q.to_row(self.run_id) for q in self.questions if q.id not in existing_qids]
        if new_q_rows:
            self.sink.write("EvalQuestion", new_q_rows)
        asks = self.collect()
        traces, trace_rows = self.capture_trace(asks)
        return self.finish(asks, traces, trace_rows, status="completed")

    def rescore(self) -> RunOutcome:
        """Re-capture DAX and re-score an existing run folder (for example after a trace timeout).

        Appends new EvalScore / EvalResult rows (later ScoredUtc) and only DAX rows not
        captured before; readers take the latest score per ask and backend.
        """
        manifest_path = self.folder / "run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        self.started = parse_iso(manifest.get("started_utc")) or self.clock.now()
        loaded_questions, asks = load_run(self.folder)
        if loaded_questions:
            self.questions = loaded_questions
        if not asks:
            raise ValueError("no asks found in %s" % self.folder)
        traces, rows = self.capture_trace(asks)

        def identity(r: dict[str, Any]) -> tuple[Any, ...]:
            q_ts = r["QueryTimeUtc"]
            iso_ts = iso(parse_iso(q_ts)) if isinstance(q_ts, str) else iso(q_ts)
            return (r["AskId"], iso_ts, r["WorkspaceId"], r["ItemId"], r["CorrelationId"])

        seen = {identity(r) for r in self.jsonl.read("FabricIqQuery")}
        rows = [r for r in rows if identity(r) not in seen]
        return self.finish(asks, traces, rows, status="rescored")

    def collect(self) -> list[dict[str, Any]]:
        asks: list[dict[str, Any]] = []
        total = self.repeats * len(self.questions)
        existing_ok: dict[tuple[str, int], dict[str, Any]] = {}
        if self.resume and (self.folder / "EvalAsk.jsonl").exists():
            for prev in self.jsonl.read("EvalAsk"):
                if prev.get("Status") == "ok":
                    prev["AskStartUtc"] = parse_iso(prev.get("AskStartUtc"))
                    prev["AskEndUtc"] = parse_iso(prev.get("AskEndUtc"))
                    key = (str(prev.get("QuestionId") or ""), int(prev.get("Attempt") or 1))
                    existing_ok[key] = prev

        collect_t0 = self.clock.monotonic()
        n = 0
        budget_exhausted = False
        for attempt in range(1, self.repeats + 1):
            if budget_exhausted:
                break
            for q in self.questions:
                n += 1
                cached = existing_ok.get((q.id, attempt))
                if cached is not None:
                    asks.append(cached)
                    self.log("[%d/%d] %s ok   (resumed)" % (n, total, q.id))
                    continue

                if self.max_wall_seconds is not None and (self.clock.monotonic() - collect_t0) >= self.max_wall_seconds:
                    self.log(
                        "Stopping collection: elapsed %.1fs reached max_wall_seconds (%.1fs)."
                        % (self.clock.monotonic() - collect_t0, self.max_wall_seconds)
                    )
                    budget_exhausted = True
                    break

                ask_id = "%s-%s-%d" % (self.run_id, q.id, attempt)
                eff_persona = self.persona or getattr(q, "persona", "")
                with self.telemetry.stage("copilot.ask", ask_id, question_id=q.id) as info:
                    res = self._invoke_driver_ask(q, attempt, eff_persona)
                    norm = _normalize_turn_response(res)
                    info["status"] = "ok" if norm["ok"] else "error"
                if norm["latency_ms"] is not None:
                    self.telemetry.event("copilot.answer", norm["latency_ms"], ask_id)
                if norm["why_latency_ms"] is not None:
                    self.telemetry.event("copilot.why", norm["why_latency_ms"], ask_id)
                if norm["tool_calls"]:
                    self._tool_traces[ask_id] = {
                        "tool_calls": norm["tool_calls"],
                        "started": norm["started"] or self.clock.now(),
                    }
                row = ask_row(
                    self.run_id,
                    ask_id,
                    q,
                    attempt,
                    res,
                    self.explain_mode,
                    self.test_user,
                    target=self.target_name,
                    persona=eff_persona,
                )
                self.sink.write("EvalAsk", [row])
                asks.append(row)
                self.log(
                    "[%d/%d] %s %s  %s  %s"
                    % (
                        n,
                        total,
                        q.id,
                        "ok " if norm["ok"] else "ERR",
                        "%.1fs" % ((row["LatencyMs"] or 0) / 1000.0),
                        (row["ArtifactNames"] or norm["error"] or "(no citations)")[:70],
                    )
                )
                if n < total and self.pause_seconds:
                    self.clock.sleep(self.pause_seconds)
        return asks

    def _queries_from_tool_calls(self, ask_id: str, ask_start: datetime | None) -> list[FabricQuery]:
        entry = self._tool_traces.get(ask_id)
        if not entry:
            return []
        ts = ask_start or entry.get("started") or self.clock.now()
        out: list[FabricQuery] = []
        for tc in entry.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            model_name = str(tc.get("model") or tc.get("item_name") or tc.get("dataset") or "")
            dax_txt = str(tc.get("dax") or tc.get("query") or "")
            if not (model_name or dax_txt):
                continue
            out.append(
                FabricQuery(
                    query_time=ts,
                    workspace_id=str(tc.get("workspace_id") or ""),
                    item_id=str(tc.get("item_id") or ""),
                    item_name=model_name,
                    application_name="MCP",
                    operation_name=str(tc.get("tool") or tc.get("name") or "ToolCall"),
                    duration_ms=float(tc.get("duration_ms") or 0.0),
                    dax=dax_txt,
                    correlation_id=str(tc.get("correlation_id") or ask_id),
                    operation_id=str(tc.get("operation_id") or "mcp-tool-call"),
                    application_context=json.dumps(tc.get("application_context") or {}, sort_keys=True)
                    if isinstance(tc.get("application_context"), dict)
                    else str(tc.get("application_context") or ""),
                    cpu_time_ms=float(tc.get("cpu_time_ms") or 0.0),
                    executing_user=self.trace_user,
                )
            )
        return out

    def capture_trace(
        self,
        asks: list[dict[str, Any]],
        send_watermark: bool = True,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        traces: dict[str, dict[str, Any]] = {}
        tool_rows: list[dict[str, Any]] = []
        is_mcp = self.target_name in ("mcp-agent", "fabric-iq-mcp-reference")
        for a in asks:
            aid = a["AskId"]
            a_start = parse_iso(a["AskStartUtc"]) if isinstance(a.get("AskStartUtc"), str) else a.get("AskStartUtc")
            cited = citation_artifacts(a.get("Artifacts") or [])
            tc_queries = self._queries_from_tool_calls(aid, a_start)
            if tc_queries and self.monitoring is None:
                traces[aid] = {
                    "status": "observed",
                    "queries": tc_queries,
                    "models": sorted({x.item_name for x in tc_queries if x.item_name}),
                    "stats": trace_stats(tc_queries, a_start),
                    "correlation_confidence": "high",
                    "routing_evidence": "tool_call",
                }
                for x in tc_queries:
                    tool_rows.append(x.to_dict(run_id=self.run_id, ask_id=aid, ask_start=a_start))
            else:
                traces[aid] = {
                    "status": "disabled",
                    "queries": [],
                    "models": [],
                    "stats": trace_stats([], None),
                    "correlation_confidence": "none",
                    "routing_evidence": compute_routing_evidence("disabled", [], cited),
                }
        if self.monitoring is None or not asks:
            return traces, tool_rows

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
        queries: list[FabricQuery] = []
        caught: str | None = None
        settled = False
        capture_error = False

        mon = self.monitoring

        def fetch() -> list[FabricQuery]:
            nonlocal queries
            with self.telemetry.stage("trace.fetch") as info:
                try:
                    found = mon.fetch(self.trace_user, first - pad, last + pad)
                except TraceCollectionError as exc:
                    exc.queries = list({query_key(q): q for q in queries + list(exc.queries)}.values())
                    raise
                queries = list({query_key(q): q for q in queries + found}.values())
                info["queries"] = len(found)
                return queries

        try:
            with self.telemetry.stage("trace.wait") as info:
                if isinstance(self.monitoring, InMemoryMonitoringSource):
                    queries = fetch()
                    caught = "in_memory"
                    settled = True
                else:
                    caught = wait_for_ingestion(
                        self.monitoring,
                        last + pad,
                        self.clock,
                        max(0.0, deadline - self.clock.monotonic()),
                        self.trace_poll_seconds,
                        marker=marker,
                        since=first - pad,
                        log=self.log,
                    )
                    if caught:
                        queries, settled = settle_queries(
                            fetch,
                            self.clock,
                            deadline,
                            self.trace_poll_seconds,
                            self.trace_settle_seconds,
                        )
                    else:
                        queries = fetch()
                info.update(progress=caught or "timeout", settled=settled, queries=len(queries))
        except Exception as exc:
            self.log("DAX capture failed: %s" % exc)
            queries = list(getattr(exc, "queries", queries))
            capture_error = True
        queries = list({query_key(q): q for q in queries}.values())
        by_ask = correlate(windows, queries, PAD_SECONDS, PAD_SECONDS)
        rows: list[dict[str, Any]] = []
        for a, w in zip(asks, windows, strict=False):
            found = by_ask.get(a["AskId"], [])
            status = "error" if capture_error else "observed" if settled and found else "pending"
            arts = a.get("Artifacts") or []
            cited = citation_artifacts(arts)
            art_ids = extract_artifact_ids(arts)
            corr_conf = compute_correlation_confidence(
                status,
                found,
                ask_window=w,
                all_windows=windows,
                artifact_ids=art_ids,
                user_upn=self.trace_user,
                pad_before_s=PAD_SECONDS,
                pad_after_s=PAD_SECONDS,
            )
            preset_ev = str(getattr(self.monitoring, "routing_evidence_preset", "") or "")
            routing_ev = (
                "tool_call"
                if ((is_mcp or preset_ev == "tool_call") and found and status == "observed")
                else compute_routing_evidence(status, found, cited)
            )
            traces[a["AskId"]] = {
                "status": status,
                "queries": found,
                "stats": trace_stats(found, w.start),
                "models": sorted({x.item_name for x in found if x.item_name}),
                "correlation_confidence": corr_conf,
                "routing_evidence": routing_ev,
            }
            for x in found:
                rows.append(
                    {
                        "RunId": self.run_id,
                        "AskId": a["AskId"],
                        "QueryTimeUtc": x.query_time,
                        "OffsetMs": round((x.query_time - w.start).total_seconds() * 1000.0, 1),
                        "WorkspaceId": x.workspace_id,
                        "ItemId": x.item_id,
                        "ItemName": x.item_name,
                        "ApplicationName": x.application_name,
                        "OperationName": x.operation_name,
                        "DurationMs": x.duration_ms,
                        "Dax": x.dax,
                        "DaxChars": len(x.dax or ""),
                        "CorrelationId": x.correlation_id,
                        "OperationId": getattr(x, "operation_id", "") or "",
                        "ApplicationContext": getattr(x, "application_context", "") or "",
                        "CpuTimeMs": float(getattr(x, "cpu_time_ms", 0.0) or 0.0),
                    }
                )
        captured = sum(1 for t in traces.values() if t["queries"])
        self.log(
            "DAX capture: %d queries for %d of %d asks (%s; %s). Time-window correlation is observational."
            % (len(rows), captured, len(asks), caught or "timeout", "settled" if settled else "not settled")
        )
        return traces, rows

    def score(
        self,
        asks: list[dict[str, Any]],
        traces: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any] | None]:
        qmap = {q.id: q for q in self.questions}
        for q in self.all_questions:
            qmap.setdefault(q.id, q)

        items: list[dict[str, Any]] = []
        for a in asks:
            orig_q = qmap[a["QuestionId"]]
            tr = traces[a["AskId"]]
            policy = self._resolve_question_policy(orig_q, tr)
            active_gates = list(policy["gates"])
            eff_q = dataclasses.replace(orig_q, gates=active_gates)
            items.append(
                {
                    "q": eff_q,
                    "ask": a,
                    "artifacts": a["Artifacts"] or [],
                    "trace": tr,
                    "active_gates": tuple(active_gates),
                }
            )

        scores: list[dict[str, Any]] = []
        results: dict[str, list[dict[str, Any]]] = {}
        foundry_meta: dict[str, Any] | None = None
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

    def _score_foundry(
        self, items: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        ok = [it for it in items if it["ask"]["Status"] == "ok"]
        rows: list[dict[str, Any]] = []
        for it in ok:
            q = it["q"]
            frow = foundry_row(q, it["ask"], it["artifacts"], it["trace"])
            frow["case_type"] = getattr(q, "case_type", "scalar") or "scalar"
            frow["expect_json"] = json.dumps(getattr(q, "expect", None) or {}, sort_keys=True)
            frow["display_tol"] = repr(getattr(q, "display_tol", 0.01))
            frow["currency"] = getattr(q, "currency", "") or ""
            rows.append(frow)

        meta: dict[str, Any]
        try:
            meta = (
                self.foundry.run(rows, "%s %s" % (self.run_name, self.run_id))
                if rows
                else {"status": "skipped", "scores": {}}
            )
        except Exception as exc:
            operation = dict(getattr(self.foundry, "last_operation", {}))
            meta = dict(
                operation,
                service_status=operation.get("status", "unknown"),
                status="error",
                scores={},
                error="%s: %s" % (type(exc).__name__, str(exc)[:1000]),
            )
        service_status = str(meta.get("status", "unknown"))
        expected_checks = self.foundry.checks()
        raw_scores: dict[str, Any] = dict(meta.get("scores") or {})
        unexpected = set(raw_scores) - {it["ask"]["AskId"] for it in ok}
        errors: dict[str, str] = {}
        now = self.clock.now()
        scores: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for it in items:
            q, ask, artifacts, trace = it["q"], it["ask"], it["artifacts"], it["trace"]
            active_gates = it.get("active_gates") or tuple(self._resolve_question_policy(q, trace)["gates"])
            checks: dict[str, Any] = {}
            backend_error = ""
            if ask["Status"] == "ok":
                returned = raw_scores.get(ask["AskId"]) or {}
                missing = [
                    c
                    for c in expected_checks
                    if not isinstance(returned.get(c), dict)
                    or isinstance(returned[c].get("score"), bool)
                    or not isinstance(returned[c].get("score"), (int, float))
                    or not math.isfinite(returned[c]["score"])
                    or not 0 <= returned[c]["score"] <= 1
                    or returned[c].get("error")
                ]
                if service_status != "completed":
                    backend_error = str(meta.get("error") or "Foundry run status is %s" % service_status)
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
                        merged["reason"] = (
                            "Foundry score differs from local replay; inspect the original evaluator run."
                        )
                        merged["reason_source"] = "scorer-divergence"
                    checks[check] = merged
            scores += score_rows(self.run_id, ask, "foundry", checks, now, FOUNDRY_EVALUATOR_NAMES)
            results.append(
                result_row(
                    self.run_id,
                    q,
                    ask,
                    artifacts,
                    trace,
                    checks,
                    "foundry",
                    now,
                    active_gates,
                    backend_error=backend_error,
                )
            )
        if errors:
            meta.setdefault("service_status", service_status)
            if service_status == "completed":
                meta["status"] = "partial"
            meta["errors"] = errors
            meta["error"] = "; ".join(sorted(set(errors.values())))[:2000]
            self.log("Foundry backend error: " + str(meta["error"]))
            op_path = meta.get("operation_path")
            if op_path:
                Path(str(op_path)).write_text(
                    json.dumps({k: v for k, v in meta.items() if k != "scores"}, indent=2, default=str),
                    encoding="utf-8",
                )
        return scores, results, {k: v for k, v in meta.items() if k != "scores"}

    def finish(
        self,
        asks: list[dict[str, Any]],
        traces: dict[str, dict[str, Any]],
        trace_rows: list[dict[str, Any]],
        status: str = "completed",
    ) -> RunOutcome:
        full_run = status == "completed"
        scores, results, foundry_meta = self.score(asks, traces)
        all_results = [r for rows in results.values() for r in rows]
        if any(r["Verdict"] == "ERROR" for r in all_results):
            status = "partial" if any(r["Verdict"] != "ERROR" for r in all_results) else "failed"
        primary = results[self.backends[0]]
        metrics = run_metrics(primary)
        stats_summary = summarize_run_stats(primary, k=self.repeats)
        metrics["PassPowK"] = round(stats_summary["mean_pass_pow_k"], 4)
        metrics["WilsonLow"] = round(stats_summary["wilson_low"], 4)
        metrics["WilsonHigh"] = round(stats_summary["wilson_high"], 4)
        metrics["CriticalFailures"] = stats_summary["critical_failures"]

        with self.telemetry.stage("publish.results"):
            self.sink.write("FabricIqQuery", trace_rows)
            self.sink.write("EvalScore", scores)
            for backend in self.backends:
                self.sink.write("EvalResult", results[backend])
        ended = self.clock.now()
        if full_run and self.started is not None:
            self.telemetry.event("run.total", (ended - self.started).total_seconds() * 1000.0)
        self.sink.write("EvalEvent", self.telemetry.drain())

        run_policy = load_gate_policy(
            self.gate_profile,
            trace_enabled=bool(self.monitoring is not None or self._tool_traces),
            surface=self._effective_policy_surface(),
            case_gates=(self.gates or None),
            judge_gates_verdict=self._judge_gates_verdict(),
        )
        judge_obj = getattr(self.local, "judge", None) if self.local is not None else None
        prompt_hash = str(getattr(judge_obj, "prompt_hash", "") or judge_prompt_hash())
        calib_id = str(getattr(judge_obj, "calibration_id", "") or "")

        fm = foundry_meta or {}
        Distinct_q_count = len({a["QuestionId"] for a in asks}) if asks else len(self.questions)
        run_row = {
            "RunId": self.run_id,
            "RunName": self.run_name,
            "EvalOption": "+".join(self.backends),
            "Surface": self.surface,
            "StartedUtc": self.started,
            "EndedUtc": ended,
            "Status": status,
            "Host": self.host,
            "HarnessVersion": __version__,
            "GoldenSetName": self.golden_name,
            "GoldenSetHash": self.golden_hash,
            "QuestionCount": Distinct_q_count if Distinct_q_count else len(self.questions),
            "AskCount": len(asks),
            "Repeats": self.repeats,
            "ExplainMode": self.explain_mode,
            "TraceEnabled": int(self.monitoring is not None),
            "TestUser": self.test_user,
            "JudgeModel": self.judge_model,
            "FoundryEvalId": fm.get("eval_id", ""),
            "FoundryRunId": fm.get("run_id", ""),
            "FoundryReportUrl": fm.get("report_url", ""),
            "PassRate": metrics["PassRate"],
            "ValueAccuracy": metrics["ValueAccuracy"],
            "ArtifactAccuracy": metrics["ArtifactAccuracy"],
            "ModelAccuracy": metrics["ModelAccuracy"],
            "LatencyP50Ms": metrics["LatencyP50Ms"],
            "LatencyP95Ms": metrics["LatencyP95Ms"],
            "Notes": self.notes + ("\nFoundry error: " + fm["error"] if fm.get("error") else ""),
            "Target": self.target_name,
            "K": self.repeats,
            "PassPowK": round(stats_summary["mean_pass_pow_k"], 4),
            "WilsonLow": round(stats_summary["wilson_low"], 4),
            "WilsonHigh": round(stats_summary["wilson_high"], 4),
            "JudgePromptHash": prompt_hash,
            "JudgeCalibrationId": calib_id,
            "GatePolicyHash": run_policy["gate_policy_hash"],
            "SchemaVersion": SCHEMA_VERSION,
        }
        self.sink.write("EvalRun", [run_row])
        self._write_summary(run_row, metrics, stats_summary, results, fm)
        self.log(
            "Run %s %s: pass rate %s [95%% CI %s..%s, pass^%d %s] "
            "(%d pass, %d fail, %d inconclusive, %d error). Results in %s"
            % (
                self.run_id,
                status,
                _pct(metrics["PassRate"]),
                _pct(run_row["WilsonLow"]),
                _pct(run_row["WilsonHigh"]),
                self.repeats,
                _pct(run_row["PassPowK"]),
                metrics["pass"],
                metrics["fail"],
                metrics["inconclusive"],
                metrics["error"],
                self.folder,
            )
        )
        return RunOutcome(
            self.run_id,
            self.folder,
            status,
            metrics,
            primary,
            run_row,
            fm or None,
            list(self.sink.errors),
            stats=stats_summary,
        )

    # ---- files ------------------------------------------------------------------------------------
    def _write_manifest(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        questions_meta = {
            q.id: {
                "expect": getattr(q, "expect", None) or {},
                "display_tol": getattr(q, "display_tol", 0.01),
                "currency": getattr(q, "currency", "") or "",
                "paraphrases": list(getattr(q, "paraphrases", None) or []),
            }
            for q in self.questions
        }
        manifest = {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "backends": list(self.backends),
            "started_utc": iso(self.started),
            "harness_version": __version__,
            "surface": self.surface,
            "target": self.target_name,
            "gate_profile": self.gate_profile,
            "gates": list(self.gates),
            "persona": self.persona,
            "shard": list(self.shard),
            "host": self.host,
            "golden_set": self.golden_name,
            "golden_hash": self.golden_hash,
            "settings": self.settings_public,
            "questions_meta": questions_meta,
        }
        (self.folder / "run.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    def _write_summary(
        self,
        run_row: dict[str, Any],
        metrics: dict[str, Any],
        stats_summary: dict[str, Any],
        results: dict[str, list[dict[str, Any]]],
        fm: dict[str, Any],
    ) -> None:
        lines = [
            "# Copilot x Fabric IQ evaluation: %s" % self.run_name,
            "",
            "Run `%s` | target `%s` | %s | %s | %d asks | harness %s"
            % (self.run_id, self.target_name, run_row["EvalOption"], self.surface, run_row["AskCount"], __version__),
            "",
        ]
        lines += ["| Metric | Value |", "|---|---|"]
        for key in ("PassRate", "ValueAccuracy", "ArtifactAccuracy", "ModelAccuracy", "DecoyRate"):
            lines.append("| %s | %s |" % (key, _pct(metrics[key])))
        lines.append(
            "| Wilson 95%% CI | %s – %s |"
            % (_pct(stats_summary.get("wilson_low")), _pct(stats_summary.get("wilson_high")))
        )
        lines.append("| pass^%d | %s |" % (self.repeats, _pct(stats_summary.get("mean_pass_pow_k"))))
        for key in ("LatencyP50Ms", "LatencyP95Ms"):
            lines.append("| %s | %s |" % (key, "-" if metrics[key] is None else "%.1f s" % (metrics[key] / 1000.0)))
        if fm.get("report_url"):
            lines += ["", "Foundry evaluation report: %s" % fm["report_url"]]
        if fm.get("error"):
            lines += ["", "Foundry backend error: %s" % fm["error"]]
        for backend, rows in results.items():
            lines += [
                "",
                "## Results (%s)" % backend,
                "",
                "| Question | Try | Verdict | Value | Artifact | Model | Latency | DAX | Why it failed |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for r in rows:
                lines.append(
                    "| %s | %s | **%s** | %s | %s | %s | %s | %s | %s |"
                    % (
                        r["QuestionId"],
                        r["Attempt"],
                        r["Verdict"],
                        _mark(r["ValueScore"]),
                        _mark(r["ArtifactScore"]),
                        _mark(r["ModelScore"]),
                        "-" if r["LatencyMs"] is None else "%.1f s" % (r["LatencyMs"] / 1000.0),
                        r["DaxQueryCount"],
                        (r["Reasons"] or "").replace("|", "/")[:160],
                    )
                )
        lines += [
            "",
            "## Known measurement limitations",
            "",
            "DAX is correlated by user/time, not a Copilot engine request ID; settled capture is observational.",
        ]
        if self.surface == "simulated":
            lines.append("This run is simulated. It is not evidence of live Copilot, Fabric IQ or Foundry execution.")
        (self.folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


EvaluationHarness = EvalHarness


def _pct(value: float | None) -> str:
    return "-" if value is None else "%.0f%%" % (value * 100)


def _mark(score: float | None) -> str:
    if score is None:
        return "-"
    return {1.0: "pass", 0.0: "fail", 0.5: "?"}.get(score, "%.2f" % score)


def load_run(folder: str | Path) -> tuple[list[GoldenQuestion], list[dict[str, Any]]]:
    """Read a run folder back: (questions, asks) with datetimes and rich expectations restored."""
    folder_path = Path(folder)
    sink = JsonlSink(folder_path)
    manifest_path = folder_path / "run.json"
    questions_meta: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                questions_meta = dict(manifest.get("questions_meta") or {})
        except ValueError:
            questions_meta = {}
    questions = [question_from_row(r, meta=questions_meta) for r in sink.read("EvalQuestion")]
    asks = sink.read("EvalAsk")
    for a in asks:
        a["AskStartUtc"], a["AskEndUtc"] = parse_iso(a["AskStartUtc"]), parse_iso(a["AskEndUtc"])
    return questions, asks
