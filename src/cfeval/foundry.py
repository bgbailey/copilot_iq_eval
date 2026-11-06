"""Option 2: Microsoft Foundry Evaluations is the evaluation framework.

The harness drives Copilot Chat and gathers the evidence (Foundry can't call
Copilot). Each ask becomes one row in a Foundry dataset evaluation:

* code-based evaluators run the same deterministic scorers as Option 1
  (value, artifact, semantic model) - the scorer module is bundled verbatim;
* prompt-based evaluators grade answer correctness and the 'why' (1-5);
* built-in evaluators add coherence and similarity to the reference answer.

Results get a Foundry portal report and run comparison, and are written back to
the Eventhouse so the Fabric app shows both options side by side.
"""
import hashlib
import json
import math
import time
from importlib import resources
from pathlib import Path

from .scorers import citation_artifacts

FIELDS = [
    "ask_id", "question", "response", "expected_answer", "expected_value", "unit", "rel_tol", "abs_tol",
    "expected_artifact", "artifact_aliases", "decoys", "artifacts_json", "cited", "expected_model",
    "queried_models_json", "queried_models", "trace_status", "why", "dax_preview",
]

CODE_EVALUATORS = {
    "value": ("cfeval_value_match", "score_value(item.get('response') or '', item.get('expected_value'), "
                                   "item.get('unit') or 'number', item.get('rel_tol') or '0.005', "
                                   "item.get('abs_tol') or '0')"),
    "artifact": ("cfeval_artifact_match", "score_artifact(_json.loads(item.get('artifacts_json') or '[]'), "
                                         "item.get('expected_artifact'), item.get('artifact_aliases'), "
                                         "item.get('decoys'))"),
    "model": ("cfeval_model_match", "score_model(item.get('trace_status'), "
                                   "_json.loads(item.get('queried_models_json') or '[]'), "
                                   "item.get('expected_model'), item.get('decoys'))"),
}

GRADE = """


import json as _json


def grade(sample, item):
    result = {expr}
    if result is None:
        return 0.5
    return float(result.get("score", 0.5))
"""

ANSWER_PROMPT = """Rate from 1 to 5 how correct the assistant's answer is compared with the reference answer.
5 = same value and meaning (display rounding, currency symbols, thousands separators and K/M/B scale words are fine); 3 = partly correct or imprecise; 1 = wrong value, wrong measure or no answer.

Question: {{question}}
Reference answer: {{expected_answer}}
Expected value: {{expected_value}} ({{unit}})
Assistant's answer: {{response}}

Output Format (JSON):
{
  "result": <integer from 1 to 5>,
  "reason": "<brief explanation for the score>"
}"""

WHY_PROMPT = """Rate from 1 to 5 how well the assistant's explanation of its sources agrees with the evidence.
5 = names exactly the cited sources, with filters and period consistent with the queries that ran; 3 = partly consistent or vague; 1 = contradicts the evidence or invents sources.

Question: {{question}}
Answer: {{response}}
Artifacts the assistant cited: {{cited}}
The assistant's explanation of its sources: {{why}}
Semantic models the engine queried (empty if not captured): {{queried_models}}
DAX the engine ran (truncated): {{dax_preview}}

Output Format (JSON):
{
  "result": <integer from 1 to 5>,
  "reason": "<brief explanation for the score>"
}"""

PROMPT_EVALUATORS = {
    "judge_answer": ("cfeval_answer_correctness", ANSWER_PROMPT,
                     ["question", "expected_answer", "expected_value", "unit", "response"]),
    "why": ("cfeval_why_consistency", WHY_PROMPT,
            ["question", "response", "cited", "why", "queried_models", "dax_preview"]),
}

BUILTIN_EVALUATORS = {
    "coherence": ("builtin.coherence", {"query": "{{item.question}}", "response": "{{item.response}}"}),
    "similarity": ("builtin.similarity", {"query": "{{item.question}}", "response": "{{item.response}}",
                                          "ground_truth": "{{item.expected_answer}}"}),
}
ORDINAL_CHECKS = ("judge_answer", "why", "coherence", "similarity")


EVALUATOR_NAMES = {
    "value": CODE_EVALUATORS["value"][0], "artifact": CODE_EVALUATORS["artifact"][0],
    "model": CODE_EVALUATORS["model"][0], "judge_answer": PROMPT_EVALUATORS["judge_answer"][0],
    "why": PROMPT_EVALUATORS["why"][0], "coherence": BUILTIN_EVALUATORS["coherence"][0],
    "similarity": BUILTIN_EVALUATORS["similarity"][0],
}


