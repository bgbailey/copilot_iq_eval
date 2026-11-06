"""Simulated tenant for offline runs, tests and demo data.

A seeded, deterministic stand-in for Copilot Chat, Fabric IQ's DAX, workspace
monitoring (with ingestion delay), the judge model and Foundry Evaluations.
Nothing here calls a network. Behaviour per question comes from a 'profile'
so a series of runs tells a story (baseline -> improving -> tuned).

Simulated data is labelled Surface = "simulated" wherever it is published.
"""
import random
import uuid
from datetime import timedelta
from urllib.parse import quote

from .chat import AskResult, ChatTurn, parse_json_block
from .foundry import BUILTIN_EVALUATORS, CODE_EVALUATORS, code_bundle, foundry_checks, parse_output_items
from .scorers import PASS, normalize_name, score_value, split_list
from .trace import WATERMARK_TAG, FabricQuery, watermark_dax

SCENARIOS = ("correct", "rounded", "no_citation", "decoy", "decoy_doc", "wrong_model", "document", "clarify", "error")

# Per-question behaviour for the bundled Contoso golden set. Unknown questions are mostly "correct".
PROFILES = {
    "baseline": {"Q01": "correct", "Q02": "decoy", "Q03": "wrong_model", "Q04": "rounded", "Q05": "correct",
                 "Q06": "document", "Q07": "clarify", "Q08": "decoy_doc"},
    "improving": {"Q01": "correct", "Q02": "correct", "Q03": "wrong_model", "Q04": "rounded", "Q05": "correct",
                  "Q06": "no_citation", "Q07": "correct", "Q08": "decoy"},
    "tuned": {"Q01": "correct", "Q02": "correct", "Q03": "correct", "Q04": "rounded", "Q05": "correct",
              "Q06": "correct", "Q07": "correct", "Q08": ["correct", "correct", "decoy"]},
}
PROFILE_ORDER = ("baseline", "improving", "tuned")
DEFAULT_MIX = ["correct"] * 7 + ["rounded", "no_citation", "decoy", "clarify"]

MEASURE_WORDS = {"currency": "revenue", "percent": "rate", "count": "total", "number": "value"}


def _uid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "cfeval-demo/" + "/".join(parts)))


WORKSPACE_ID = _uid("workspace")


def report_url(name):
    return "https://app.powerbi.com/groups/%s/reports/%s" % (WORKSPACE_ID, _uid("report", normalize_name(name)))


def document_url(name):
    return "https://contoso.sharepoint.com/sites/finance/Shared%%20Documents/%s.docx" % quote(name)


def citation(name, url):
    return {"attributionType": "citation", "providerDisplayName": name, "attributionSource": "model",
            "seeMoreWebUrl": url, "imageWebUrl": None, "imageFavIcon": None, "imageWidth": 0, "imageHeight": 0}


def fmt_value(value, unit, style="exact"):
    if value is None:
        return "n/a"
    if unit == "currency":
        if style == "rounded" and abs(value) >= 1e6:
            return "about $%.1f million" % (value / 1e6)
        return "$%.2fM" % (value / 1e6) if abs(value) >= 1e6 else "${:,.0f}".format(value)
    if unit == "percent":
        return "%.1f%%" % value
    if unit == "count":
        return "%.1fK" % (value / 1e3) if style == "rounded" and abs(value) >= 1e4 else "{:,.0f}".format(value)
    return ("%.1f" % value) if style != "exact" else ("%g" % value)


