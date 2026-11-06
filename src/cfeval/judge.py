"""Option 1 judge: a model deployed in Microsoft Foundry grades what code can't.

Deterministic scorers decide value, routing and DAX checks. The judge adds two
AI-graded checks: is the answer correct against the reference answer, and is
Copilot's own explanation of its sources consistent with the evidence.
"""
import json

from .chat import parse_json_block

SYSTEM = "You are a strict, consistent evaluator. Reply with a single JSON object and nothing else."

ANSWER_PROMPT = """Grade whether the assistant answered the business question correctly.
Question: {question}
Reference answer: {expected_answer}
Expected value: {expected_value} ({unit}). Treat values as equal when they differ only by display rounding, currency symbols, thousands separators or scale words (K, M, B), or within a relative tolerance of {rel_tol}.
Assistant's answer: {answer}
Reply with JSON: {{"correct": true or false, "reason": "<one sentence>"}}"""

WHY_PROMPT = """Check whether the assistant's explanation of its sources agrees with the evidence.
Question: {question}
Answer: {answer}
Artifacts the assistant cited: {cited}
The assistant's explanation of its sources: {why}
Semantic models the analytics engine actually queried (empty if not captured): {models}
DAX the engine ran (truncated): {dax}
Score 1 to 5: 5 = names exactly the cited sources, with filters and period consistent with the queries; 3 = partly consistent or vague; 1 = contradicts the evidence or invents sources.
Reply with JSON: {{"score": <integer 1-5>, "reason": "<one sentence>"}}"""


def _clip(text, n):
    text = text or ""
    return text if len(text) <= n else text[:n] + " ..."


class FoundryJudge:
    """Calls a chat model deployment in Microsoft Foundry (Azure OpenAI v1 API)."""

    def __init__(self, endpoint, deployment, api_key="", credential=None, client=None, max_retries=2,
                 max_calls=None):
        if max_calls is not None and (isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1):
            raise ValueError("max_calls must be a positive integer")
        if client is None:
            from openai import OpenAI

            base = endpoint.rstrip("/")
            if not base.endswith("/openai/v1"):
                base += "/openai/v1"
            if api_key:
                client = OpenAI(base_url=base + "/", api_key=api_key, max_retries=max_retries)
            else:
                from azure.identity import get_bearer_token_provider

                if credential is None:
                    raise ValueError("The judge needs an explicitly bound credential or API key")
                provider = get_bearer_token_provider(credential,
                                                     "https://cognitiveservices.azure.com/.default")
                client = OpenAI(base_url=base + "/", api_key=provider, max_retries=max_retries)
        self.client = client
        self.deployment = deployment
        self.model_name = deployment
        self.max_calls = max_calls
        self.calls = 0

    def _ask(self, prompt):
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise RuntimeError("Judge call allowance exhausted; no request was submitted")
        self.calls += 1  # Reserve before submission; a failed/ambiguous response still consumes an attempt.
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return parse_json_block(text) or {"reason": "unparseable judge reply: " + _clip(text, 200)}

    def judge_answer(self, q, answer):
        if not (q.expected_answer or q.expected_value is not None):
            return None
        out = self._ask(ANSWER_PROMPT.format(
            question=q.question, expected_answer=q.expected_answer or "(none)",
            expected_value=q.expected_value, unit=q.unit, rel_tol=q.rel_tol, answer=_clip(answer, 4000)))
        correct = out.get("correct")
        score = 1.0 if correct is True else 0.0 if correct is False else 0.5
        return {"score": score, "reason": out.get("reason", ""), "raw": out}

    def judge_why(self, q, answer, cited, why, models, dax):
        if not why:
            return None
        out = self._ask(WHY_PROMPT.format(
            question=q.question, answer=_clip(answer, 3000), cited=", ".join(cited) or "(none)",
            why=_clip(why, 3000), models=", ".join(models) or "(not captured)", dax=_clip(dax, 1500)))
        try:
            value = out.get("score")
            raw = int(value)
            if isinstance(value, bool) or raw != float(value) or not 1 <= raw <= 5:
                raise ValueError("judge score must be an integer from 1 to 5")
            score = (raw - 1) / 4.0
        except (TypeError, ValueError, OverflowError):
            raw, score = None, 0.5
            out["reason"] = "missing or invalid judge score: " + str(out.get("reason", ""))
        return {"score": score, "raw_score": raw, "reason": out.get("reason", ""), "raw": out}


def make_judge(settings, **limits):
    from .credentials import foundry_credential, judge_api_key

    if not settings.judge_endpoint:
        return None
    key = judge_api_key(settings)
    return FoundryJudge(settings.judge_endpoint, settings.judge_deployment, api_key=key,
                        credential=None if key else foundry_credential(settings), **limits)


def to_json(value):
    return json.dumps(value, ensure_ascii=False, default=str)