def foundry_checks(include_trace=True, include_prompt=True, include_builtin=True):
    checks = ["value", "artifact"] + (["model"] if include_trace else [])
    if include_prompt:
        checks += ["judge_answer", "why"]
    if include_builtin:
        checks += ["coherence", "similarity"]
    return checks


def scorers_source():
    return resources.files("cfeval").joinpath("scorers.py").read_text(encoding="utf-8")


def code_bundle(check):
    """The exact code registered as a Foundry code-based evaluator (scorers + grade())."""
    return scorers_source() + GRADE.format(expr=CODE_EVALUATORS[check][1])


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def foundry_row(q, ask, artifacts, trace):
    artifacts = citation_artifacts(artifacts)
    cited = sorted({a.get("name") or "" for a in artifacts})
    return {
        "ask_id": ask["AskId"], "question": q.question, "response": ask["Answer"] or "",
        "expected_answer": q.expected_answer or "", "expected_value": "" if q.expected_value is None
        else repr(q.expected_value), "unit": q.unit, "rel_tol": repr(q.rel_tol), "abs_tol": repr(q.abs_tol),
        "expected_artifact": q.expected_artifact, "artifact_aliases": q.artifact_aliases, "decoys": q.decoys,
        "artifacts_json": json.dumps(artifacts, ensure_ascii=False), "cited": "; ".join(cited),
        "expected_model": q.model, "queried_models_json": json.dumps(trace["models"]),
        "queried_models": "; ".join(trace["models"]), "trace_status": trace["status"],
        "why": ask["Why"] or "", "dax_preview": "\n".join(x.dax for x in trace["queries"])[:1500],
    }


def _as_dict(obj):
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "to_dict", "as_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:
                continue
    return dict(getattr(obj, "__dict__", {}))


def _first(d, *paths):
    for path in paths:
        cur = d
        for key in path.split("."):
            cur = cur.get(key) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, ""):
            return cur
    return None


def parse_output_items(items, checks):
    """Map Foundry output items to {ask_id: {check: {"score", "outcome", "reason", "raw_score"}}}."""
    out, details = {}, {}
    for raw in items:
        item = _as_dict(raw)
        source = _as_dict(item.get("datasource_item")) or {}
        ask_id = source.get("ask_id") or _first(source, "item.ask_id")
        if not ask_id:
            continue
        per = out.setdefault(ask_id, {})
        item_error = _first(item, "sample.error", "error.message")
        if not item_error and item.get("status") in ("failed", "error", "canceled", "cancelled"):
            item_error = "Foundry output item status is %s" % item["status"]
        for res in item.get("results") or []:
            r = _as_dict(res)
            name = str(r.get("name") or r.get("testing_criteria") or r.get("testing_criteria_id") or r.get("metric") or "")
            check = next((c for c in checks if any(
                name == n or name.startswith(n + "-") or name.startswith(n + "_") or name.endswith(":" + n)
                for n in (c, EVALUATOR_NAMES.get(c, c)))), None)
            if check is None:
                continue
            raw_score = r.get("score")
            error = _first(r, "error.message", "sample.error") or item_error
            if not error and r.get("status") in ("failed", "error", "canceled", "cancelled"):
                error = "Foundry criterion status is %s" % r["status"]
            reason = str(_first(r, "reason", "sample.reason", "properties.reason",
                                "sample.output_text") or "")[:1000]
            if raw_score is None and not error and reason and r.get("metric") not in (None, "", "custom_score"):
                details[(ask_id, check)] = reason
                continue
            try:
                number = float(raw_score)
                valid = not isinstance(raw_score, bool) and math.isfinite(number) and (
                    1 <= number <= 5 and number.is_integer() if check in ORDINAL_CHECKS
                    else number in (0.0, 0.5, 1.0))
            except (TypeError, ValueError, OverflowError):
                valid, number = False, None
            if error or not valid:
                message = str(error or reason or "missing or invalid Foundry score")[:1000]
                per[check] = {"score": 0.5, "outcome": "INCONCLUSIVE", "raw_score": None,
                              "reason": message, "error": message}
                continue
            score = (number - 1.0) / 4.0 if check in ORDINAL_CHECKS else number
            outcome = "INCONCLUSIVE" if score == 0.5 and check not in ORDINAL_CHECKS else (
                "PASS" if score >= 0.75 else "FAIL")
            result = {"score": round(score, 4), "raw_score": number, "outcome": outcome,
                      "reason": reason}
            if check in per and (per[check].get("error") or per[check]["score"] != result["score"]):
                message = per[check].get("error") or "conflicting Foundry results for the same ask and criterion"
                result = {"score": 0.5, "raw_score": None, "outcome": "INCONCLUSIVE",
                          "reason": message, "error": message}
            per[check] = result
    for (ask_id, check), reason in details.items():
        result = out[ask_id].get(check)
        if result is None:
            out[ask_id][check] = {"score": 0.5, "raw_score": None, "outcome": "INCONCLUSIVE",
                                  "reason": reason, "error": "Foundry returned details without a score"}
        elif not result.get("reason"):
            result["reason"] = reason
    return out