class MockWorld:
    """Copilot Chat + Fabric IQ + workspace monitoring, on a simulated clock."""

    def __init__(self, clock, questions, profile="baseline", seed=7, test_user="eval.tester@contoso.com",
                 harness_user="eval.admin@contoso.com", ingest_delay_s=(45.0, 150.0), error_rate=0.0):
        self.clock = clock
        self.questions = {q.question.strip(): q for q in questions}
        self.profile = profile
        self.rng = random.Random("%s|%s" % (seed, profile))
        self.test_user = test_user
        self.harness_user = harness_user
        self.ingest_delay_s = ingest_delay_s
        self.error_rate = error_rate
        self.logs = []          # workspace monitoring rows (with visible_at)
        self.asked = {}         # question id -> times asked

    # ---- scenario choice --------------------------------------------------------------------------
    def scenario_for(self, q):
        n = self.asked.get(q.id, 0)
        self.asked[q.id] = n + 1
        if self.error_rate and self.rng.random() < self.error_rate:
            return "error"
        plan = PROFILES.get(self.profile, {}).get(q.id)
        if plan is None:
            return self.rng.choice(DEFAULT_MIX)
        if isinstance(plan, list):
            return self.rng.choice(plan)
        return plan

    # ---- workspace monitoring -----------------------------------------------------------------------
    def log_query(self, when, model, dax, duration_ms, user=None):
        delay = self.rng.uniform(*self.ingest_delay_s)
        self.logs.append({
            "query": FabricQuery(query_time=when, workspace_id=WORKSPACE_ID, item_id=_uid("model", normalize_name(model)),
                                 item_name=model, application_name="PowerBI", operation_name="QueryEnd",
                                 duration_ms=round(duration_ms, 1), dax=dax,
                                 correlation_id=str(uuid.UUID(int=self.rng.getrandbits(128)))),
            "user": user or self.test_user, "visible_at": when + timedelta(seconds=delay)})

    def visible(self):
        now = self.clock.now()
        return [row for row in self.logs if row["visible_at"] <= now]

    # ---- Copilot Chat ------------------------------------------------------------------------------
    def ask(self, question, explain_mode="followup"):
        q = self.questions.get(question.strip())
        started = self.clock.now()
        result = AskResult(question=question, started=started)
        if q is None:
            self.clock.advance(self.rng.uniform(6, 10))
            text = "I couldn't find data to answer that question."
            result.conversation_id = str(uuid.UUID(int=self.rng.getrandbits(128)))
            result.answer = ChatTurn(text, [], started, self.clock.now(), 0.0)
            result.ended = self.clock.now()
            return result
        scenario = self.scenario_for(q)
        if scenario == "error":
            self.clock.advance(self.rng.uniform(1.5, 4.0))
            result.error = "Copilot Chat API returned 429: Too many requests (retries exhausted)"
            result.http_status = 429
            result.ended = self.clock.now()
            return result
        spec = self.render(q, scenario)
        result.conversation_id = str(uuid.UUID(int=self.rng.getrandbits(128)))
        latency = self.rng.uniform(*spec["latency"])
        offset = self.rng.uniform(2.0, 5.0)
        for model, dax in spec["dax"]:
            duration = self.rng.uniform(60, 1400)
            offset += duration / 1000.0 + self.rng.uniform(0.2, 1.5)
            self.log_query(started + timedelta(seconds=min(offset, latency - 0.5)), model, dax, duration)
        self.clock.advance(latency)
        text = spec["answer"]
        if explain_mode == "inline":
            text += " " + spec["inline"]
        raw = {"id": result.conversation_id, "messages": [
            {"@odata.type": "#microsoft.graph.copilotConversationResponseMessage", "text": question, "attributions": []},
            {"@odata.type": "#microsoft.graph.copilotConversationResponseMessage", "text": text,
             "attributions": spec["attributions"]}]}
        result.answer = ChatTurn(text, spec["attributions"], started, self.clock.now(), round(latency * 1000, 1), raw)
        if explain_mode == "followup":
            why_start = self.clock.now()
            why_latency = self.rng.uniform(5.0, 11.0)
            for model, dax in spec["why_dax"]:
                self.log_query(why_start + timedelta(seconds=self.rng.uniform(1.5, 3.0)), model, dax,
                               self.rng.uniform(40, 600))
            self.clock.advance(why_latency)
            result.explain = ChatTurn(spec["why"], [], why_start, self.clock.now(), round(why_latency * 1000, 1))
            result.why_text = spec["why"]
            result.why_json = parse_json_block(spec["why"])
        result.ended = self.clock.now()
        return result

    def render(self, q, scenario):
        value, unit = q.expected_value, q.unit
        artifact, model = q.expected_artifact or q.model, q.model
        dax = q.reference_dax or 'EVALUATE ROW("v", [%s])' % (q.category or "Value")
        decoys = split_list(q.decoys)
        measure = MEASURE_WORDS.get(unit, "value")
        spec = {"latency": (8.0, 16.0), "dax": [(model, dax)], "why_dax": [], "attributions": [citation(artifact, report_url(artifact))]}
        why = {"sources": [artifact], "semantic_model": model, "filters": "as asked", "reasoning": ""}

        if scenario in ("correct", "rounded", "no_citation"):
            shown = fmt_value(value, unit, "rounded" if scenario == "rounded" else "exact")
            spec["answer"] = "%s: %s, based on the %s report." % (q.question.rstrip("?"), shown, artifact)
            why["reasoning"] = "Queried the %s semantic model behind the %s report." % (model, artifact)
            if scenario == "no_citation":
                spec["attributions"] = []
                spec["answer"] = "%s: %s." % (q.question.rstrip("?"), shown)
            if self.rng.random() < 0.35:
                spec["dax"].append((model, "DEFINE VAR _t = %s\nEVALUATE _t" % dax.replace("EVALUATE ", "")))
        elif scenario in ("decoy", "decoy_doc"):
            docs = [d for d in decoys if _looks_like_document(d)]
            reports = [d for d in decoys if not _looks_like_document(d)]
            pool = (docs or reports) if scenario == "decoy_doc" else (reports or docs)
            decoy = pool[0] if pool else "Sales Sandbox"
            wrong = value * self.rng.choice((0.93, 0.96, 1.04)) if value is not None else None
            if _looks_like_document(decoy):
                spec["attributions"] = [citation(decoy, document_url(decoy))]
                spec["dax"] = []
                spec["answer"] = "According to %s, the %s is %s." % (decoy, measure, fmt_value(wrong, unit))
                why.update(sources=[decoy], semantic_model="", reasoning="Found the figure in a document in SharePoint.")
            else:
                spec["attributions"] = [citation(decoy, report_url(decoy))]
                spec["dax"] = [(decoy, dax)]
                spec["answer"] = "%s: %s, from the %s report." % (q.question.rstrip("?"), fmt_value(wrong, unit), decoy)
                why.update(sources=[decoy], semantic_model=decoy, reasoning="The %s report had the most recent data." % decoy)
        elif scenario == "wrong_model":
            other = "Sales Analytics" if normalize_name(model) != normalize_name("Sales Analytics") else "Finance"
            wrong = value * 1.075 if value is not None else None
            spec["attributions"] = [citation(other, report_url(other))]
            spec["dax"] = [(other, dax.replace("Net Revenue", "Gross Revenue"))]
            spec["answer"] = "%s: %s, based on the %s report." % (q.question.rstrip("?"), fmt_value(wrong, unit), other)
            why.update(sources=[other], semantic_model=other, reasoning="Used the %s measure in %s." % (measure, other))
        elif scenario == "document":
            doc = "%s monthly review" % artifact
            stale = value * 0.978 if value is not None else None
            spec["attributions"] = [citation(doc, document_url(doc))]
            spec["dax"] = []
            spec["latency"] = (11.0, 20.0)
            spec["answer"] = "The %s document reports %s." % (doc, fmt_value(stale, unit))
            why.update(sources=[doc], semantic_model="", reasoning="Found the number in a recent review document.")
        elif scenario == "clarify":
            spec["attributions"] = []
            spec["dax"] = []
            spec["latency"] = (4.0, 8.0)
            spec["answer"] = "Do you mean the fiscal or the calendar year, and which business unit?"
            why.update(sources=[], semantic_model="", reasoning="The question was ambiguous, so I asked for clarification.")
        else:
            raise ValueError("unknown scenario %s" % scenario)

        spec["why"] = "```json\n%s\n```" % _json(why)
        spec["inline"] = "Source: %s." % (", ".join(why["sources"]) or "none")
        spec["scenario"] = scenario
        return spec


