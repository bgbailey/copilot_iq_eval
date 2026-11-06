"""Turn an ask, its artifacts and its DAX trace into EvalScore and EvalResult rows."""
from .artifacts import powerbi_artifacts
from .scorers import FAIL, INCONCLUSIVE, PASS, citation_artifacts, score_artifact, score_model, score_value, verdict

GATE_CHECKS = ("value", "artifact", "model")
EVALUATOR_NAMES = {
    "value": "cfeval.score_value",
    "artifact": "cfeval.score_artifact",
    "model": "cfeval.score_model",
    "judge_answer": "judge.answer_correctness",
    "why": "judge.why_consistency",
}


def trace_stats(queries, ask_start):
    if not queries:
        return {"count": 0, "total": 0.0, "max": 0.0, "first_offset": None}
    durations = [float(q.duration_ms or 0) for q in queries]
    first = min(q.query_time for q in queries)
    return {
        "count": len(queries),
        "total": round(sum(durations), 1),
        "max": round(max(durations), 1),
        "first_offset": round((first - ask_start).total_seconds() * 1000.0, 1),
    }


def deterministic_checks(q, ask, artifacts, trace):
    if ask["Status"] != "ok":
        return {}
    checks = {
        "value": score_value(ask["Answer"], q.expected_value, q.unit, q.rel_tol, q.abs_tol),
        "artifact": score_artifact(artifacts, q.expected_artifact, q.artifact_aliases, q.decoys),
    }
    model = score_model(trace["status"], trace["models"], q.model, q.decoys)
    if model is not None:
        checks["model"] = model
    return checks


def _outcome(score):
    if score is None:
        return "SKIPPED"
    return {PASS: "PASS", FAIL: "FAIL"}.get(score, "INCONCLUSIVE" if score == INCONCLUSIVE else "SCORED")


def score_rows(run_id, ask, backend, checks, scored_utc, evaluator_names=None):
    names = evaluator_names or EVALUATOR_NAMES
    rows = []
    for check, res in checks.items():
        if res is None:
            continue
        details = {k: v for k, v in res.items() if k not in ("score", "outcome", "reason")}
        rows.append({
            "RunId": run_id, "AskId": ask["AskId"], "QuestionId": ask["QuestionId"], "Backend": backend,
            "Check": check, "Evaluator": names.get(check, check), "Score": res.get("score"),
            "Outcome": res.get("outcome") or _outcome(res.get("score")), "Reason": res.get("reason", ""),
            "Details": details, "ScoredUtc": scored_utc,
        })
    return rows


def result_row(run_id, q, ask, artifacts, trace, checks, backend, scored_utc, gate_checks=GATE_CHECKS,
               backend_error=""):
    def s(name):
        res = checks.get(name)
        return None if res is None else res.get("score")

    value = checks.get("value") or {}
    decoy = bool((checks.get("artifact") or {}).get("decoy_hit") or (checks.get("model") or {}).get("decoy_hit"))
    if ask["Status"] != "ok" or backend_error:
        final = "ERROR"
    else:
        final = verdict({k: s(k) for k in gate_checks}, required=gate_checks)
    def notes(keys):
        return ["%s: %s" % (k, r.get("reason", "")) for k, r in checks.items() if k in keys and r is not None
                and r.get("reason") and (r.get("outcome") or _outcome(r.get("score"))) in ("FAIL", "INCONCLUSIVE")]

    reasons = notes(gate_checks)   # why the verdict is what it is
    if ask["Status"] == "ok":
        reasons += ["%s: required check did not return a score" % k for k in gate_checks if s(k) is None]
    judge_notes = notes([k for k in checks if k not in gate_checks])
    if ask["Status"] != "ok":
        reasons.insert(0, "Copilot Chat API error: %s" % ask.get("Error", ""))
    if backend_error:
        reasons.insert(0, "%s evaluation error: %s" % (backend, backend_error))
    stats = trace["stats"]
    cited = citation_artifacts(artifacts)
    return {
        "RunId": run_id, "AskId": ask["AskId"], "QuestionId": q.id, "Attempt": ask["Attempt"],
        "Question": q.question, "Category": q.category, "Criticality": q.criticality,
        "TestUser": ask["TestUser"], "AskStartUtc": ask["AskStartUtc"], "Backend": backend, "Verdict": final,
        "ValueScore": s("value"), "ArtifactScore": s("artifact"), "ModelScore": s("model"),
        "JudgeAnswerScore": s("judge_answer"), "WhyScore": s("why"), "DecoyHit": int(decoy),
        "PowerBiCited": len(powerbi_artifacts(cited)), "ExpectedArtifact": q.expected_artifact,
        "CitedArtifacts": "; ".join(sorted({a.get("name") or a.get("url") for a in cited})),
        "ExpectedModel": q.model, "QueriedModels": "; ".join(trace["models"]),
        "ExpectedValue": q.expected_value, "ExtractedValue": value.get("extracted"),
        "ValueErrorPct": value.get("error_pct"), "LatencyMs": ask["LatencyMs"], "WhyLatencyMs": ask["WhyLatencyMs"],
        "DaxQueryCount": stats["count"], "DaxTotalMs": stats["total"], "DaxMaxMs": stats["max"],
        "FirstDaxOffsetMs": stats["first_offset"], "TraceStatus": trace["status"],
        "AnswerPreview": (ask["Answer"] or "")[:1500], "WhyPreview": (ask["Why"] or "")[:1000],
        "Reasons": " | ".join(reasons)[:2000], "JudgeNotes": " | ".join(judge_notes)[:2000],
        "Error": backend_error or ask.get("Error") or "", "ScoredUtc": scored_utc,
    }


class LocalBackend:
    """Option 1 scoring: deterministic scorers in Python plus an optional Foundry-hosted judge model."""

    name = "fabric-native"

    def __init__(self, judge=None, gate_on_judge=False, telemetry=None, clock=None):
        self.judge = judge
        self.gate = GATE_CHECKS + (("judge_answer",) if gate_on_judge else ())
        self.telemetry = telemetry
        self.clock = clock

    def evaluate(self, run_id, items):
        scores, results = [], []
        for it in items:
            q, ask, artifacts, trace = it["q"], it["ask"], it["artifacts"], it["trace"]
            checks = deterministic_checks(q, ask, artifacts, trace)
            if self.judge and ask["Status"] == "ok":
                with self._stage("score.judge", ask["AskId"]):
                    checks["judge_answer"] = _with_outcome(self.judge.judge_answer(q, ask["Answer"]))
                    cited = sorted({a.get("name") or "" for a in citation_artifacts(artifacts)})
                    dax = "\n".join(x.dax for x in trace["queries"])[:1500]
                    checks["why"] = _with_outcome(self.judge.judge_why(
                        q, ask["Answer"], cited, ask["Why"], trace["models"], dax))
            now = self.clock.now()
            scores += score_rows(run_id, ask, self.name, checks, now)
            results.append(result_row(run_id, q, ask, artifacts, trace, checks, self.name, now, self.gate))
        return scores, results

    def _stage(self, name, ask_id):
        if self.telemetry is None:
            from contextlib import nullcontext
            return nullcontext()
        return self.telemetry.stage(name, ask_id)


def _with_outcome(res):
    if res is None:
        return None
    res = dict(res)
    sc = res.get("score")
    res.setdefault("outcome", "PASS" if sc is not None and sc >= 0.75 else "FAIL" if sc is not None and sc <= 0.25
                   else "INCONCLUSIVE")
    return res
