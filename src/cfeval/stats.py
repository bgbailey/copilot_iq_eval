"""Pure standard-library statistical functions for evaluation runs and comparisons."""

from __future__ import annotations

import math
from typing import Any

Z_95 = 1.959963984540054


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Compute the Wilson score confidence interval (low, high) for a binomial proportion."""
    if isinstance(successes, bool) or isinstance(total, bool):
        raise ValueError("successes and total must be integers, not booleans")
    if total < 0 or successes < 0 or successes > total:
        raise ValueError(f"Invalid counts: successes={successes}, total={total}")
    if z < 0.0 or not math.isfinite(z):
        raise ValueError(f"z must be finite and non-negative, got {z}")
    if total == 0:
        return (0.0, 0.0)

    p_hat = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denom
    radicand = max(0.0, (p_hat * (1.0 - p_hat) / total) + (z2 / (4.0 * total * total)))
    half_width = (z / denom) * math.sqrt(radicand)
    low = 0.0 if successes == 0 else max(0.0, min(1.0, center - half_width))
    high = 1.0 if successes == total else max(0.0, min(1.0, center + half_width))
    if low > high:
        low, high = high, low
    return (low, high)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimator of pass@k: probability at least 1 of k samples passes.

    Matches app/overlay/src/eval/metrics.ts:
    - Returns 0.0 when n <= 0 or k <= 0.
    - Clamps k_eff = min(k, n) when k > n, so single-trial n=1, k=3 yields 1.0 if c >= 1 else 0.0.
    - Uses 1 - comb(n - c, k_eff) / comb(n, k_eff) when n - c >= k_eff, else 1.0.
    """
    if isinstance(n, bool) or isinstance(c, bool) or isinstance(k, bool):
        raise ValueError("n, c, and k must be integers, not booleans")
    if c < 0 or (n >= 0 and c > n):
        raise ValueError(f"Invalid counts: n={n}, c={c}")
    if n <= 0 or k <= 0:
        return 0.0
    k_eff = min(k, n)
    if n - c < k_eff:
        return 1.0
    return 1.0 - (math.comb(n - c, k_eff) / math.comb(n, k_eff))