def _looks_like_document(name):
    low = name.lower()
    return "draft" in low or "review" in low or any(ch.isdigit() for ch in name)


def _json(value):
    import json
    return json.dumps(value, indent=2)


class MockCopilotChat:
    """Drop-in for CopilotChatClient.ask()."""

    def __init__(self, world):
        self.world = world

    def ask(self, question, explain_mode="followup"):
        return self.world.ask(question, explain_mode)


class MockMonitoringSource:
    """Drop-in for WorkspaceMonitoringSource; rows appear after a simulated ingestion delay."""

    def __init__(self, world):
        self.world = world

    def fetch(self, upn, start, end):
        rows = [r["query"] for r in self.world.visible()
                if r["user"].lower() == (upn or "").lower() and start <= r["query"].query_time <= end
                and WATERMARK_TAG not in r["query"].dax]
        return sorted(rows, key=lambda q: q.query_time)

    def latest_timestamp(self):
        rows = self.world.visible()
        return max(r["query"].query_time for r in rows) if rows else None

    def watermark_seen(self, marker, since):
        return any(marker in r["query"].dax and r["query"].query_time > since for r in self.world.visible())


class MockWatermark:
    def __init__(self, world, model="Sales Analytics"):
        self.world = world
        self.model = model

    def send(self, marker):
        self.world.log_query(self.world.clock.now(), self.model, watermark_dax(marker), 12.0, user=self.world.harness_user)


