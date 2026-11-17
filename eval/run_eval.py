"""Evaluate how Microsoft 365 Copilot answers questions about your Fabric data. Start here.

    python eval/run_eval.py --answers sample/answers-before.jsonl   # score saved answers, no Copilot needed
    python eval/run_eval.py                                          # ask Copilot live, as the test user
    python eval/run_eval.py --repeats 3 --label "After model fixes"  # ask each question three times

Each question gets three checks (see scoring.py):
  value     is the number right, compared with the reference DAX result?
  citation  did Copilot cite the expected report, and not a decoy?
  model     did the DAX actually run on the expected semantic model, according to workspace monitoring?
"""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from scoring import check_citation, check_model, check_value, verdict  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Read KEY=value lines from .env into the environment (a tiny stand-in for python-dotenv)."""
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.split(" #")[0].strip().strip('"'))


def ask_copilot(questions, repeats, env):
    """Live mode: refresh expected values, ask Copilot, then collect DAX evidence."""
    from copilot import SignIn, ask
    from fabric import dax_that_ran, reference_value

    signin = SignIn(env["TENANT_ID"], env["CLIENT_ID"], env["TEST_USER"])
    signin.token("copilot")  # sign in once up front

    if env.get("SEMANTIC_MODEL_ID"):
        token = signin.token("powerbi")
        for q in questions:
            if q.get("reference_dax"):
                q["expected"] = reference_value(token, q.get("model_id") or env["SEMANTIC_MODEL_ID"], q["reference_dax"])
                print(f"  {q['id']} expected value from reference DAX: {q['expected']:,.10g}")

    attempts = []
    for attempt in range(1, repeats + 1):
        for q in questions:
            print(f"Asking {q['id']} (attempt {attempt}): {q['question']}")
            try:
                a = ask(signin.token("copilot"), q["question"])
            except Exception as error:  # keep going; the question is recorded as ERROR
                a = {"error": str(error)[:300]}
            attempts.append({"id": q["id"], "attempt": attempt, **a})
            time.sleep(int(env.get("PAUSE_SECONDS", "5")))  # be gentle with the API

    if env.get("MONITORING_QUERY_URI"):
        wait = int(env.get("MONITORING_WAIT_SECONDS", "120"))
        print(f"Waiting {wait}s for workspace monitoring to record the DAX queries...")
        time.sleep(wait)
        token = signin.token("kusto")
        for a in attempts:
            if "error" not in a:
                a["queries"] = dax_that_ran(token, env["MONITORING_QUERY_URI"], env["MONITORING_DATABASE"],
                                            env["TEST_USER"], a["started"], a["ended"])
    return attempts, signin


def saved_answers(path):
    """Saved-answer mode: one JSON object per line with id, answer, citations and (optionally) queries."""
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    for row in rows:
        row.setdefault("attempt", 1)
    return rows


def score(question, a):
    if "error" in a:
        return {"verdict": "ERROR", "value": None, "citation": None, "model": None}
    value = check_value(a.get("answer", ""), question.get("expected"), question.get("unit", "number"),
                        question.get("tolerance", 0.005), question.get("expect_refusal", False))
    citation = check_citation(a.get("citations"), question.get("expected_report"), question.get("decoys"))
    model = check_model(a.get("queries"), question.get("expected_model"), question.get("decoys"))
    return {"verdict": verdict(value, citation, model), "value": value, "citation": citation, "model": model}


def show(cell, width):
    if not cell:
        return "-".ljust(width)
    text = cell["reason"]
    return (text if len(text) <= width else text[: width - 1] + "\u2026").ljust(width)


def main():
    parser = argparse.ArgumentParser(description="Evaluate Microsoft 365 Copilot answers over Fabric data.")
    parser.add_argument("--questions", default=str(ROOT / "questions.yaml"), help="golden questions file")
    parser.add_argument("--answers", help="score saved answers (JSONL) instead of asking Copilot")
    parser.add_argument("--repeats", type=int, default=1, help="ask each question this many times")
    parser.add_argument("--label", default="", help="a name for this run, shown in the scorecard")
    parser.add_argument("--no-publish", action="store_true", help="keep results on disk, skip the Eventhouse")
    args = parser.parse_args()

    load_env()
    env = dict(os.environ)
    questions = yaml.safe_load(open(args.questions, encoding="utf-8"))["questions"]
    by_id = {q["id"]: q for q in questions}
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    mode = "saved answers" if args.answers else "live"

    signin = None
    if args.answers:
        attempts = [a for a in saved_answers(args.answers) if a["id"] in by_id]
    else:
        attempts, signin = ask_copilot(questions, args.repeats, env)

    # ---- score and print ----
    results = []
    print(f"\nRun {run_id} {args.label!r} ({mode}, {len(attempts)} answers)\n")
    print(f"{'ID':<5}{'Verdict':<14}{'Value':<38}{'Citation':<34}{'Model'}")
    for a in attempts:
        q = by_id[a["id"]]
        s = score(q, a)
        print(f"{a['id']:<5}{s['verdict']:<14}{show(s['value'], 37)} {show(s['citation'], 33)} {show(s['model'], 40)}")
        results.append({"question": q, "answer": a, **s})

    passed = sum(r["verdict"] == "PASS" for r in results)
    print(f"\nPassed {passed} of {len(results)} ({passed / max(len(results), 1):.0%}).")
    if args.repeats > 1:
        steady = [qid for qid in by_id if all(r["verdict"] == "PASS" for r in results if r["question"]["id"] == qid)]
        print(f"Passed every attempt: {len(steady)} of {len(by_id)} questions.")

    # ---- save locally ----
    out = ROOT / "results" / f"{run_id}.jsonl"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({"run_id": run_id, "label": args.label, **r}, default=str) + "\n")
    print(f"Results saved to {out.relative_to(ROOT)}")

    # ---- publish to the Eventhouse for the scorecard app ----
    if env.get("EVENTHOUSE_QUERY_URI") and not args.no_publish:
        from copilot import SignIn
        from fabric import ingest
        signin = signin or SignIn(env["TENANT_ID"], env["CLIENT_ID"], env["TEST_USER"])
        token = signin.token("kusto")
        uri, db = env["EVENTHOUSE_QUERY_URI"], env["EVENTHOUSE_DATABASE"]
        ingest(token, uri, db, "EvalRuns", [run_row(run_id, args.label, started, mode, env, results, by_id)])
        ingest(token, uri, db, "EvalResults", [result_row(run_id, r) for r in results])
        ingest(token, uri, db, "EvalQueries", [query_row(run_id, r, q) for r in results
                                               for q in r["answer"].get("queries") or []])
        print(f"Published to the Eventhouse database {db}. The scorecard app shows it once OneLake syncs.")


# Column order must match eventhouse.kql.
def run_row(run_id, label, started, mode, env, results, by_id):
    passed = sum(r["verdict"] == "PASS" for r in results)
    return {"RunId": run_id, "Label": label, "StartedUtc": started.isoformat(), "Mode": mode,
            "TestUser": env.get("TEST_USER", ""), "Questions": len(by_id), "Answers": len(results),
            "Passed": passed, "PassRate": round(passed / max(len(results), 1), 4)}


def result_row(run_id, r):
    a, q = r["answer"], r["question"]
    cell = lambda c, k: (c or {}).get(k, "")  # noqa: E731
    return {"RunId": run_id, "QuestionId": q["id"], "Attempt": a.get("attempt", 1),
            "AskedUtc": a.get("started", ""), "Question": q["question"],
            "Answer": " ".join((a.get("answer") or a.get("error") or "").split()),
            "Expected": q.get("expected"), "Found": cell(r["value"], "found"),
            "ValueCheck": cell(r["value"], "result"), "ValueReason": cell(r["value"], "reason"),
            "CitedReports": ", ".join(cell(r["citation"], "cited") or []),
            "CitationCheck": cell(r["citation"], "result"), "CitationReason": cell(r["citation"], "reason"),
            "QueriedModels": ", ".join(cell(r["model"], "models") or []),
            "ModelCheck": cell(r["model"], "result"), "ModelReason": cell(r["model"], "reason"),
            "Verdict": r["verdict"], "LatencyMs": a.get("latency_ms")}


def query_row(run_id, r, q):
    return {"RunId": run_id, "QuestionId": r["question"]["id"], "Attempt": r["answer"].get("attempt", 1),
            "Timestamp": q.get("timestamp", ""), "SemanticModel": q.get("semantic_model", ""),
            "Dax": " ".join((q.get("dax") or "").split()), "DurationMs": q.get("duration_ms")}


if __name__ == "__main__":
    main()
