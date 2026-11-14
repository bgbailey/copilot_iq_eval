"""Model-assisted answer judge, blind value extractor, and Cohen's kappa calibration.

Deterministic scorers decide value, citation routing, and DAX checks. The judge adds
optional AI-graded checks, blind literal-span extraction on ambiguous prose, and
offline calibration against human-labeled answer pairs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .chat import parse_json_block
from .scorers import (
    _ABSTAIN_RE,
    extract_answer_value,
    extract_numbers,
    normalize_name,
    value_check,
)

PROMPT_VERSION = "v2"

SYSTEM = "You are a strict, consistent evaluator. Reply with a single JSON object and nothing else."

ANSWER_PROMPT = (
    "Grade whether the assistant answered the business question correctly.\n"
    "Question: {question}\n"
    "Reference answer: {expected_answer}\n"
    "Expected value: {expected_value} ({unit}). Treat values as equal when they differ only "
    "by display rounding, currency symbols, thousands separators or scale words (K, M, B), "
    "or within a relative tolerance of {rel_tol}.\n"
    "Assistant's answer: {answer}\n"
    'Reply with JSON: {{"correct": true or false, "reason": "<one sentence>"}}'
)

WHY_PROMPT = (
    "Check whether the assistant's explanation of its sources agrees with the evidence.\n"
    "Question: {question}\n"
    "Answer: {answer}\n"
    "Artifacts the assistant cited: {cited}\n"
    "The assistant's explanation of its sources: {why}\n"
    "Semantic models the analytics engine actually queried (empty if not captured): {models}\n"
    "DAX the engine ran (truncated): {dax}\n"
    "Score 1 to 5: 5 = names exactly the cited sources, with filters and period consistent "
    "with the queries; 3 = partly consistent or vague; 1 = contradicts the evidence or invents sources.\n"
    'Reply with JSON: {{"score": <integer 1-5>, "reason": "<one sentence>"}}'
)

EXTRACT_PROMPT = (
    "Identify the single verbatim numeric span in the assistant's answer that directly answers "
    "the user's question.\n"
    "Do NOT guess or invent numbers. Copy the exact substring from the answer text.\n"
    "Question: {question}\n"
    "Assistant's answer: {answer}\n"
    'Reply with JSON: {{"span": "<exact verbatim substring from answer, or empty string if none>", '
    '"value": <parsed numeric value or null>, "unit": "<unit or empty string>", '
    '"reason": "<one sentence>"}}'
)

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "for",
        "of",
        "to",
        "from",
        "by",
        "with",
        "and",
        "or",
        "was",
        "were",
        "is",
        "are",
        "be",
        "been",
        "what",
        "how",
        "much",
        "many",
        "did",
        "does",
        "do",
        "we",
        "our",
        "total",
        "value",
        "amount",
        "number",
        "show",
        "tell",
        "me",
        "give",
        "assistant",
        "answer",
        "should",
        "expected",
        "summary",
        "contoso",
    }
)
_EXPECT_ABSTAIN_RE = re.compile(
    r"\b(?:should\s+abstain|must\s+abstain|should\s+refuse|must\s+refuse|expected\s+abstention|"
    r"abstain\s*:|refuse\s*:|out\s+of\s+scope|not\s+in\s+(?:the\s+)?(?:model|data|dataset)|"
    r"no\s+access|restricted\s+data|cannot\s+be\s+answered)\b",
    re.I,
)
_PERIOD_TOKEN_RE = re.compile(r"\b(?:fy\s*20\d{2}|cy\s*20\d{2}|q[1-4](?:\s*20\d{2})?|20\d{2})\b", re.I)
_REGION_TOKENS = ("north america", "emea", "apac", "latam", "europe", "asia pacific")


def _clip(text: str | None, n: int) -> str:
    s = text or ""
    return s if len(s) <= n else s[:n] + " ..."


def judge_prompt_hash() -> str:
    """Compute a deterministic 16-char SHA-256 hex digest of the active judge prompts."""
    canonical = json.dumps(
        {
            "version": PROMPT_VERSION,
            "system": SYSTEM,
            "answer_prompt": ANSWER_PROMPT,
            "why_prompt": WHY_PROMPT,
            "extract_prompt": EXTRACT_PROMPT,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _q_field(q: Any, name: str, default: Any = None) -> Any:
    if isinstance(q, Mapping):
        return q.get(name, default)
    return getattr(q, name, default)


def _validate_extracted_span(answer: str, raw_out: Mapping[str, Any]) -> dict[str, Any] | None:
    span = str(raw_out.get("span") or "").strip()
    if not span or span not in (answer or ""):
        return None
    ext = extract_answer_value(span)
    if ext["status"] != "ok" or ext["value"] is None:
        nums = extract_numbers(span)
        if len(nums) != 1:
            return None
        parsed_val = float(nums[0]["value"])
        parsed_unit = str(nums[0]["unit"])
    else:
        parsed_val = float(ext["value"])
        parsed_unit = str(ext["unit"])

    reported_val = raw_out.get("value")
    if reported_val is not None and not isinstance(reported_val, bool):
        try:
            rep_f = float(reported_val)
        except (TypeError, ValueError):
            return None
        if abs(parsed_val - rep_f) > max(1e-6, abs(rep_f) * 1e-6):
            return None

    return {
        "span": span,
        "value": parsed_val,
        "unit": str(raw_out.get("unit") or parsed_unit),
        "reason": str(raw_out.get("reason") or ""),
    }


class AnswerJudge:
    """Model-backed answer judge and blind literal-span extractor."""

    def __init__(
        self,
        endpoint: str = "",
        deployment: str = "judge",
        api_key: str = "",
        credential: Any = None,
        client: Any = None,
        max_retries: int = 2,
        max_calls: int | None = None,
        *,
        calibration_id: str = "",
    ) -> None:
        if max_calls is not None and (isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1):
            raise ValueError("max_calls must be a positive integer")
        if client is None:
            if not endpoint:
                raise ValueError("endpoint is required when client is not supplied")
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
                provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
                client = OpenAI(base_url=base + "/", api_key=provider, max_retries=max_retries)

        self.client = client
        self.deployment = deployment
        self.model_name = deployment
        self.max_calls = max_calls
        self.calls = 0
        self.prompt_version = PROMPT_VERSION
        self.prompt_hash = judge_prompt_hash()
        self.calibration_id = calibration_id

    def _ask(self, prompt: str) -> dict[str, Any]:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise RuntimeError("Maximum judge call limit reached; no request was submitted")
        self.calls += 1
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        parsed = parse_json_block(text)
        if isinstance(parsed, dict):
            return parsed
        return {"reason": "unparseable judge reply: " + _clip(text, 200)}

    def judge_answer(self, q: Any, answer: str) -> dict[str, Any] | None:
        exp_ans = _q_field(q, "expected_answer") or _q_field(q, "expected_summary") or ""
        exp_val = _q_field(q, "expected_value")
        if exp_val is None:
            exp_val = _q_field(q, "expected")
        if not (exp_ans or exp_val is not None):
            return None
        q_text = str(_q_field(q, "question") or "")
        unit = str(_q_field(q, "unit") or "number")
        rel_tol = _q_field(q, "rel_tol", 0.005)
        out = self._ask(
            ANSWER_PROMPT.format(
                question=q_text,
                expected_answer=exp_ans or "(none)",
                expected_value=exp_val,
                unit=unit,
                rel_tol=rel_tol,
                answer=_clip(answer, 4000),
            )
        )
        correct = out.get("correct")
        passed = 1 if correct is True else 0 if correct is False else -1
        score = 1.0 if correct is True else 0.0 if correct is False else 0.5
        return {
            "passed": passed,
            "score": score,
            "outcome": "PASS" if passed == 1 else "FAIL" if passed == 0 else "INCONCLUSIVE",
            "reason": str(out.get("reason") or ""),
            "raw": out,
        }

    def score_answer(self, question: str, expected_summary: str, answer: str) -> dict[str, Any]:
        res = self.judge_answer(
            {"question": question, "expected_summary": expected_summary, "unit": "number", "rel_tol": 0.005},
            answer,
        )
        return res or {"passed": -1, "score": 0.5, "outcome": "INCONCLUSIVE", "reason": "no expectation"}

    def judge_why(
        self,
        q: Any,
        answer: str,
        cited: Sequence[str],
        why: str,
        models: Sequence[str],
        dax: str,
    ) -> dict[str, Any] | None:
        if not why:
            return None
        q_text = str(_q_field(q, "question") or "")
        out = self._ask(
            WHY_PROMPT.format(
                question=q_text,
                answer=_clip(answer, 3000),
                cited=", ".join(cited) or "(none)",
                why=_clip(why, 3000),
                models=", ".join(models) or "(not captured)",
                dax=_clip(dax, 1500),
            )
        )
        raw: int | None
        try:
            value = out.get("score")
            if isinstance(value, bool) or value is None:
                raise ValueError("judge score must be an integer from 1 to 5")
            raw_int = int(value)
            if raw_int != float(value) or not 1 <= raw_int <= 5:
                raise ValueError("judge score must be an integer from 1 to 5")
            raw = raw_int
            score = (raw - 1) / 4.0
        except (TypeError, ValueError, OverflowError):
            raw, score = None, 0.5
            out["reason"] = "missing or invalid judge score: " + str(out.get("reason", ""))
        passed = 1 if score >= 0.75 else 0 if score <= 0.25 else -1
        return {
            "passed": passed,
            "score": score,
            "raw_score": raw,
            "reason": str(out.get("reason") or ""),
            "raw": out,
        }

    def extract_value(self, question: str, answer: str) -> dict[str, Any] | None:
        """Blindly extract the answering numeric span using ONLY question and answer."""
        if not (answer or "").strip():
            return None
        out = self._ask(EXTRACT_PROMPT.format(question=question, answer=_clip(answer, 4000)))
        return _validate_extracted_span(answer, out)


class FoundryJudge(AnswerJudge):
    """Calls a chat model deployment in Microsoft Foundry (Azure OpenAI v1 API)."""

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: str = "",
        credential: Any = None,
        client: Any = None,
        max_retries: int = 2,
        max_calls: int | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            deployment=deployment,
            api_key=api_key,
            credential=credential,
            client=client,
            max_retries=max_retries,
            max_calls=max_calls,
        )


def _content_tokens(text: str) -> set[str]:
    words = normalize_name(text).split()
    return {w for w in words if len(w) >= 2 and w not in _STOPWORDS and not w.isdigit()}


def _extract_ordered_items_from_summary(summary: str) -> list[str] | None:
    m = re.search(r"(?:in\s+order|ranked(?:\s+order)?)\s*:\s*(.+)$", summary, re.I)
    if not m:
        return None
    tail = m.group(1)
    parts = re.split(r"\s*(?:\d+\.\s*|>\s*|,\s*|\s+then\s+)\s*", tail)
    cleaned = [p.strip(" .;") for p in parts if p.strip(" .;")]
    return cleaned if len(cleaned) >= 2 else None


class MockJudge:
    """Deterministic offline judge for unit tests, mock runs, and calibration verification."""

    def __init__(self, max_calls: int | None = None, *, calibration_id: str = "mock-cal-v2") -> None:
        self.deployment = "mock-judge-v2"
        self.model_name = "mock-judge-v2"
        self.max_calls = max_calls
        self.calls = 0
        self.prompt_version = PROMPT_VERSION
        self.prompt_hash = judge_prompt_hash()
        self.calibration_id = calibration_id

    def _tick(self) -> None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise RuntimeError("Maximum judge call limit reached; no request was submitted")
        self.calls += 1

    def extract_value(self, question: str, answer: str) -> dict[str, Any] | None:
        """Blindly select the numeric span in `answer` whose local clause best matches `question`."""
        self._tick()
        raw_ans = answer or ""
        if not raw_ans.strip():
            return None

        cands = [c for c in extract_numbers(raw_ans) if not c.get("_in_range", False)]
        if not cands:
            return None

        direct = extract_answer_value(raw_ans)
        if direct["status"] == "ok" and direct["span"]:
            return {
                "span": str(direct["span"]),
                "value": float(direct["value"]),
                "unit": str(direct["unit"]),
                "reason": "unambiguous discourse lead value",
            }

        q_tokens = _content_tokens(question)
        q_lower = (question or "").lower()
        target_regions = [r for r in _REGION_TOKENS if r in q_lower]

        best_cand: dict[str, Any] | None = None
        best_score = -1
        tied = False

        for c in cands:
            s = int(c.get("_start", 0))
            e = int(c.get("_end", len(raw_ans)))
            clause_start = max(0, raw_ans.rfind(",", 0, s), raw_ans.rfind("\n", 0, s), raw_ans.rfind(";", 0, s))
            clause_end_candidates = [
                p
                for p in (raw_ans.find(",", e), raw_ans.find("\n", e), raw_ans.find(".", e), raw_ans.find(";", e))
                if p != -1
            ]
            clause_end = min(clause_end_candidates) if clause_end_candidates else len(raw_ans)
            local_ctx = raw_ans[clause_start:clause_end].lower()
            ctx_tokens = _content_tokens(local_ctx)

            overlap = len(q_tokens & ctx_tokens)
            for reg in target_regions:
                if reg in local_ctx:
                    overlap += 5
            if overlap > best_score:
                best_score = overlap
                best_cand = c
                tied = False
            elif overlap == best_score:
                tied = True

        if best_cand is not None and best_score > 0 and not tied:
            return {
                "span": str(best_cand["span"]),
                "value": float(best_cand["value"]),
                "unit": str(best_cand["unit"]),
                "reason": "matched local entity/clause context to question",
            }
        return None

    def score_answer(self, question: str, expected_summary: str, answer: str) -> dict[str, Any]:
        """Deterministically evaluate `(question, expected_summary, answer)` offline."""
        self._tick()
        ans = (answer or "").strip()
        exp = (expected_summary or "").strip()
        if not ans:
            return {"passed": 0, "score": 0.0, "outcome": "FAIL", "reason": "empty answer"}

        expect_abstain = bool(_EXPECT_ABSTAIN_RE.search(exp))
        if expect_abstain:
            vc_abs = value_check(ans, case_type="abstention")
            p = int(vc_abs["passed"])
            return {
                "passed": p,
                "score": 1.0 if p == 1 else 0.0,
                "outcome": "PASS" if p == 1 else "FAIL",
                "reason": str(vc_abs["reason"]),
            }

        if _ABSTAIN_RE.search(ans):
            return {
                "passed": 0,
                "score": 0.0,
                "outcome": "FAIL",
                "reason": "unexpected abstention on answerable question",
            }

        ordered_items = _extract_ordered_items_from_summary(exp)
        if ordered_items:
            vc_rk = value_check(ans, case_type="ranked_list", expect={"items": ordered_items, "ordered": True})
            p = int(vc_rk["passed"])
            return {
                "passed": p,
                "score": 1.0 if p == 1 else 0.0,
                "outcome": "PASS" if p == 1 else "FAIL",
                "reason": str(vc_rk["reason"]),
            }

        # Check explicit period mismatch (e.g., expected FY2025, answer states only FY2024)
        exp_periods = {re.sub(r"\s+", "", m.group(0).lower()) for m in _PERIOD_TOKEN_RE.finditer(exp + " " + question)}
        ans_periods = {re.sub(r"\s+", "", m.group(0).lower()) for m in _PERIOD_TOKEN_RE.finditer(ans)}
        if exp_periods and ans_periods and not (exp_periods & ans_periods):
            # Normalize bare year vs fy year (e.g. fy2025 vs 2025)
            exp_years = {re.sub(r"^(?:fy|cy)", "", p) for p in exp_periods}
            ans_years = {re.sub(r"^(?:fy|cy)", "", p) for p in ans_periods}
            if not (exp_years & ans_years):
                return {"passed": 0, "score": 0.0, "outcome": "FAIL", "reason": "period mismatch against reference"}

        # Check explicit region mismatch when single region asked/expected
        ref_low = (question + " " + exp).lower()
        ans_low = ans.lower()
        ref_regions = [r for r in _REGION_TOKENS if r in ref_low]
        ans_regions = [r for r in _REGION_TOKENS if r in ans_low]
        if len(ref_regions) == 1 and ans_regions and ref_regions[0] not in ans_regions:
            return {
                "passed": 0,
                "score": 0.0,
                "outcome": "FAIL",
                "reason": f"wrong region ({ans_regions[0]} vs {ref_regions[0]})",
            }

        # Numeric check when reference summary has a primary scalar value
        exp_ext = extract_answer_value(exp)
        if exp_ext["status"] == "ok" and exp_ext["value"] is not None:
            vc_num = value_check(
                ans,
                float(exp_ext["value"]),
                expected_unit=str(exp_ext.get("unit") or ""),
                expected_currency=str(exp_ext.get("currency") or ""),
                rel_tol=0.005,
                display_tol=0.01,
            )
            if vc_num["passed"] == -1:
                # Try blind question-conditioned span extraction
                self.calls -= 1  # internal helper reuse without double-counting
                blind = self.extract_value(question, ans)
                if blind is not None:
                    vc_num = value_check(
                        blind["span"],
                        float(exp_ext["value"]),
                        expected_unit=str(exp_ext.get("unit") or ""),
                        expected_currency=str(exp_ext.get("currency") or ""),
                        rel_tol=0.005,
                        display_tol=0.01,
                    )
            p = 1 if vc_num["passed"] == 1 else 0
            return {
                "passed": p,
                "score": 1.0 if p == 1 else 0.0,
                "outcome": "PASS" if p == 1 else "FAIL",
                "reason": str(vc_num["reason"]),
            }

        # Textual / Work IQ factual summary check
        exp_tokens = _content_tokens(exp)
        ans_tokens = _content_tokens(ans)
        if not exp_tokens:
            return {"passed": 1, "score": 1.0, "outcome": "PASS", "reason": "non-empty response"}

        # Contradiction check on explicit negation words absent from reference
        neg_words = {"cancelled", "canceled", "postponed", "rejected", "denied", "never"}
        if (ans_tokens & neg_words) - exp_tokens:
            return {"passed": 0, "score": 0.0, "outcome": "FAIL", "reason": "contradictory status in answer"}

        overlap_ratio = len(exp_tokens & ans_tokens) / len(exp_tokens)
        p = 1 if overlap_ratio >= 0.55 else 0
        return {
            "passed": p,
            "score": 1.0 if p == 1 else 0.0,
            "outcome": "PASS" if p == 1 else "FAIL",
            "reason": f"factual token overlap {overlap_ratio:.2f}",
        }

    def judge_answer(self, q: Any, answer: str) -> dict[str, Any] | None:
        case_type = str(_q_field(q, "case_type") or "scalar")
        expect = _q_field(q, "expect")
        exp_val = _q_field(q, "expected_value")
        if exp_val is None:
            exp_val = _q_field(q, "expected")
        exp_ans = str(_q_field(q, "expected_answer") or _q_field(q, "expected_summary") or "")
        q_text = str(_q_field(q, "question") or "")

        if case_type != "scalar" or expect is not None:
            self._tick()
            vc = value_check(
                answer,
                exp_val,
                expected_unit=str(_q_field(q, "unit") or ""),
                rel_tol=float(_q_field(q, "rel_tol", 0.005) or 0.005),
                abs_tol=_q_field(q, "abs_tol"),
                display_tol=float(_q_field(q, "display_tol", 0.01) or 0.01),
                case_type=case_type,
                expect=expect,
            )
            p = int(vc["passed"])
            return {
                "passed": p,
                "score": 1.0 if p == 1 else 0.0 if p == 0 else 0.5,
                "outcome": str(vc["outcome"]),
                "reason": str(vc["reason"]),
            }

        if exp_val is not None and not exp_ans:
            self._tick()
            vc = value_check(
                answer,
                float(exp_val),
                expected_unit=str(_q_field(q, "unit") or ""),
                expected_currency=str(_q_field(q, "currency") or ""),
                rel_tol=float(_q_field(q, "rel_tol", 0.005) or 0.005),
                abs_tol=_q_field(q, "abs_tol"),
                display_tol=float(_q_field(q, "display_tol", 0.01) or 0.01),
            )
            p = int(vc["passed"])
            return {
                "passed": p,
                "score": 1.0 if p == 1 else 0.0 if p == 0 else 0.5,
                "outcome": str(vc["outcome"]),
                "reason": str(vc["reason"]),
            }

        if not exp_ans:
            return None
        return self.score_answer(q_text, exp_ans, answer)

    def judge_why(
        self,
        q: Any,
        answer: str,
        cited: Sequence[str],
        why: str,
        models: Sequence[str],
        dax: str,
    ) -> dict[str, Any] | None:
        if not why:
            return None
        self._tick()
        targets = [s for s in list(cited) + list(models) if s]
        if not targets or any(t.lower() in why.lower() for t in targets):
            return {"passed": 1, "score": 1.0, "raw_score": 5, "reason": "sources consistent with explanation"}
        return {"passed": 0, "score": 0.0, "raw_score": 1, "reason": "explanation omitted cited/queried sources"}


def cohens_kappa(labels_a: Sequence[int | bool], labels_b: Sequence[int | bool]) -> float:
    """Compute Cohen's kappa inter-rater agreement between two equal-length label sequences."""
    if len(labels_a) != len(labels_b):
        raise ValueError(f"Label sequences must have equal length ({len(labels_a)} != {len(labels_b)})")
    n = len(labels_a)
    if n == 0:
        raise ValueError("Label sequences must be non-empty")

    a = [int(x) for x in labels_a]
    b = [int(x) for x in labels_b]
    categories = sorted(set(a) | set(b))

    p_o = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    p_e = sum((a.count(cat) / n) * (b.count(cat) / n) for cat in categories)

    if abs(1.0 - p_e) < 1e-12:
        return 1.0 if abs(1.0 - p_o) < 1e-12 else 0.0
    return float((p_o - p_e) / (1.0 - p_e))


