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

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from .scorers import citation_artifacts

FIELDS = [
    "ask_id",
    "question",
    "response",
    "expected_answer",
    "expected_value",
    "unit",
    "rel_tol",
    "abs_tol",
    "expected_artifact",
    "artifact_aliases",
    "decoys",
    "artifacts_json",
    "cited",
    "expected_model",
    "queried_models_json",
    "queried_models",
    "trace_status",
    "why",
    "dax_preview",
    "display_tol",
    "case_type",
    "expect_json",
    "currency",
    "expected_artifact_id",
    "routing_evidence",
    "correlation_confidence",
]

CODE_EVALUATORS = {
    "value": (
        "cfeval_value_match",
        "score_value("
        "item.get('response') or '', "
        "None if item.get('expected_value') in (None, '') else float(item.get('expected_value')), "
        "item.get('unit') or 'number', "
        "0.005 if item.get('rel_tol') in (None, '') else float(item.get('rel_tol')), "
        "0.0 if item.get('abs_tol') in (None, '') else float(item.get('abs_tol')), "
        "display_tol=0.01 if item.get('display_tol') in (None, '') else float(item.get('display_tol')), "
        "case_type=item.get('case_type') or 'scalar', "
        "expect=_json.loads(item.get('expect_json') or 'null'), "
        "expected_currency=item.get('currency') or '')",
    ),
    "artifact": (
        "cfeval_artifact_match",
        "score_artifact("
        "_json.loads(item.get('artifacts_json') or '[]'), "
        "item.get('expected_artifact'), "
        "item.get('artifact_aliases'), "
        "item.get('decoys'), "
        "expected_id=item.get('expected_artifact_id') or '')",
    ),
    "model": (
        "cfeval_model_match",
        "score_model("
        "item.get('trace_status'), "
        "_json.loads(item.get('queried_models_json') or '[]'), "
        "item.get('expected_model'), "
        "item.get('decoys'), "
        "routing_evidence=item.get('routing_evidence') or '', "
        "correlation_confidence=item.get('correlation_confidence') or 'none')",
    ),
}

GRADE = """


import json as _json


def grade(sample, item):
    result = {expr}
    if result is None:
        return 0.5
    return float(result.get("score", 0.5))
"""

ANSWER_PROMPT = (
    "Rate from 1 to 5 how correct the assistant's answer is compared with the reference answer.\n"
    "5 = same value and meaning (display rounding, currency symbols, thousands separators and K/M/B scale words "
    "are fine); 3 = partly correct or imprecise; 1 = wrong value, wrong measure or no answer.\n\n"
    "Question: {{question}}\n"
    "Reference answer: {{expected_answer}}\n"
    "Expected value: {{expected_value}} ({{unit}})\n"
    "Assistant's answer: {{response}}\n\n"
    "Output Format (JSON):\n"
    "{\n"
    '  "result": <integer from 1 to 5>,\n'
    '  "reason": "<brief explanation for the score>"\n'
    "}"
)

WHY_PROMPT = (
    "Rate from 1 to 5 how well the assistant's explanation of its sources agrees with the evidence.\n"
    "5 = names exactly the cited sources, with filters and period consistent with the queries that ran; "
    "3 = partly consistent or vague; 1 = contradicts the evidence or invents sources.\n\n"
    "Question: {{question}}\n"
    "Answer: {{response}}\n"
    "Artifacts the assistant cited: {{cited}}\n"
    "The assistant's explanation of its sources: {{why}}\n"
    "Semantic models the engine queried (empty if not captured): {{queried_models}}\n"
    "DAX the engine ran (truncated): {{dax_preview}}\n\n"
    "Output Format (JSON):\n"
    "{\n"
    '  "result": <integer from 1 to 5>,\n'
    '  "reason": "<brief explanation for the score>"\n'
    "}"
)

PROMPT_EVALUATORS: dict[str, tuple[str, str, list[str]]] = {
    "judge_answer": (
        "cfeval_answer_correctness",
        ANSWER_PROMPT,
        ["question", "expected_answer", "expected_value", "unit", "response"],
    ),
    "why": (
        "cfeval_why_consistency",
        WHY_PROMPT,
        ["question", "response", "cited", "why", "queried_models", "dax_preview"],
    ),
}