def pass_pow_k(n: int, c: int, k: int) -> float:
    """Reliability metric pass^k: probability all k independent trials pass ((c / n) ** k)."""
    if isinstance(n, bool) or isinstance(c, bool) or isinstance(k, bool):
        raise ValueError("n, c, and k must be integers, not booleans")
    if c < 0 or (n >= 0 and c > n):
        raise ValueError(f"Invalid counts: n={n}, c={c}")
    if n <= 0 or k <= 0:
        return 0.0
    return float((c / n) ** k)


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact binomial McNemar p-value on discordant pairs (b, c)."""
    if isinstance(b, bool) or isinstance(c, bool):
        raise ValueError("b and c must be integers, not booleans")
    if b < 0 or c < 0:
        raise ValueError(f"Discordant counts must be non-negative: b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    if 2 * m >= n - 1:
        return 1.0
    tail_sum = sum(math.comb(n, i) for i in range(m + 1))
    p_val = (2 * tail_sum) / (1 << n)
    return min(1.0, float(p_val))


def _row_verdict(row: dict[str, Any]) -> str:
    raw = row.get("Verdict")
    if raw is None:
        raw = row.get("verdict")
    if raw is not None and str(raw).strip():
        return str(raw).strip().upper()
    passed = row.get("passed")
    if passed == 1 or passed is True:
        return "PASS"
    if passed == 0 or passed is False:
        return "FAIL"
    return "INCONCLUSIVE"


def _row_qid(row: dict[str, Any], index: int) -> str:
    qid = row.get("QuestionId") or row.get("question_id") or row.get("id") or f"row_{index}"
    return str(qid)


def _row_category(row: dict[str, Any]) -> str:
    cat = row.get("Category") if "Category" in row else row.get("category", "")
    return str(cat or "uncategorized")


def _row_criticality(row: dict[str, Any]) -> str:
    crit = row.get("Criticality") if "Criticality" in row else row.get("criticality", "standard")
    return str(crit or "standard").lower()


def _row_extracted(row: dict[str, Any]) -> float | None:
    val = row.get("ExtractedValue") if "ExtractedValue" in row else row.get("extracted")
    if val is None or isinstance(val, bool):
        return None
    try:
        num = float(val)
        return num if math.isfinite(num) else None
    except (TypeError, ValueError):
        return None


def _values_consistent(values: list[float]) -> bool:
    if len(values) <= 1:
        return True
    first = values[0]
    tol = max(1e-6, abs(first) * 1e-6)
    return all(abs(v - first) <= tol for v in values[1:])


def summarize_run_stats(rows: list[dict[str, Any]], k: int = 1) -> dict[str, Any]:
    """Aggregate attempt-level rows into per-question, per-category, and run-level statistics."""
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for idx, row in enumerate(rows):
        qid = _row_qid(row, idx)
        grouped.setdefault(qid, []).append(row)

    questions: list[dict[str, Any]] = []
    per_question: dict[str, dict[str, Any]] = {}
    critical_failure_ids: list[str] = []

    for qid, q_rows in grouped.items():
        n = len(q_rows)
        verdicts = [_row_verdict(r) for r in q_rows]
        c = sum(1 for v in verdicts if v == "PASS")
        inc = sum(1 for v in verdicts if v == "INCONCLUSIVE")
        err = sum(1 for v in verdicts if v == "ERROR")
        category = _row_category(q_rows[0])
        criticality = _row_criticality(q_rows[0])
        extracted_vals = [v for v in (_row_extracted(r) for r in q_rows) if v is not None]
        consistent = _values_consistent(extracted_vals) and (len(extracted_vals) in (0, n))

        q_stat: dict[str, Any] = {
            "question_id": qid,
            "category": category,
            "criticality": criticality,
            "n": n,
            "c": c,
            "pass_rate": c / n if n > 0 else 0.0,
            "pass_at_k": pass_at_k(n, c, k),
            "pass_pow_k": pass_pow_k(n, c, k),
            "inconclusive_count": inc,
            "error_count": err,
            "consistent": consistent,
        }
        if criticality == "critical" and c < n:
            critical_failure_ids.append(qid)
        questions.append(q_stat)
        per_question[qid] = q_stat

    critical_failures = len(critical_failure_ids)

    total_asks = len(rows)
    question_count = len(questions)
    all_verdicts = [_row_verdict(r) for r in rows]
    passed_asks = sum(1 for v in all_verdicts if v == "PASS")
    inconclusive_count = sum(1 for v in all_verdicts if v == "INCONCLUSIVE")
    error_count = sum(1 for v in all_verdicts if v == "ERROR")
    pass_rate = (passed_asks / total_asks) if total_asks > 0 else 0.0
    w_low, w_high = wilson_interval(passed_asks, total_asks)

    mean_pass_at_k = (sum(q["pass_at_k"] for q in questions) / question_count) if question_count > 0 else 0.0
    mean_pass_pow_k = (sum(q["pass_pow_k"] for q in questions) / question_count) if question_count > 0 else 0.0
    consistency_rate = sum(1 for q in questions if q["consistent"]) / question_count if question_count > 0 else 1.0

    cat_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cat_rows.setdefault(_row_category(row), []).append(row)

    by_category: dict[str, dict[str, Any]] = {}
    for cat, c_rows in cat_rows.items():
        cat_qids = {_row_qid(r, i) for i, r in enumerate(c_rows)}
        cat_qs = [per_question[qid] for qid in cat_qids if qid in per_question]
        c_total = len(c_rows)
        c_verdicts = [_row_verdict(r) for r in c_rows]
        c_pass = sum(1 for v in c_verdicts if v == "PASS")
        c_inc = sum(1 for v in c_verdicts if v == "INCONCLUSIVE")
        c_err = sum(1 for v in c_verdicts if v == "ERROR")
        cw_low, cw_high = wilson_interval(c_pass, c_total)
        by_category[cat] = {
            "question_count": len(cat_qs),
            "total_asks": c_total,
            "passed_asks": c_pass,
            "pass_rate": c_pass / c_total if c_total > 0 else 0.0,
            "wilson_low": cw_low,
            "wilson_high": cw_high,
            "mean_pass_at_k": (sum(q["pass_at_k"] for q in cat_qs) / len(cat_qs)) if cat_qs else 0.0,
            "mean_pass_pow_k": (sum(q["pass_pow_k"] for q in cat_qs) / len(cat_qs)) if cat_qs else 0.0,
            "inconclusive_rate": c_inc / c_total if c_total > 0 else 0.0,
            "error_count": c_err,
        }

    return {
        "k": k,
        "question_count": question_count,
        "total_questions": question_count,
        "total_asks": total_asks,
        "total_rows": total_asks,
        "passed_asks": passed_asks,
        "pass_rate": pass_rate,
        "wilson_low": w_low,
        "wilson_high": w_high,
        "mean_pass_at_k": mean_pass_at_k,
        "mean_pass_pow_k": mean_pass_pow_k,
        "inconclusive_count": inconclusive_count,
        "inconclusive_rate": (inconclusive_count / total_asks) if total_asks > 0 else 0.0,
        "error_count": error_count,
        "error_rate": (error_count / total_asks) if total_asks > 0 else 0.0,
        "critical_failures": critical_failures,
        "critical_failure_ids": critical_failure_ids,
        "consistency_rate": consistency_rate,
        "by_category": by_category,
        "questions": questions,
        "per_question": per_question,
    }


def _question_passed(q_stat: dict[str, Any], k: int) -> bool:
    n = int(q_stat["n"])
    c = int(q_stat["c"])
    if n <= 0:
        return False
    if k > 1:
        return c == n
    return (c * 2) > n


def compare_runs(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    k: int = 1,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Compare baseline and candidate runs on matched QuestionIds using exact McNemar test."""
    base_stats = summarize_run_stats(baseline_rows, k=k)
    cand_stats = summarize_run_stats(candidate_rows, k=k)
    base_q = base_stats["per_question"]
    cand_q = cand_stats["per_question"]

    paired_ids = [qid for qid in base_q if qid in cand_q]
    both_passed = 0
    b = 0  # baseline passed, candidate failed (regression)
    c = 0  # baseline failed, candidate passed (improvement)
    both_failed = 0
    regressions: list[str] = []
    improvements: list[str] = []
    per_question_deltas: list[dict[str, Any]] = []

    for qid in paired_ids:
        bq = base_q[qid]
        cq = cand_q[qid]
        b_ok = _question_passed(bq, k)
        c_ok = _question_passed(cq, k)
        if b_ok and c_ok:
            both_passed += 1
            change = "unchanged_pass"
        elif b_ok and not c_ok:
            b += 1
            regressions.append(qid)
            change = "regression"
        elif not b_ok and c_ok:
            c += 1
            improvements.append(qid)
            change = "improvement"
        else:
            both_failed += 1
            change = "unchanged_fail"
        per_question_deltas.append(
            {
                "question_id": qid,
                "baseline_pass_rate": bq["pass_rate"],
                "candidate_pass_rate": cq["pass_rate"],
                "delta_pass_rate": cq["pass_rate"] - bq["pass_rate"],
                "baseline_passed": b_ok,
                "candidate_passed": c_ok,
                "change": change,
            }
        )

    p_val = mcnemar_exact_p(b, c)
    return {
        "k": k,
        "paired_count": len(paired_ids),
        "paired_questions": len(paired_ids),
        "both_passed": both_passed,
        "b": b,
        "c": c,
        "both_failed": both_failed,
        "mcnemar_p": p_val,
        "alpha": alpha,
        "significant": p_val < alpha,
        "delta_pass_rate": cand_stats["pass_rate"] - base_stats["pass_rate"],
        "delta_pass_pow_k": cand_stats["mean_pass_pow_k"] - base_stats["mean_pass_pow_k"],
        "baseline_pass_rate": base_stats["pass_rate"],
        "candidate_pass_rate": cand_stats["pass_rate"],
        "baseline_wilson": (base_stats["wilson_low"], base_stats["wilson_high"]),
        "candidate_wilson": (cand_stats["wilson_low"], cand_stats["wilson_high"]),
        "regressions": regressions,
        "improvements": improvements,
        "per_question_deltas": per_question_deltas,
        "baseline": base_stats,
        "candidate": cand_stats,
    }