def calibrate_judge(
    judge: Any,
    dataset_path: str | Path,
    *,
    min_kappa: float = 0.70,
) -> dict[str, Any]:
    """Evaluate a judge against a human-labeled JSONL calibration set and enforce `min_kappa`."""
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Calibration dataset not found: {path}")

    raw_bytes = path.read_bytes()
    dataset_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
    records = [json.loads(line) for line in raw_bytes.decode("utf-8").splitlines() if line.strip()]
    if not records:
        raise ValueError(f"Calibration dataset is empty: {path}")

    human_labels: list[int] = []
    judge_labels: list[int] = []
    slice_pairs: dict[str, tuple[list[int], list[int]]] = {}
    disagreements: list[dict[str, Any]] = []

    tp = tn = fp = fn = 0

    for rec in records:
        qid = str(rec.get("id") or "")
        question = str(rec.get("question") or "")
        expected_summary = str(rec.get("expected_summary") or "")
        answer = str(rec.get("answer") or "")
        h_label = 1 if int(rec["human_pass"]) == 1 else 0
        slc = str(rec.get("slice") or "general")

        if hasattr(judge, "score_answer"):
            res = judge.score_answer(question, expected_summary, answer)
        else:
            res = judge.judge_answer(
                {"question": question, "expected_summary": expected_summary, "unit": "number", "rel_tol": 0.005},
                answer,
            ) or {"passed": 0, "score": 0.0, "reason": "no verdict"}

        j_pass = 1 if (res.get("passed") == 1 or (res.get("score") is not None and float(res["score"]) >= 0.75)) else 0

        human_labels.append(h_label)
        judge_labels.append(j_pass)
        s_h, s_j = slice_pairs.setdefault(slc, ([], []))
        s_h.append(h_label)
        s_j.append(j_pass)

        if h_label == 1 and j_pass == 1:
            tp += 1
        elif h_label == 0 and j_pass == 0:
            tn += 1
        elif h_label == 0 and j_pass == 1:
            fp += 1
        else:
            fn += 1

        if h_label != j_pass:
            disagreements.append(
                {
                    "id": qid,
                    "slice": slc,
                    "human_pass": h_label,
                    "judge_pass": j_pass,
                    "reason": str(res.get("reason") or ""),
                }
            )

    total = len(records)
    agreement = (tp + tn) / total
    kappa = cohens_kappa(human_labels, judge_labels)
    pass_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    fail_recall = tn / (tn + fn) if (tn + fn) > 0 else 0.0

    by_slice: dict[str, dict[str, Any]] = {}
    for slc, (sh, sj) in sorted(slice_pairs.items()):
        s_agree = sum(1 for x, y in zip(sh, sj, strict=True) if x == y) / len(sh)
        by_slice[slc] = {
            "count": len(sh),
            "agreement": s_agree,
            "kappa": cohens_kappa(sh, sj),
        }

    p_hash = str(getattr(judge, "prompt_hash", None) or judge_prompt_hash())
    model_name = str(getattr(judge, "model_name", None) or getattr(judge, "deployment", "unknown"))
    cal_payload = json.dumps(
        {
            "model": model_name,
            "prompt_hash": p_hash,
            "dataset_hash": dataset_hash,
            "total": total,
            "kappa": round(kappa, 6),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    calibration_id = hashlib.sha256(cal_payload.encode("utf-8")).hexdigest()[:16]
    if hasattr(judge, "calibration_id"):
        judge.calibration_id = calibration_id

    return {
        "calibration_id": calibration_id,
        "model_name": model_name,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": p_hash,
        "dataset_hash": dataset_hash,
        "total": total,
        "agreement": agreement,
        "accuracy": agreement,
        "kappa": kappa,
        "min_kappa": min_kappa,
        "passed": bool(kappa >= min_kappa),
        "pass_precision": pass_precision,
        "fail_recall": fail_recall,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "by_slice": by_slice,
        "disagreements": disagreements,
    }


def make_judge(settings: Any, **limits: Any) -> FoundryJudge | None:
    from .credentials import foundry_credential, judge_api_key

    if not settings.judge_endpoint:
        return None
    key = judge_api_key(settings)
    return FoundryJudge(
        settings.judge_endpoint,
        settings.judge_deployment,
        api_key=key,
        credential=None if key else foundry_credential(settings),
        **limits,
    )


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