class FoundryEvaluation:
    """Registers the evaluators once, then runs one dataset evaluation per harness run."""

    name = "foundry"

    def __init__(self, project_endpoint, deployment, credential=None, project_client=None,
                 include_trace=True, include_builtin=True, include_prompt=True,
                 cache_path=".cache/foundry_evaluators.json", log=print, poll_seconds=10, timeout_seconds=1800):
        if project_client is None:
            from azure.ai.projects import AIProjectClient

            if credential is None:
                raise ValueError("Foundry needs an explicitly bound credential (or an injected project_client)")
            project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
        self.project = project_client
        self.client = project_client.get_openai_client()
        if hasattr(self.client, "with_options"):
            self.client = self.client.with_options(max_retries=0, timeout=60)
        self.project_endpoint = project_endpoint.rstrip("/")
        self.evaluators = getattr(project_client, "evaluators", None) or project_client.beta.evaluators
        self.versions = {}
        self.deployment = deployment
        self.include_trace = include_trace
        self.include_builtin = include_builtin
        self.include_prompt = include_prompt
        self.cache_path = Path(cache_path)
        self.log = log
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.last_operation = {}

    # ---- evaluator registration -------------------------------------------------------------
    def checks(self):
        return foundry_checks(self.include_trace, self.include_prompt, self.include_builtin)

    def _definitions(self):
        try:
            from azure.ai.projects.models import EvaluatorDefinitionType
            code_type, prompt_type = EvaluatorDefinitionType.CODE, EvaluatorDefinitionType.PROMPT
        except ImportError:
            code_type, prompt_type = "code", "prompt"
        defs = {}
        for check, (name, _expr) in CODE_EVALUATORS.items():
            text = code_bundle(check)
            defs[check] = (name, _hash(text), {
                "type": code_type, "code_text": text,
                "init_parameters": {"type": "object", "properties": {"deployment_name": {"type": "string"},
                                    "pass_threshold": {"type": "number"}},
                                    "required": ["deployment_name", "pass_threshold"]},
                "metrics": {"result": {"type": "continuous", "desirable_direction": "increase",
                                       "min_value": 0.0, "max_value": 1.0}},
                "data_schema": {"type": "object", "required": ["item"], "properties": {"item": {
                    "type": "object", "properties": {f: {"type": "string"} for f in FIELDS}}}},
            })
        for check, (name, prompt, fields) in PROMPT_EVALUATORS.items():
            defs[check] = (name, _hash(prompt), {
                "type": prompt_type, "prompt_text": prompt,
                "init_parameters": {"type": "object", "properties": {"deployment_name": {"type": "string"},
                                    "threshold": {"type": "number"}}, "required": ["deployment_name", "threshold"]},
                "data_schema": {"type": "object", "properties": {f: {"type": "string"} for f in fields},
                                "required": fields},
                "metrics": {"custom_prompt": {"type": "ordinal", "desirable_direction": "increase",
                                              "min_value": 1, "max_value": 5}},
            })
        return defs

    def ensure_evaluators(self):
        """Register (or re-version) custom evaluators whose definition changed."""
        try:
            from azure.ai.projects.models import EvaluatorCategory
            category = EvaluatorCategory.QUALITY
        except ImportError:
            category = "quality"
        cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        scoped = cache.setdefault("projects", {}).setdefault(self.project_endpoint, {})
        for check, (name, digest, definition) in self._definitions().items():
            if check not in self.checks():
                continue
            digest = _hash(json.dumps(definition, sort_keys=True))
            saved = scoped.get(name, {})
            version = saved.get("version") if saved.get("hash") == digest else None
            if not version:
                created = self.evaluators.create_version(name=name, evaluator_version={
                    "name": name, "categories": [category], "display_name": name.replace("_", " "),
                    "description": "Copilot x Fabric IQ eval: %s (definition %s)" % (check, digest),
                    "definition": definition,
                })
                version = _as_dict(created).get("version")
                if not version:
                    raise RuntimeError("Foundry registration returned no version for %s" % name)
                scoped[name] = {"hash": digest, "version": str(version)}
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
                self.log("Registered Foundry evaluator %s version %s (%s)" % (name, version, digest))
            remote = _as_dict(self.evaluators.get_version(name=name, version=str(version)))
            source_key = "code_text" if check in CODE_EVALUATORS else "prompt_text"
            if (_as_dict(remote.get("definition")).get(source_key) != definition[source_key]
                    or str(remote.get("version")) != str(version)):
                raise RuntimeError("Foundry source/version readback did not match %s version %s" % (name, version))
            self.versions[check] = str(version)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache, indent=2))

    def testing_criteria(self):
        crit = []
        for check in self.checks():
            if check in CODE_EVALUATORS:
                crit.append({"type": "azure_ai_evaluator", "name": check, "evaluator_name": CODE_EVALUATORS[check][0],
                             "evaluator_version": self.versions[check],
                             "initialization_parameters": {"deployment_name": self.deployment, "pass_threshold": 1.0}})
            elif check in PROMPT_EVALUATORS:
                name, _prompt, fields = PROMPT_EVALUATORS[check]
                crit.append({"type": "azure_ai_evaluator", "name": check, "evaluator_name": name,
                             "evaluator_version": self.versions[check],
                             "data_mapping": {f: "{{item.%s}}" % f for f in fields},
                             "initialization_parameters": {"deployment_name": self.deployment, "threshold": 4}})
            elif check in BUILTIN_EVALUATORS:
                name, mapping = BUILTIN_EVALUATORS[check]
                crit.append({"type": "azure_ai_evaluator", "name": check, "evaluator_name": name,
                             "initialization_parameters": {"model": self.deployment}, "data_mapping": mapping})
        return crit

    # ---- run ---------------------------------------------------------------------------------
    def run(self, rows, name):
        self.last_operation = {"project_endpoint": self.project_endpoint, "status": "registering"}
        self.ensure_evaluators()
        evaluation = self.client.evals.create(
            name=name,
            data_source_config={"type": "custom", "item_schema": {
                "type": "object", "properties": {f: {"type": "string"} for f in FIELDS},
                "required": ["ask_id", "question", "response"]}},
            testing_criteria=self.testing_criteria(),
        )
        operation_path = self.cache_path.parent / ("foundry-operation-%s.json" % _hash(str(evaluation.id)))
        operation = {"project_endpoint": self.project_endpoint, "eval_id": evaluation.id, "run_id": "",
                     "status": "submitting", "evaluator_versions": dict(self.versions),
                     "operation_path": str(operation_path)}
        self.last_operation = operation
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        run = self.client.evals.runs.create(eval_id=evaluation.id, name=name, data_source={
            "type": "jsonl", "source": {"type": "file_content", "content": [{"item": r} for r in rows]}})
        operation.update(run_id=run.id, status=run.status)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while run.status not in ("completed", "failed", "canceled", "cancelled"):
            if time.monotonic() > deadline:
                raise TimeoutError("Foundry evaluation run %s still %s after %ss" % (run.id, run.status,
                                                                                    self.timeout_seconds))
            time.sleep(self.poll_seconds)
            run = self.client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
            operation["status"] = run.status
        operation.update(status=run.status, report_url=getattr(run, "report_url", "") or "",
                         service_error=_as_dict(getattr(run, "error", None)))
        if run.status != "completed":
            detail = _first(operation["service_error"], "message") or "service returned no error detail"
            operation["error"] = "Foundry run %s: %s" % (run.status, detail)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        items = list(self.client.evals.runs.output_items.list(run_id=run.id, eval_id=evaluation.id))
        operation["output_items"] = len(items)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        return dict(operation, scores=parse_output_items(items, self.checks()))
