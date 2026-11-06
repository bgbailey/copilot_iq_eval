"""Deterministic scorers.

This module uses only the Python standard library so the same code runs
locally, in Fabric notebooks and inside Microsoft Foundry code-based
evaluators (which have no network access and a limited package set).

Every scorer returns a dict: {"score": 1.0 | 0.0 | 0.5, "outcome": str,
"reason": str, ...details}. 1.0 = PASS, 0.0 = FAIL, 0.5 = INCONCLUSIVE.
"""
import re
from decimal import Decimal, InvalidOperation

PASS = 1.0
FAIL = 0.0
INCONCLUSIVE = 0.5

POWERBI_KINDS = (
    "powerbi_report",
    "semantic_model",
    "powerbi_dashboard",
    "paginated_report",
    "powerbi_app",
    "powerbi_link",
    "fabric_data_agent",
)

_TEN = Decimal(10)
_SCALES = {
    "k": _TEN ** 3, "thousand": _TEN ** 3,
    "m": _TEN ** 6, "mm": _TEN ** 6, "mn": _TEN ** 6, "million": _TEN ** 6,
    "b": _TEN ** 9, "bn": _TEN ** 9, "billion": _TEN ** 9,
    "t": _TEN ** 12, "trillion": _TEN ** 12,
}
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_STRIP = [
    (r"\[[^\]]*\]\((?:https?://)[^)\s]*\)", 0),            # markdown links
    (r"https?://\S+", 0),                                  # bare URLs
    (r"\[\^?\d+\^?\]", 0),                                 # citation markers [^1^] [1]
    (r"\bFY\s?'?\d{2,4}\b", re.I),                         # fiscal year labels
    (r"\b[QH][1-4]\b", re.I),                               # quarter / half labels
    (r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?\b", 0),      # ISO dates
    (r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", 0),                  # 6/30/2025
    (r"\b\d{1,2}\s+" + _MONTH + r",?\s+\d{4}\b", re.I),   # 30 June 2025
    (_MONTH + r"\s+\d{1,2},?\s+\d{4}\b", re.I),           # June 30, 2025
    (_MONTH + r"\s+\d{4}\b", re.I),                       # June 2025
    (r"<[^>]{1,40}>", 0),                                  # inline tags such as <File>
    (r"\b[A-Za-z]+\d+[A-Za-z0-9]*\b", 0),                 # labels such as Sev1, P1, COVID19
    (r"\b\d+(?:st|nd|rd|th)\b", re.I),                     # ordinals: 3rd, 4th
]
_YEAR = r"(?<![\d.,$\u20ac\u00a3])\b(?:19|20)\d{2}\b(?![\d.,%])"
_NUM = (
    r"(?P<lpar>\()?[ \t]*"
    r"(?P<sign>[-\u2212])?[ \t]*"
    r"(?P<cur>[$\u20ac\u00a3])?[ \t]*"
    r"(?P<num>\d{1,3}(?:[,\u00a0\u202f]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?:[ \t]?(?P<scale>trillion|billion|million|thousand|bn|mn|mm|k|m|b|t)(?![a-z]))?"
    r"[ \t]*(?P<pct>%|percent\b|pct\b)?"
    r"(?:[ \t]?(?P<cursuf>usd|dollars?|eur|gbp)\b)?"
    r"[ \t]*(?P<rpar>\))?"
)


def _dec(value, default=None):
    if value is None or value == "":
        return default
    try:
        number = Decimal(str(value).strip())
        return number if number.is_finite() else default
    except (InvalidOperation, ValueError):
        return default


def show(number):
    """Readable number for reasons: 12840000.0 -> 12,840,000; 41.60 -> 41.6."""
    d = _dec(number)
    if d is None:
        return str(number)
    return format(d.normalize(), ",f")


def clean_text(text):
    """Remove URLs, dates, fiscal labels and citation markers before parsing numbers."""
    out = text or ""
    for pattern, flags in _STRIP:
        out = re.sub(pattern, " ", out, flags=flags)
    return re.sub(_YEAR, " ", out)


def parse_numbers(text):
    """Return every number in the text with its kind, scale and displayed precision."""
    results = []
    for m in re.finditer(_NUM, clean_text(text), re.I):
        raw_num = m.group("num")
        digits = re.sub(r"[,\u00a0\u202f]", "", raw_num)
        try:
            base = Decimal(digits)
        except InvalidOperation:
            continue
        scale_word = (m.group("scale") or "").lower()
        scale = _SCALES.get(scale_word, Decimal(1))
        decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
        negative = bool(m.group("sign")) or bool(m.group("lpar") and m.group("rpar"))
        value = base * scale * (-1 if negative else 1)
        if m.group("pct"):
            kind = "percent"
        elif m.group("cur") or m.group("cursuf"):
            kind = "currency"
        else:
            kind = "number"
        results.append({
            "value": value,
            "raw": m.group(0).strip(),
            "kind": kind,
            "scaled": scale != 1,
            "decimals": decimals,
            "step": (Decimal(1).scaleb(-decimals)) * scale,
        })
    return results


def candidates_for_unit(numbers, unit):
    """Pick the numbers compatible with the expected unit, best tier first."""
    unit = (unit or "number").lower()
    if unit == "percent":
        tiers = [[n for n in numbers if n["kind"] == "percent"]]
    elif unit == "currency":
        tiers = [
            [n for n in numbers if n["kind"] == "currency"],
            [n for n in numbers if n["kind"] == "number" and n["scaled"]],
            [n for n in numbers if n["kind"] == "number"],
        ]
    else:  # count / number
        tiers = [
            [n for n in numbers if n["kind"] == "number" and not n["scaled"]],
            [n for n in numbers if n["kind"] == "number"],
            [n for n in numbers if n["kind"] == "currency"],
        ]
    for tier in tiers:
        if tier:
            return tier
    return []


def _result(score, reason, **details):
    outcome = {PASS: "PASS", FAIL: "FAIL"}.get(score, "INCONCLUSIVE")
    out = {"score": score, "outcome": outcome, "reason": reason}
    out.update(details)
    return out


def score_value(answer, expected, unit="number", rel_tol=0.005, abs_tol=0.0,
                display_aware=True, max_display_rel=0.05):
    """Is the first unit-compatible number in the answer within tolerance of the expected value?

    Display-aware tolerance accepts an answer rounded for display (for example
    "$12.8M" for 12,840,000) but fails an answer rounded so coarsely that it
    can't be checked (half a display step above max_display_rel of the value).
    The expected value is never used to choose between candidates.
    """
    exp = _dec(expected)
    if exp is None:
        return _result(INCONCLUSIVE, "no expected value configured")
    cands = candidates_for_unit(parse_numbers(answer), unit)
    if not cands:
        return _result(FAIL, "no %s value found in the answer" % (unit or "number"), extracted=None)
    first = cands[0]
    value = first["value"]
    rel, absol = _dec(rel_tol), _dec(abs_tol)
    if rel is None or absol is None or rel < 0 or absol < 0:
        return _result(INCONCLUSIVE, "value tolerances must be finite and non-negative")
    allowed = max(absol, rel * abs(exp))
    half_step = first["step"] / 2
    if display_aware:
        if exp != 0 and half_step / abs(exp) > _dec(max_display_rel, Decimal("0.05")):
            return _result(FAIL, "answer rounded too coarsely to verify (%s)" % first["raw"],
                           extracted=float(value), raw=first["raw"])
        allowed = max(allowed, half_step)
    diff = abs(value - exp)
    details = {
        "extracted": float(value),
        "raw": first["raw"],
        "difference": float(diff),
        "allowed": float(allowed),
        "error_pct": float(diff / abs(exp) * 100) if exp != 0 else None,
        "candidates": len(cands),
    }
    if diff <= allowed:
        return _result(PASS, "value %s matches expected %s" % (first["raw"], show(exp)), **details)
    return _result(FAIL, "value %s differs from expected %s" % (first["raw"], show(exp)), **details)


def normalize_name(name):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (name or "").lower()).split())


