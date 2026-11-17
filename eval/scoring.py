"""The three checks behind every verdict.

Pure Python with no network calls, so you can read it top to bottom and try it in a REPL:

    >>> from scoring import check_value
    >>> check_value("Gross revenue was $12.84M.", expected=12_840_000, unit="currency")
"""
import re

# "12.84M", "$12,840,000", "41.6%", "6.4 hours", "1.2 billion" ...
NUMBER = re.compile(
    r"(?<![\w.\[])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<scale>thousand|million|billion|bn|mn|k|m|b)?(?![A-Za-z])\s?(?P<pct>%|percent)?",
    re.IGNORECASE,
)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}

# Phrases that mean "I can't answer that" (used for questions where the right answer is to decline).
REFUSAL = re.compile(
    r"\b(can't|cannot|can not|unable to|don't have|do not have|isn't available|is not available|"
    r"no data|not available|couldn't find|could not find|not able to)\b",
    re.IGNORECASE,
)

# A vague answer such as "about $13M" must not pass, so display rounding may widen the tolerance by
# half of the last digit shown, but never beyond this.
MAX_ROUNDING = 0.01


def numbers_in(text):
    """Every number in the text with its scale applied: '$12.84M' becomes 12_840_000."""
    found = []
    for m in NUMBER.finditer(text or ""):
        digits = m.group("num")
        scale = SCALE.get((m.group("scale") or "").lower(), 1)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        found.append({
            "value": float(digits.replace(",", "")) * scale,
            "shown": m.group(0).strip(),
            "half_step": 0.5 * 10 ** -decimals * scale,  # how much rounding the displayed number hides
        })
    return found


def check_value(answer, expected, unit="number", tolerance=0.005, expect_refusal=False):
    """Is the number right? Picks the number in the answer closest to the expected value."""
    if expect_refusal:
        if REFUSAL.search(answer or ""):
            return {"result": "pass", "found": None, "reason": "declined, as expected"}
        return {"result": "fail", "found": None, "reason": "should have declined"}
    if expected is None:
        return {"result": "inconclusive", "found": None, "reason": "no expected value"}

    candidates = []
    for n in numbers_in(answer):
        candidates.append(n)
        if unit == "percent" and n["value"] <= 1:  # "0.416" for 41.6%
            candidates.append({**n, "value": n["value"] * 100, "half_step": n["half_step"] * 100})
    if not candidates:
        return {"result": "fail", "found": None, "reason": "no number in the answer"}

    best = min(candidates, key=lambda n: abs(n["value"] - expected))
    allowed = abs(expected) * tolerance
    allowed = max(allowed, min(best["half_step"], abs(expected) * MAX_ROUNDING))
    off = abs(best["value"] - expected)
    pct = off / abs(expected) * 100 if expected else 0
    if off <= allowed:
        return {"result": "pass", "found": best["value"], "reason": f"{best['shown']} matches {expected:,.10g}"}
    return {"result": "fail", "found": best["value"],
            "reason": f"{best['shown']} is {pct:.1f}% off {expected:,.10g}"}


def _norm(name):
    return " ".join((name or "").lower().replace("_", " ").split())


def check_citation(citations, expected_report, decoys=()):
    """Did Copilot cite the right report? Names must match exactly, so 'Sales' never matches 'Sales Sandbox'."""
    if not expected_report:
        return {"result": "skipped", "cited": [], "reason": "not checked"}
    cited = [c.get("title") or c.get("name") or "" for c in citations or []]
    names = {_norm(c) for c in cited}
    hit_decoys = [d for d in decoys or [] if _norm(d) in names]
    if hit_decoys:
        return {"result": "fail", "cited": cited, "reason": f"cited decoy {', '.join(hit_decoys)}"}
    if _norm(expected_report) in names:
        return {"result": "pass", "cited": cited, "reason": f"cited {expected_report}"}
    if not cited:
        return {"result": "fail", "cited": cited, "reason": "no citation"}
    return {"result": "fail", "cited": cited, "reason": f"cited {', '.join(cited)} instead"}


def check_model(queries, expected_model, decoys=()):
    """Did the right semantic model run the query? Uses the DAX found in workspace monitoring."""
    if not expected_model:
        return {"result": "skipped", "models": [], "reason": "not checked"}
    if queries is None:
        return {"result": "inconclusive", "models": [], "reason": "workspace monitoring not configured"}
    models = sorted({q.get("semantic_model", "") for q in queries if q.get("semantic_model")})
    if not models:
        return {"result": "inconclusive", "models": [], "reason": "no DAX found for this question yet"}
    names = {_norm(m) for m in models}
    hit_decoys = [d for d in decoys or [] if _norm(d) in names]
    if hit_decoys:
        return {"result": "fail", "models": models, "reason": f"DAX ran on decoy {', '.join(hit_decoys)}"}
    if _norm(expected_model) in names:
        return {"result": "pass", "models": models, "reason": f"DAX ran on {expected_model}"}
    return {"result": "fail", "models": models, "reason": f"DAX ran on {', '.join(models)}"}


def verdict(*checks):
    """FAIL if any check failed; INCONCLUSIVE if evidence was missing; otherwise PASS."""
    results = [c["result"] for c in checks]
    if "fail" in results:
        return "FAIL"
    if "inconclusive" in results:
        return "INCONCLUSIVE"
    return "PASS"