BUILTIN_EVALUATORS: dict[str, tuple[str, dict[str, str]]] = {
    "coherence": ("builtin.coherence", {"query": "{{item.question}}", "response": "{{item.response}}"}),
    "similarity": (
        "builtin.similarity",
        {
            "query": "{{item.question}}",
            "response": "{{item.response}}",
            "ground_truth": "{{item.expected_answer}}",
        },
    ),
}
ORDINAL_CHECKS = ("judge_answer", "why", "coherence", "similarity")


EVALUATOR_NAMES = {
    "value": CODE_EVALUATORS["value"][0],
    "artifact": CODE_EVALUATORS["artifact"][0],
    "model": CODE_EVALUATORS["model"][0],
    "judge_answer": PROMPT_EVALUATORS["judge_answer"][0],
    "why": PROMPT_EVALUATORS["why"][0],
    "coherence": BUILTIN_EVALUATORS["coherence"][0],
    "similarity": BUILTIN_EVALUATORS["similarity"][0],
}


def foundry_checks(
    include_trace: bool = True,
    include_prompt: bool = True,
    include_builtin: bool = True,
) -> list[str]:
    checks = ["value", "artifact"] + (["model"] if include_trace else [])
    if include_prompt:
        checks += ["judge_answer", "why"]
    if include_builtin:
        checks += ["coherence", "similarity"]
    return checks


def scorers_source() -> str:
    raw = resources.files("cfeval").joinpath("scorers.py").read_text(encoding="utf-8")
    return re.sub(r"(?m)^\s*from\s+\.[A-Za-z0-9_.]*\s+import\s+.*$\n?", "", raw)


def code_bundle(check: str) -> str:
    """The exact code registered as a Foundry code-based evaluator (scorers + grade())."""
    return scorers_source() + GRADE.format(expr=CODE_EVALUATORS[check][1])


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _q_attr(q: Any, name: str, default: Any = None) -> Any:
    if isinstance(q, Mapping):
        return q.get(name, default)
    return getattr(q, name, default)


def _str_list_field(val: Any) -> str:
    if isinstance(val, (list, tuple)):
        return "; ".join(str(x) for x in val if str(x).strip())
    return str(val or "")


def foundry_row(
    q: Any,
    ask: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any],
) -> dict[str, str]:
    cited_arts = citation_artifacts(artifacts)
    cited = sorted({str(a.get("name") or "") for a in cited_arts if a.get("name")})

    expected_val = _q_attr(q, "expected_value")
    rel_tol = _q_attr(q, "rel_tol")
    abs_tol = _q_attr(q, "abs_tol")
    display_tol = _q_attr(q, "display_tol")
    expect_obj = _q_attr(q, "expect")
    expected_model = _q_attr(q, "model")
    if not expected_model:
        expected_model = _q_attr(q, "expected_model") or _q_attr(q, "expected_artifact") or ""

    raw_queries = trace.get("queries") or []
    dax_parts: list[str] = []
    inferred_models: set[str] = set()
    for q_item in raw_queries:
        if isinstance(q_item, Mapping):
            dax_text = str(q_item.get("Dax") or q_item.get("dax") or "")
            item_name = str(q_item.get("ItemName") or q_item.get("item_name") or "")
        else:
            dax_text = str(getattr(q_item, "dax", "") or "")
            item_name = str(getattr(q_item, "item_name", "") or "")
        if dax_text:
            dax_parts.append(dax_text)
        if item_name:
            inferred_models.add(item_name)

    models_raw = trace.get("models")
    models = sorted(str(m) for m in models_raw if m) if models_raw is not None else sorted(inferred_models)

    return {
        "ask_id": str(ask.get("AskId") or ""),
        "question": str(_q_attr(q, "question") or ask.get("Question") or ""),
        "response": str(ask.get("Answer") or ""),
        "expected_answer": str(_q_attr(q, "expected_answer") or ""),
        "expected_value": "" if expected_val is None else repr(expected_val),
        "unit": str(_q_attr(q, "unit") or ""),
        "rel_tol": repr(0.005 if rel_tol is None else rel_tol),
        "abs_tol": repr(0.0 if abs_tol is None else abs_tol),
        "display_tol": repr(0.01 if display_tol is None else display_tol),
        "case_type": str(_q_attr(q, "case_type") or "scalar"),
        "expect_json": "" if expect_obj is None else json.dumps(expect_obj, ensure_ascii=False, sort_keys=True),
        "currency": str(_q_attr(q, "currency") or ""),
        "expected_artifact": str(_q_attr(q, "expected_artifact") or ""),
        "expected_artifact_id": str(_q_attr(q, "expected_artifact_id") or ""),
        "artifact_aliases": _str_list_field(_q_attr(q, "artifact_aliases")),
        "decoys": _str_list_field(_q_attr(q, "decoys")),
        "artifacts_json": json.dumps(cited_arts, ensure_ascii=False),
        "cited": "; ".join(cited),
        "expected_model": str(expected_model),
        "queried_models_json": json.dumps(models),
        "queried_models": "; ".join(models),
        "trace_status": str(trace.get("status") or ""),
        "routing_evidence": str(trace.get("routing_evidence") or ""),
        "correlation_confidence": str(trace.get("correlation_confidence") or "none"),
        "why": str(ask.get("Why") or ""),
        "dax_preview": "\n".join(dax_parts)[:1500],
    }


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "to_dict", "as_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                res = fn()
                if isinstance(res, dict):
                    return res
            except TypeError:
                continue
    return dict(getattr(obj, "__dict__", {}))