def split_list(value):
    """Accept a list or a ';' / '|' separated string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = re.split(r"[;|]", str(value))
    return [str(i).strip() for i in items if str(i).strip()]


def name_matches(candidate, target):
    c, t = normalize_name(candidate), normalize_name(target)
    if not c or not t:
        return False
    return c == t or (" " + t + " ") in (" " + c + " ")


def _artifact_hit(artifact, targets):
    name = artifact.get("name") or ""
    item_id = (artifact.get("item_id") or "").lower()
    for t in targets:
        if item_id and t.lower() == item_id:
            return True
        if name_matches(name, t):
            return True
    return False


def citation_artifacts(artifacts):
    """Answer links and model citations, not grounding-only discovery metadata.

    Legacy artifacts without attribution fields retain their original meaning.
    This is a citation policy, not proof that other grounding had no influence.
    """
    return [
        a for a in artifacts or []
        if a.get("answer_cited") or a.get("source") == "answer_link" or (
            (a.get("attribution_source") or "").lower() in ("", "model")
            and (a.get("attribution_type") or "").lower() in ("", "citation"))
    ]


def score_artifact(artifacts, expected, aliases=None, decoys=None):
    """Did Copilot cite the expected report or semantic model, and no decoy?

    Only Power BI / Fabric items count as a hit on the expected artifact (a
    document that merely shares its name doesn't); decoys match any kind.
    """
    artifacts = citation_artifacts(artifacts)
    targets = split_list(expected) + split_list(aliases)
    decoy_list = split_list(decoys)
    decoy_hits = sorted({a.get("name") or a.get("url") or "?" for a in artifacts if _artifact_hit(a, decoy_list)})
    powerbi = [a for a in artifacts if a.get("kind") in POWERBI_KINDS]
    cited = sorted({a.get("name") or a.get("url") or "?" for a in artifacts})
    details = {"decoy_hit": bool(decoy_hits), "cited": cited, "powerbi_cited": len(powerbi)}
    if decoy_hits:
        return _result(FAIL, "decoy cited: " + ", ".join(decoy_hits), **details)
    if not targets:
        return _result(INCONCLUSIVE, "no expected artifact configured", **details)
    if any(_artifact_hit(a, targets) for a in powerbi):
        return _result(PASS, "expected artifact cited", **details)
    lookalikes = sorted({a.get("name") or "?" for a in artifacts if a not in powerbi and _artifact_hit(a, targets)})
    if not powerbi:
        note = " (cited a non-Power BI item with a matching name: %s)" % ", ".join(lookalikes) if lookalikes else ""
        return _result(FAIL, "no Power BI report or semantic model cited" + note, **details)
    return _result(FAIL, "cited other Power BI content: " + ", ".join(
        sorted({a.get("name") or "?" for a in powerbi})), **details)


def score_model(trace_status, queried_models, expected_model, decoys=None):
    """Did Fabric IQ run DAX against the expected semantic model, and no decoy?"""
    status = (trace_status or "disabled").lower()
    models = sorted(set(queried_models or []))
    details = {"queried": models, "trace_status": status}
    decoy_hits = [m for m in models if any(name_matches(m, d) for d in split_list(decoys))]
    if decoy_hits:
        return _result(FAIL, "decoy semantic model queried: " + ", ".join(decoy_hits), decoy_hit=True, **details)
    if status == "disabled":
        return None
    if status not in ("complete", "observed") or not models:
        return _result(INCONCLUSIVE, "DAX capture is missing or not settled (%s)" % status, **details)
    targets = split_list(expected_model)
    if not targets:
        return _result(INCONCLUSIVE, "no expected semantic model configured", **details)
    if any(name_matches(m, t) for m in models for t in targets):
        return _result(PASS, "expected semantic model observed in the captured queries", **details)
    return _result(FAIL, "queried other semantic models: " + ", ".join(models), **details)


def verdict(scores, required=("value", "artifact", "model")):
    """Combine check results. A FAIL on any required check fails the ask;
    an INCONCLUSIVE required check makes the ask INCONCLUSIVE."""
    considered = [scores.get(k) for k in required]
    if not considered:
        return "INCONCLUSIVE"
    if any(s == FAIL for s in considered):
        return "FAIL"
    if any(s != PASS for s in considered):
        return "INCONCLUSIVE"
    return "PASS"