class MockJudge:
    """Deterministic stand-in for the Foundry-hosted judge model."""

    model_name = "simulated-judge"

    def judge_answer(self, q, answer):
        if not (q.expected_answer or q.expected_value is not None):
            return None
        r = score_value(answer, q.expected_value, q.unit, q.rel_tol, q.abs_tol)
        ok = r["score"] == PASS
        return {"score": 1.0 if ok else 0.0, "reason": ("matches the reference" if ok else "does not match the "
                "reference: " + r["reason"]), "raw": {"correct": ok}}

    def judge_why(self, q, answer, cited, why, models, dax):
        if not why:
            return None
        text = why.lower()
        named = [c for c in cited if c and c.lower() in text]
        raw = 5 if named and (not models or any(m.lower() in text for m in models)) else 4 if named else 2 if cited else 3
        return {"score": (raw - 1) / 4.0, "raw_score": raw, "reason": "explanation names %s" % (
            ", ".join(named) if named else "none of the cited sources"), "raw": {"score": raw}}


def _load_grade(code_text):
    namespace = {"__name__": "foundry_code_evaluator"}
    exec(compile(code_text, "<foundry-code-evaluator>", "exec"), namespace)  # noqa: S102 - our own bundled code
    return namespace["grade"]


class LocalFoundryEmulator:
    """Runs Option 2 offline: code evaluators exec the exact bundles registered in Foundry;
    prompt and built-in evaluators are simulated. Output goes through the same parser as real runs."""

    name = "foundry"

    def __init__(self, include_trace=True, include_prompt=True, include_builtin=True):
        self.include_trace = include_trace
        self.include_prompt = include_prompt
        self.include_builtin = include_builtin
        self.judge = MockJudge()

    def checks(self):
        return foundry_checks(self.include_trace, self.include_prompt, self.include_builtin)

    def run(self, rows, name):
        checks = self.checks()
        graders = {c: _load_grade(code_bundle(c)) for c in CODE_EVALUATORS if c in checks}
        items = []
        for row in rows:
            results = []
            value_ok = None
            for check in checks:
                if check in graders:
                    score = graders[check]({}, row)
                    if check == "value":
                        value_ok = score == 1.0
                    results.append({"name": check, "type": "azure_ai_evaluator", "score": score,
                                    "passed": score >= 1.0, "sample": {}})
                elif check == "judge_answer":
                    raw = 5 if value_ok else 1
                    results.append({"name": check, "score": raw, "passed": raw >= 4,
                                    "reason": "simulated grader: %s" % ("matches" if value_ok else "does not match")})
                elif check == "why":
                    named = row["cited"] and row["cited"].split("; ")[0].lower() in (row["why"] or "").lower()
                    raw = 5 if named else 2
                    results.append({"name": check, "score": raw, "passed": raw >= 4,
                                    "reason": "simulated grader: explanation %s the cited source" % (
                                        "names" if named else "doesn't name")})
                elif check in BUILTIN_EVALUATORS:
                    raw = (5 if value_ok else 2) if check == "similarity" else (4 if len(row["response"]) > 30 else 3)
                    results.append({"name": check, "score": raw, "passed": raw >= 3, "reason": "simulated"})
            items.append({"datasource_item": row, "results": results})
        return {"eval_id": "simulated", "run_id": "simulated-%s" % _uid(name)[:8], "status": "completed",
                "report_url": "", "scores": parse_output_items(items, checks)}