def _first(d: Any, *paths: str) -> Any:
    for path in paths:
        cur = d
        for key in path.split("."):
            cur = cur.get(key) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, ""):
            return cur
    return None


def parse_output_items(items: Iterable[Any], checks: Sequence[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Map Foundry output items to {ask_id: {check: {"score", "outcome", "reason", "raw_score"}}}."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    details: dict[tuple[str, str], str] = {}
    for raw in items:
        item = _as_dict(raw)
        source = _as_dict(item.get("datasource_item")) or {}
        ask_id = str(source.get("ask_id") or _first(source, "item.ask_id") or "")
        if not ask_id:
            continue
        per = out.setdefault(ask_id, {})
        item_error = _first(item, "sample.error", "error.message")
        if not item_error and item.get("status") in ("failed", "error", "canceled", "cancelled"):
            item_error = "Foundry output item status is %s" % item["status"]
        for res in item.get("results") or []:
            r = _as_dict(res)
            name = str(
                r.get("name") or r.get("testing_criteria") or r.get("testing_criteria_id") or r.get("metric") or ""
            )
            check = next(
                (
                    c
                    for c in checks
                    if any(
                        name == n or name.startswith(n + "-") or name.startswith(n + "_") or name.endswith(":" + n)
                        for n in (c, EVALUATOR_NAMES.get(c, c))
                    )
                ),
                None,
            )
            if check is None:
                continue
            raw_score = r.get("score")
            error = _first(r, "error.message", "sample.error") or item_error
            if not error and r.get("status") in ("failed", "error", "canceled", "cancelled"):
                error = "Foundry criterion status is %s" % r["status"]
            reason = str(_first(r, "reason", "sample.reason", "properties.reason", "sample.output_text") or "")[:1000]
            if raw_score is None and not error and reason and r.get("metric") not in (None, "", "custom_score"):
                details[(ask_id, check)] = reason
                continue
            number = 0.0
            try:
                if raw_score is None or isinstance(raw_score, bool):
                    valid = False
                else:
                    number = float(raw_score)
                    valid = math.isfinite(number) and (
                        1 <= number <= 5 and number.is_integer()
                        if check in ORDINAL_CHECKS
                        else number in (0.0, 0.5, 1.0)
                    )
            except (TypeError, ValueError, OverflowError):
                valid = False
            if error or not valid:
                message = str(error or reason or "missing or invalid Foundry score")[:1000]
                per[check] = {
                    "score": 0.5,
                    "outcome": "INCONCLUSIVE",
                    "raw_score": None,
                    "reason": message,
                    "error": message,
                }
                continue
            score = (number - 1.0) / 4.0 if check in ORDINAL_CHECKS else number
            outcome = (
                "INCONCLUSIVE"
                if score == 0.5 and check not in ORDINAL_CHECKS
                else ("PASS" if score >= 0.75 else "FAIL")
            )
            result: dict[str, Any] = {
                "score": round(score, 4),
                "raw_score": number,
                "outcome": outcome,
                "reason": reason,
            }
            if check in per and (per[check].get("error") or per[check]["score"] != result["score"]):
                message = per[check].get("error") or "conflicting Foundry results for the same ask and criterion"
                result = {
                    "score": 0.5,
                    "raw_score": None,
                    "outcome": "INCONCLUSIVE",
                    "reason": message,
                    "error": message,
                }
            per[check] = result
    for (ask_id, check), reason in details.items():
        existing = out[ask_id].get(check)
        if existing is None:
            out[ask_id][check] = {
                "score": 0.5,
                "raw_score": None,
                "outcome": "INCONCLUSIVE",
                "reason": reason,
                "error": "Foundry returned details without a score",
            }
        elif not existing.get("reason"):
            existing["reason"] = reason
    return out


class FoundryEvaluation:
    """Registers the evaluators once, then runs one dataset evaluation per harness run."""

    name = "foundry"

    def __init__(
        self,
        project_endpoint: str,
        deployment: str,
        credential: Any = None,
        project_client: Any = None,
        include_trace: bool = True,
        include_builtin: bool = True,
        include_prompt: bool = True,
        cache_path: str | Path = ".cache/foundry_evaluators.json",
        log: Callable[[str], Any] = print,
        poll_seconds: float = 10,
        timeout_seconds: float = 1800,
    ) -> None:
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
        self.versions: dict[str, str] = {}
        self.deployment = deployment
        self.include_trace = include_trace
        self.include_builtin = include_builtin
        self.include_prompt = include_prompt
        self.cache_path = Path(cache_path)
        self.log = log
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.last_operation: dict[str, Any] = {}

    # ---- evaluator registration -------------------------------------------------------------
    def checks(self) -> list[str]:
        return foundry_checks(self.include_trace, self.include_prompt, self.include_builtin)

    def _definitions(self) -> dict[str, tuple[str, str, dict[str, Any]]]:
        try:
            import azure.ai.projects.models as _proj_models

            _edt = getattr(_proj_models, "EvaluatorDefinitionType", None)
            code_type: Any = _edt.CODE if _edt is not None else "code"
            prompt_type: Any = _edt.PROMPT if _edt is not None else "prompt"
        except ImportError:
            code_type, prompt_type = "code", "prompt"
        defs: dict[str, tuple[str, str, dict[str, Any]]] = {}
        for check, (name, _expr) in CODE_EVALUATORS.items():
            text = code_bundle(check)
            defs[check] = (
                name,
                _hash(text),
                {
                    "type": code_type,
                    "code_text": text,
                    "init_parameters": {
                        "type": "object",
                        "properties": {
                            "deployment_name": {"type": "string"},
                            "pass_threshold": {"type": "number"},
                        },
                        "required": ["deployment_name", "pass_threshold"],
                    },
                    "metrics": {
                        "result": {
                            "type": "continuous",
                            "desirable_direction": "increase",
                            "min_value": 0.0,
                            "max_value": 1.0,
                        }
                    },
                    "data_schema": {
                        "type": "object",
                        "required": ["item"],
                        "properties": {
                            "item": {
                                "type": "object",
                                "properties": {f: {"type": "string"} for f in FIELDS},
                            }
                        },
                    },
                },
            )
        for check, (name, prompt, fields) in PROMPT_EVALUATORS.items():
            defs[check] = (
                name,
                _hash(prompt),
                {
                    "type": prompt_type,
                    "prompt_text": prompt,
                    "init_parameters": {
                        "type": "object",
                        "properties": {
                            "deployment_name": {"type": "string"},
                            "threshold": {"type": "number"},
                        },
                        "required": ["deployment_name", "threshold"],
                    },
                    "data_schema": {
                        "type": "object",
                        "properties": {f: {"type": "string"} for f in fields},
                        "required": fields,
                    },
                    "metrics": {
                        "custom_prompt": {
                            "type": "ordinal",
                            "desirable_direction": "increase",
                            "min_value": 1,
                            "max_value": 5,
                        }
                    },
                },
            )
        return defs

    def ensure_evaluators(self) -> None:
        """Register (or re-version) custom evaluators whose definition changed."""
        try:
            import azure.ai.projects.models as _proj_models

            _cat = getattr(_proj_models, "EvaluatorCategory", None)
            category: Any = _cat.QUALITY if _cat is not None else "quality"
        except ImportError:
            category = "quality"
        cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}
        scoped = cache.setdefault("projects", {}).setdefault(self.project_endpoint, {})
        for check, (name, digest, definition) in self._definitions().items():
            if check not in self.checks():
                continue
            digest = _hash(json.dumps(definition, sort_keys=True))
            saved = scoped.get(name, {})
            version = saved.get("version") if saved.get("hash") == digest else None
            if not version:
                created = self.evaluators.create_version(
                    name=name,
                    evaluator_version={
                        "name": name,
                        "categories": [category],
                        "display_name": name.replace("_", " "),
                        "description": "Copilot x Fabric IQ eval: %s (definition %s)" % (check, digest),
                        "definition": definition,
                    },
                )
                version = _as_dict(created).get("version")
                if not version:
                    raise RuntimeError("Foundry registration returned no version for %s" % name)
                scoped[name] = {"hash": digest, "version": str(version)}
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
                self.log("Registered Foundry evaluator %s version %s (%s)" % (name, version, digest))
            remote = _as_dict(self.evaluators.get_version(name=name, version=str(version)))
            source_key = "code_text" if check in CODE_EVALUATORS else "prompt_text"
            if _as_dict(remote.get("definition")).get(source_key) != definition[source_key] or str(
                remote.get("version")
            ) != str(version):
                raise RuntimeError("Foundry source/version readback did not match %s version %s" % (name, version))
            self.versions[check] = str(version)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    def testing_criteria(self) -> list[dict[str, Any]]:
        crit: list[dict[str, Any]] = []
        for check in self.checks():
            if check in CODE_EVALUATORS:
                crit.append(
                    {
                        "type": "azure_ai_evaluator",
                        "name": check,
                        "evaluator_name": CODE_EVALUATORS[check][0],
                        "evaluator_version": self.versions[check],
                        "initialization_parameters": {"deployment_name": self.deployment, "pass_threshold": 1.0},
                    }
                )
            elif check in PROMPT_EVALUATORS:
                name, _prompt, fields = PROMPT_EVALUATORS[check]
                crit.append(
                    {
                        "type": "azure_ai_evaluator",
                        "name": check,
                        "evaluator_name": name,
                        "evaluator_version": self.versions[check],
                        "data_mapping": {f: "{{item.%s}}" % f for f in fields},
                        "initialization_parameters": {"deployment_name": self.deployment, "threshold": 4},
                    }
                )
            elif check in BUILTIN_EVALUATORS:
                name, mapping = BUILTIN_EVALUATORS[check]
                crit.append(
                    {
                        "type": "azure_ai_evaluator",
                        "name": check,
                        "evaluator_name": name,
                        "initialization_parameters": {"model": self.deployment},
                        "data_mapping": mapping,
                    }
                )
        return crit

    # ---- run ---------------------------------------------------------------------------------
    def run(self, rows: Sequence[Mapping[str, Any]], name: str) -> dict[str, Any]:
        self.last_operation = {"project_endpoint": self.project_endpoint, "status": "registering"}
        self.ensure_evaluators()
        evaluation = self.client.evals.create(
            name=name,
            data_source_config={
                "type": "custom",
                "item_schema": {
                    "type": "object",
                    "properties": {f: {"type": "string"} for f in FIELDS},
                    "required": ["ask_id", "question", "response"],
                },
            },
            testing_criteria=self.testing_criteria(),
        )
        operation_path = self.cache_path.parent / ("foundry-operation-%s.json" % _hash(str(evaluation.id)))
        operation: dict[str, Any] = {
            "project_endpoint": self.project_endpoint,
            "eval_id": evaluation.id,
            "run_id": "",
            "status": "submitting",
            "evaluator_versions": dict(self.versions),
            "operation_path": str(operation_path),
        }
        self.last_operation = operation
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        run = self.client.evals.runs.create(
            eval_id=evaluation.id,
            name=name,
            data_source={
                "type": "jsonl",
                "source": {"type": "file_content", "content": [{"item": dict(r)} for r in rows]},
            },
        )
        operation.update(run_id=run.id, status=run.status)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while run.status not in ("completed", "failed", "canceled", "cancelled"):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Foundry evaluation run %s still %s after %ss" % (run.id, run.status, self.timeout_seconds)
                )
            time.sleep(self.poll_seconds)
            run = self.client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
            operation["status"] = run.status
        operation.update(
            status=run.status,
            report_url=getattr(run, "report_url", "") or "",
            service_error=_as_dict(getattr(run, "error", None)),
        )
        if run.status != "completed":
            detail = _first(operation["service_error"], "message") or "service returned no error detail"
            operation["error"] = "Foundry run %s: %s" % (run.status, detail)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        items = list(self.client.evals.runs.output_items.list(run_id=run.id, eval_id=evaluation.id))
        operation["output_items"] = len(items)
        operation_path.write_text(json.dumps(operation, indent=2), encoding="utf-8")
        return dict(operation, scores=parse_output_items(items, self.checks()))
