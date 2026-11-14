"""Deterministic scorers for Copilot x IQ evaluation.

This module uses only the Python standard library at import time so the same
code runs locally, in Fabric notebooks, and inside Microsoft Foundry code-based
evaluators (which have no network access and a restricted package set).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PASS = 1.0
FAIL = 0.0
INCONCLUSIVE = 0.5
VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE", "ERROR")

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
_SCALES: dict[str, Decimal] = {
    "k": _TEN**3,
    "thousand": _TEN**3,
    "thousands": _TEN**3,
    "m": _TEN**6,
    "mm": _TEN**6,
    "mn": _TEN**6,
    "mio": _TEN**6,
    "million": _TEN**6,
    "millions": _TEN**6,
    "b": _TEN**9,
    "bn": _TEN**9,
    "mrd": _TEN**9,
    "billion": _TEN**9,
    "billions": _TEN**9,
    "t": _TEN**12,
    "tn": _TEN**12,
    "trillion": _TEN**12,
    "trillions": _TEN**12,
}

_CURRENCY_MAP: dict[str, str] = {
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "\u20ac": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "\u00a3": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
}

_UNIT_CANON: dict[str, str] = {
    "%": "percent",
    "percent": "percent",
    "pct": "percent",
    "pp": "pp",
    "percentage point": "pp",
    "percentage points": "pp",
    "pct pt": "pp",
    "pct pts": "pp",
    "bps": "bps",
    "basis point": "bps",
    "basis points": "bps",
    "unit": "units",
    "units": "units",
    "order": "orders",
    "orders": "orders",
    "customer": "customers",
    "customers": "customers",
    "day": "days",
    "days": "days",
    "hour": "hours",
    "hours": "hours",
    "headcount": "headcount",
    "employee": "employees",
    "employees": "employees",
    "item": "items",
    "items": "items",
    "count": "count",
    "counts": "count",
    "ratio": "ratio",
    "ratios": "ratio",
    "x": "x",
}

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_YEAR_CORE = r"(?:19\d{2}|20\d{2}|2100)"
_MEASURE_FOLLOW = (
    r"(?!\s*(?:units?|orders?|customers?|days?|hours?|headcount|employees?|items?|counts?|"
    r"%|percent\b|pct\b|pp\b|percentage\s+points?\b|bps\b|basis\s+points?\b|"
    r"thousands?|millions?|billions?|trillions?|[KMBT]\b))"
)

_MASK_FULL_PATTERNS: list[tuple[re.Pattern[str], str | None]] = [
    (re.compile(r"\]\((?P<m>https?://[^)\s]*)\)"), "m"),
    (re.compile(r"(?P<m>https?://\S+)"), "m"),
    (re.compile(r"(?P<m>\[\^?\d+\^?\])"), "m"),
    (re.compile(r"(?P<m><[^>]{1,60}>)"), "m"),
    (re.compile(r"(?P<m>\b" + _YEAR_CORE + r"-\d{2}-\d{2}(?:[T ][\d:.+-]+Z?)?\b)"), "m"),
    (re.compile(r"(?P<m>\b" + _YEAR_CORE + r"-(?:0[1-9]|1[0-2])\b)"), "m"),
    (re.compile(r"(?P<m>\b\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})\b)"), "m"),
    (re.compile(r"(?P<m>\b\d{1,2}\s+" + _MONTH + r",?\s+" + _YEAR_CORE + r"\b)", re.I), "m"),
    (re.compile(r"(?P<m>\b" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+" + _YEAR_CORE + r"\b)", re.I), "m"),
    (re.compile(r"(?P<m>\b" + _MONTH + r",?\s+(?:of\s+)?" + _YEAR_CORE + r"\b)", re.I), "m"),
    (re.compile(r"(?P<m>\b(?:FY|CY|GJ|AY|SY)\s*['\u2019]?(?:" + _YEAR_CORE + r"|\d{2})\b)", re.I), "m"),
    (
        re.compile(
            r"(?P<m>\b[QH][1-4](?:\s+(?:of\s+)?(?:(?:FY|CY)\s*['\u2019]?)?(?:" + _YEAR_CORE + r"|\d{2}))?\b)",
            re.I,
        ),
        "m",
    ),
    (re.compile(r"(?P<m>\b" + _YEAR_CORE + r"\s+[QH][1-4]\b)", re.I), "m"),
    (
        re.compile(
            r"(?<![$\u20ac\u00a3\d.,])(?P<m>\b(?:from\s+)?"
            + _YEAR_CORE
            + r"\s*(?:to|[-\u2013\u2014]|vs\.?|versus)\s*"
            + _YEAR_CORE
            + r"\b)"
            + _MEASURE_FOLLOW,
            re.I,
        ),
        "m",
    ),
    (
        re.compile(
            r"(?<![$\u20ac\u00a3\d.,])\b(?:in|for|during|since|through|throughout|until|of|vs\.?|versus|"
            r"compared\s+(?:with|to)|fiscal\s+year|calendar\s+year|prior\s+year|full\s+year|year|"
            r"ended|ending|as\s+of)\s+(?P<m>" + _YEAR_CORE + r")\b" + _MEASURE_FOLLOW,
            re.I,
        ),
        "m",
    ),
    (
        re.compile(
            r"(?<![$\u20ac\u00a3\d.,])\b(?P<m>" + _YEAR_CORE + r")\b"
            r"(?=\s+(?:(?:gross|net|total|annual|operating|fiscal|calendar|actual|projected|prior|ytd)\s+)?"
            r"(?:revenue|sales|margin|income|profit|loss|ebitda|cost|spend|expenses?|budget|forecast|"
            r"target|actuals?|baseline|results?|performance|churn|retention|arr|mrr|bookings|pipeline)\b)",
            re.I,
        ),
        "m",
    ),
    (re.compile(r"(?P<m>\b\d+(?:st|nd|rd|th)\b)", re.I), "m"),
    (re.compile(r"(?!\b(?:USD|EUR|GBP)-\d)(?P<m>\b[A-Za-z]{2,}-\d+[A-Za-z0-9_-]*\b)", re.I), "m"),
    (re.compile(r"(?!\b(?:USD|EUR|GBP)\d)(?P<m>\b[A-Za-z]+\d+[A-Za-z0-9]*\b)"), "m"),
]

_NUM_RE = re.compile(
    r"(?P<sign>(?<![\d%$\u20ac\u00a3A-Za-z])[+\-\u2212](?=(?:US\$|[$\u20ac\u00a3])?\d|\.\d))?"
    r"(?P<cur_pre>US\$|[$\u20ac\u00a3]|(?:\b(?:USD|EUR|GBP)\b(?=[ \t]*[+\-\u2212]?\d)))?[ \t]*"
    r"(?P<sign2>(?<=[$\u20ac\u00a3\s])[+\-\u2212](?=\d|\.\d))?"
    r"(?P<num>"
    r"\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?"
    r"|\d{1,3}(?:\.\d{3})+,\d+"
    r"|\d{1,3}(?:[,\u00a0\u202f]\d{3})+(?:\.\d+)?"
    r"|\d+,\d{1,2}(?![,\d])"
    r"|\d+(?:\.\d+)?"
    r"|\.\d+"
    r")"
    r"(?:(?P<scale_sp>[ \t]+(?P<scale_w>trillions?|billions?|millions?|thousands?|mrd|mio|tn|bn|mn|mm|[KMBT]))"
    r"|(?P<scale_t>trillions?|billions?|millions?|thousands?|mrd|mio|tn|bn|mn|mm|[KMBTkmbt]))?(?!(?!x\b)[A-Za-z])"
    r"(?:[ \t]*(?P<cur_suf>[$\u20ac\u00a3]|\b(?:USD|EUR|GBP|dollars?|euros?|pounds?)\b))?"
    r"(?:[ \t]*(?P<unit_suf>%|percentage[ \t]+points?\b|pct[ \t]+pts?\b|percent\b|pct\b|pp\b|"
    r"basis[ \t]+points?\b|bps\b|units?\b|orders?\b|customers?\b|days?\b|hours?\b|"
    r"headcount\b|employees?\b|items?\b|counts?\b|ratios?\b)|(?P<mult_x>(?<=\d)x\b))?",
    re.I,
)

_ABBREV_RE = re.compile(
    r"\b(?:vs|v|approx|est|e\.g|i\.e|etc|inc|corp|ltd|co|mr|mrs|ms|dr|u\.s|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|no|fig)\.$",
    re.I,
)

_CHANGE_VERBS = (
    r"(?:rose|increased|grew|went|climbed|jumped|surged|expanded|improved|moved|shifted|changed|"
    r"fell|dropped|declined|decreased|slipped|dipped|shrank|contracted|slowed|reduced)"
)
_CHANGE_FROM_RE = re.compile(r"\b" + _CHANGE_VERBS + r"(?:\s+\w+){0,3}\s+from\s*$", re.I)
_CHANGE_BY_RE = re.compile(
    r"\b(?:" + _CHANGE_VERBS + r"|up|down|higher|lower)(?:\s+\w+){0,2}\s+by\s*$"
    r"|\b(?:up|down)\s*$",
    re.I,
)
_PRIOR_LEAD_RE = re.compile(
    r"\b(?:compared\s+(?:with|to)|versus|vs\.?|against|from\s+a\s+prior|prior\s+year(?:'s)?(?:\s+of)?|"
    r"up\s+from|down\s+from)\s*$",
    re.I,
)
_TARGET_LEAD_RE = re.compile(
    r"\b(?:" + _CHANGE_VERBS + r"|reached|totaled|totalling|was|is|were|stood\s+at|came\s+in\s+at)\s+(?:to\s+)?$",
    re.I,
)
_TO_BETWEEN_RE = re.compile(r"^\s*(?:in\s+[^,.;()]{1,25}\s+)?to\s*$", re.I)
_BY_TO_BETWEEN_RE = re.compile(r"^\s*(?:or\s+[^,.;()]{1,20}\s+)?to\s*$", re.I)
_FROM_VERB_TO_RE = re.compile(r"\b" + _CHANGE_VERBS + r"(?:\s+\w+){0,2}\s+to\s*$", re.I)
_POST_PRIOR_BETWEEN_RE = re.compile(
    r"^\s*[,;(]?\s*(?:which\s+(?:is|was)\s+)?"
    r"(?:(?:up|down|higher|lower)\s+(?:by\s+|from\s+)?|"
    r"an?\s+(?:increase|decrease|gain|drop|decline|rise|growth)\s+(?:of\s+|from\s+)|"
    r"(?:compared\s+(?:with|to)|versus|vs\.?|against|prior(?:\s+period|\s+year)?[:\s]))\s*$",
    re.I,
)
_DELTA_LEAD_RE = re.compile(
    r",\s*(?:an?\s+|representing\s+an?\s+)?(?:increase|decrease|gain|loss|rise|drop|growth|decline)\s+of\s*$",
    re.I,
)
_EXPLICIT_CUE_RE = re.compile(
    r"\b(?:answer\s+is|total(?:\s+\w+){0,2}\s+(?:is|was|of|to|equals?|reached|totaled)|"
    r"combined(?:\s+\w+){0,2}\s+(?:is|was|reached|totaled)|in\s+total[,:\s]|"
    r"grand\s+total(?:\s+is|\s+was|:)?|net\s+total(?:\s+is|\s+was|:)?|"
    r"overall(?:\s+\w+){0,2}\s+(?:is|was|reached|stands\s+at))\s*:?\s*$",
    re.I,
)
_SCOPE_MOD_RE = re.compile(
    r"\b(?:across(?:\s+all)?|among(?:\s+all)?|over(?:\s+the)?(?:\s+past|\s+last|\s+next)?|"
    r"within(?:\s+the)?|spanning|covering|top|first|last|past|next)\s+$",
    re.I,
)
_BETWEEN_LEAD_RE = re.compile(r"\bbetween\s*(?:approximately\s+|about\s+|roughly\s+|around\s+)?$", re.I)
_RANGE_DASH_RE = re.compile(r"^[ \t]*[\u2013\u2014~-][ \t]*$")
_RANGE_TO_RE = re.compile(r"^[ \t]*to[ \t]*$", re.I)
_RANGE_AND_RE = re.compile(r"^[ \t]*and[ \t]*$", re.I)
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$")
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")

_ABSTAIN_RE = re.compile(
    r"\b(?:cannot|can't|can\s+not|do\s+not\s+have|don't\s+have|does\s+not\s+have|doesn't\s+have|"
    r"not\s+available|unavailable|not\s+in\s+the|no\s+data|no\s+information|no\s+records?|"
    r"no\s+access|lack\s+access|restricted|not\s+authorized|unable\s+to|"
    r"outside\s+(?:the\s+)?scope|out\s+of\s+scope|does\s+not\s+contain|doesn't\s+contain|"
    r"cannot\s+determine|can't\s+determine|insufficient|not\s+tracked|not\s+included|"
    r"not\s+provided|not\s+found|beyond\s+the\s+available|decline\s+to\s+answer)\b",
    re.I,
)
_CLARIFY_RE = re.compile(
    r"\b(?:could\s+you\s+(?:please\s+)?clarify|please\s+(?:clarify|specify)|which\s+\w+\s+do\s+you\s+mean|"
    r"do\s+you\s+mean|would\s+you\s+like\s+to\s+see|can\s+you\s+specify)\b",
    re.I,
)
_DIR_UP_RE = re.compile(
    r"(?<!\bnot\s)(?<!\bno\s)(?<!\bnever\s)\b(?:increased?|increasing|up|rose|risen|rising|"
    r"grew|grown|growing|higher|gain(?:ed)?|climbed|jumped|surged|expanded|improved|positive|ahead)\b",
    re.I,
)
_DIR_DOWN_RE = re.compile(
    r"(?<!\bnot\s)(?<!\bno\s)(?<!\bnever\s)\b(?:decreased?|decreasing|down|fell|fallen|falling|"
    r"dropped|dropping|declined?|declining|lower|loss|shrank|shrunk|contracted|slipped|dipped|negative|behind)\b",
    re.I,
)
_DIR_FLAT_RE = re.compile(
    r"\b(?:flat|unchanged|steady|stable|remained\s+(?:the\s+)?same|no\s+change|constant|level)\b",
    re.I,
)

_DEFAULT_GATE_CONFIG: dict[str, Any] = {
    "version": 1,
    "default_profile": "auto",
    "profiles": {
        "with_engine_evidence": {
            "description": "Requires value match, citation routing, and observed semantic-model DAX routing.",
            "routing_evidence": "engine+citations",
            "gates": ["value", "artifact", "model"],
            "incomplete_on_missing_trace": True,
        },
        "without_engine_evidence": {
            "description": "Requires value match and citation routing when engine DAX telemetry is unavailable.",
            "routing_evidence": "citations-only",
            "gates": ["value", "artifact"],
            "incomplete_on_missing_trace": False,
        },
        "tool_call_evidence": {
            "description": "Requires value match and verified MCP/agent tool-call routing.",
            "routing_evidence": "tool_call",
            "gates": ["value", "model"],
            "incomplete_on_missing_trace": False,
        },
        "work_iq": {
            "description": "Workplace M365 grounding where semantic-model DAX does not apply.",
            "routing_evidence": "citations-only",
            "gates": ["value", "artifact"],
            "incomplete_on_missing_trace": False,
        },
    },
    "thresholds": {
        "min_pass_rate": 0.85,
        "max_critical_failures": 0,
        "max_inconclusive_rate": 0.10,
        "max_error_count": 0,
    },
}


def _dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return default
    try:
        number = Decimal(str(value).strip())
        return number if number.is_finite() else default
    except (InvalidOperation, ValueError):
        return default


def show(number: Any) -> str:
    """Readable number for reasons: 12840000.0 -> 12,840,000; 41.60 -> 41.6."""
    d = _dec(number)
    if d is None:
        return str(number)
    return format(d.normalize(), ",f")


def _mask_preserving_offsets(text: str) -> str:
    chars = list(text)
    for pattern, group_name in _MASK_FULL_PATTERNS:
        current = "".join(chars)
        for m in pattern.finditer(current):
            s, e = m.span(group_name) if group_name else m.span()
            for idx in range(s, e):
                if chars[idx] != "\n":
                    chars[idx] = " "
    return "".join(chars)


def clean_text(text: str | None) -> str:
    """Remove URLs, dates, fiscal labels and contextual years while preserving measure numbers."""
    return _mask_preserving_offsets(text or "")


def _check_dict(passed: int, reason: str, **details: Any) -> dict[str, Any]:
    score = PASS if passed == 1 else FAIL if passed == 0 else INCONCLUSIVE
    outcome = "PASS" if passed == 1 else "FAIL" if passed == 0 else "INCONCLUSIVE"
    out: dict[str, Any] = {
        "passed": passed,
        "score": score,
        "outcome": outcome,
        "reason": reason,
        "detail": reason,
    }
    out.update(details)
    return out


def _result(score: float, reason: str, **details: Any) -> dict[str, Any]:
    passed = 1 if score == PASS else 0 if score == FAIL else -1
    return _check_dict(passed, reason, **details)


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [
        re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2) or "", c.strip())
        for c in stripped.split("|")
    ]
    return cells


def _find_markdown_tables(text: str) -> list[dict[str, Any]]:
    if "|" not in text:
        return []
    lines = text.splitlines(keepends=True)
    offsets: list[tuple[int, int, str]] = []
    pos = 0
    for ln in lines:
        offsets.append((pos, pos + len(ln), ln.rstrip("\r\n")))
        pos += len(ln)

    tables: list[dict[str, Any]] = []
    i = 0
    n = len(offsets)
    while i + 1 < n:
        h_start, _, h_line = offsets[i]
        _, s_end, s_line = offsets[i + 1]
        if "|" in h_line and _TABLE_SEP_RE.match(s_line):
            headers = _split_pipe_row(h_line)
            if len(headers) >= 2:
                rows: list[list[str]] = []
                t_end = s_end
                j = i + 2
                while j < n:
                    _, r_end, r_line = offsets[j]
                    if "|" not in r_line or not r_line.strip():
                        break
                    if _TABLE_SEP_RE.match(r_line):
                        t_end = r_end
                        j += 1
                        continue
                    row_cells = _split_pipe_row(r_line)
                    rows.append(row_cells)
                    t_end = r_end
                    j += 1
                tables.append(
                    {
                        "headers": headers,
                        "rows": rows,
                        "start": h_start,
                        "end": t_end,
                    }
                )
                i = j
                continue
        i += 1
    return tables


def parse_markdown_table(text: str) -> dict[str, Any] | None:
    """Parse the first GitHub-flavored Markdown table into {'headers': [...], 'rows': [[...]]}."""
    tables = _find_markdown_tables(text or "")
    if not tables:
        return None
    first = tables[0]
    return {"headers": first["headers"], "rows": first["rows"]}


def _bold_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", text):
        spans.append(m.span())
    return spans


def _paren_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for idx, ch in enumerate(text):
        if ch == "(":
            stack.append(idx)
        elif ch == ")" and stack:
            start = stack.pop()
            spans.append((start, idx))
    return spans


def _first_sentence_end(text: str, tables: list[dict[str, Any]]) -> int:
    if not text or not text.strip():
        return -1
    lstripped = text.lstrip()
    lead_offset = len(text) - len(lstripped)
    if tables and tables[0]["start"] <= lead_offset:
        return -1
    non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]
    if (
        len(non_empty_lines) >= 2
        and _BULLET_LINE_RE.match(non_empty_lines[0])
        and _BULLET_LINE_RE.match(non_empty_lines[1])
    ):
        return -1

    depth = 0
    n = len(text)
    for idx in range(lead_offset, n):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == "\n" and depth == 0:
            return idx
        elif ch in ".!?" and depth == 0:
            if ch == "." and idx + 1 < n and text[idx + 1].isdigit():
                continue
            prefix = text[max(lead_offset, idx - 12) : idx + 1]
            if ch == "." and _ABBREV_RE.search(prefix):
                continue
            if idx + 1 == n or text[idx + 1].isspace():
                return idx + 1
    return n


def _parse_locale_decimal(raw_num: str, number_locale: str = "auto") -> tuple[Decimal | None, int, int]:
    """Return (decimal_value, decimal_places, significant_figures)."""
    cleaned = re.sub(r"[\u00a0\u202f ]", "", raw_num)
    loc = (number_locale or "auto").lower()

    has_dot = "." in cleaned
    has_comma = "," in cleaned
    normalized = cleaned

    if has_dot and has_comma:
        if cleaned.rfind(",") > cleaned.rfind("."):
            normalized = cleaned.replace(".", "").replace(",", ".")
        else:
            normalized = cleaned.replace(",", "")
    elif has_comma and not has_dot:
        parts = cleaned.split(",")
        if loc == "eu" or (len(parts) == 2 and len(parts[1]) in (1, 2)):
            normalized = cleaned.replace(",", ".")
        else:
            normalized = cleaned.replace(",", "")
    elif has_dot and not has_comma:
        parts = cleaned.split(".")
        if len(parts) >= 3 and all(len(p) == 3 for p in parts[1:]):
            normalized = cleaned.replace(".", "")
        elif loc == "eu" and len(parts) == 2 and len(parts[1]) == 3 and parts[0] != "0":
            normalized = cleaned.replace(".", "")

    try:
        dec_val = Decimal(normalized)
    except InvalidOperation:
        return None, 0, 0

    decimals = len(normalized.split(".", 1)[1]) if "." in normalized else 0
    digits_only = normalized.replace(".", "").lstrip("0")
    if not digits_only:
        sig_figs = 1
    elif decimals > 0:
        sig_figs = len(digits_only)
    else:
        sig_figs = len(digits_only.rstrip("0")) or 1
    return dec_val, decimals, sig_figs


def _canonical_unit(unit_raw: str) -> tuple[str, str]:
    u = " ".join((unit_raw or "").strip().lower().split())
    if not u:
        return "", ""
    if u in _CURRENCY_MAP:
        return "currency", _CURRENCY_MAP[u]
    if u == "currency":
        return "currency", ""
    return _UNIT_CANON.get(u, u), ""


def _sentence_start_before(text: str, pos: int) -> int:
    idx = pos - 1
    while idx >= 0:
        ch = text[idx]
        if ch == "\n":
            return idx + 1
        if ch in ".!?" and (idx + 1 >= len(text) or text[idx + 1].isspace()):
            prefix = text[max(0, idx - 12) : idx + 1]
            if not (ch == "." and _ABBREV_RE.search(prefix)):
                return idx + 1
        idx -= 1
    return 0


def extract_numbers(text: str, *, number_locale: str = "auto") -> list[dict[str, Any]]:
    """Extract numeric candidates with unit, currency, scale, and discourse metadata."""
    raw_text = text or ""
    if not raw_text.strip():
        return []

    masked = _mask_preserving_offsets(raw_text)
    tables = _find_markdown_tables(raw_text)
    bolds = _bold_spans(raw_text)
    parens = _paren_spans(raw_text)
    first_sent_end = _first_sentence_end(raw_text, tables)

    candidates: list[dict[str, Any]] = []
    for m in _NUM_RE.finditer(masked):
        raw_num = m.group("num")
        if not raw_num:
            continue
        s, e = m.span()
        if m.group("cur_suf") and not m.group("unit_suf") and not m.group("mult_x"):
            e = m.end("cur_suf")
        elif m.group("unit_suf") or m.group("mult_x"):
            e = m.end("unit_suf") if m.group("unit_suf") else m.end("mult_x")

        # expand to include optional euro/dollar after space if missed (e.g., "12.840.000 €")
        base_dec, decimals, sig_figs = _parse_locale_decimal(raw_num, number_locale=number_locale)
        if base_dec is None:
            continue

        scale_tok = (m.group("scale_w") or m.group("scale_t") or "").lower()
        scale_dec = _SCALES.get(scale_tok, Decimal(1))
        has_scale_word = scale_dec != Decimal(1)

        sign_str = (m.group("sign") or m.group("sign2") or "").strip()
        is_neg = sign_str in ("-", "\u2212")

        cur_tok = (m.group("cur_pre") or m.group("cur_suf") or "").strip().lower()
        currency = _CURRENCY_MAP.get(cur_tok, "")

        unit_tok = (m.group("unit_suf") or ("x" if m.group("mult_x") else "")).strip().lower()
        unit_tok_norm = " ".join(unit_tok.split())
        if currency:
            unit = "currency"
        elif unit_tok_norm:
            unit = _UNIT_CANON.get(unit_tok_norm, unit_tok_norm)
        else:
            unit = ""

        # Check enclosing parentheses & accounting negative notation like ($420K)
        enclosing_parens = [(ps, pe) for ps, pe in parens if ps < s and e <= pe]
        in_parens = bool(enclosing_parens)
        span_text = raw_text[s:e]

        if enclosing_parens:
            ps, pe = enclosing_parens[-1]
            inner = raw_text[ps + 1 : pe].strip()
            sent_start = _sentence_start_before(raw_text, ps)
            prior_same_clause = any(c["_start"] >= sent_start and c["_end"] <= ps for c in candidates)
            if inner == span_text.strip() and not prior_same_clause and not is_neg:
                is_neg = True
                in_parens = False
                s, e = ps, pe + 1
                span_text = raw_text[s:e]

        val_dec = base_dec * scale_dec * (Decimal(-1) if is_neg else Decimal(1))
        ulp_dec = Decimal(1).scaleb(-decimals) * scale_dec

        is_table_cell = any(t["start"] <= s and e <= t["end"] for t in tables)
        is_bold = any(bs <= s and e <= be for bs, be in bolds)
        in_first_sentence = (not is_table_cell) and (first_sent_end > 0) and (e <= first_sent_end)

        sent_start = _sentence_start_before(raw_text, s)
        lead_ctx = raw_text[sent_start:s]
        line_start = raw_text.rfind("\n", 0, s) + 1
        is_bullet = bool(_BULLET_LINE_RE.match(raw_text[line_start:e]))
        is_explicit_cue = bool(_EXPLICIT_CUE_RE.search(lead_ctx))
        is_scope_modifier = bool(_SCOPE_MOD_RE.search(lead_ctx))
        is_delta = bool(_DELTA_LEAD_RE.search(lead_ctx))

        candidates.append(
            {
                "value": float(val_dec),
                "unit": unit,
                "raw": span_text.strip(),
                "currency": currency,
                "span": span_text.strip(),
                "scale": float(scale_dec),
                "in_parens": in_parens,
                "is_bold": is_bold,
                "in_first_sentence": in_first_sentence,
                "is_change_target": False,
                "is_change_prior": False,
                "is_table_cell": is_table_cell,
                "sig_figs": sig_figs,
                "decimals": decimals,
                "has_scale_word": has_scale_word,
                "ulp": float(ulp_dec),
                "_decimal": val_dec,
                "_step": ulp_dec,
                "_start": s,
                "_end": e,
                "_sent_start": sent_start,
                "_is_bullet": is_bullet,
                "_is_explicit_cue": is_explicit_cue,
                "_is_scope_modifier": is_scope_modifier,
                "_is_delta": is_delta,
                "_in_range": False,
            }
        )

    # Classify change clauses BEFORE range detection
    change_pairs: set[tuple[int, int]] = set()
    for idx, cand in enumerate(candidates):
        s = cand["_start"]
        sent_start = cand["_sent_start"]
        before = raw_text[sent_start:s]
        if _PRIOR_LEAD_RE.search(before):
            cand["is_change_prior"] = True
            if idx + 1 < len(candidates) and candidates[idx + 1]["_sent_start"] == sent_start:
                before_next = raw_text[cand["_end"] : candidates[idx + 1]["_start"]]
                if _TARGET_LEAD_RE.search(before_next):
                    candidates[idx + 1]["is_change_target"] = True
                    change_pairs.add((idx, idx + 1))

        if idx + 1 < len(candidates):
            nxt = candidates[idx + 1]
            if nxt["_sent_start"] != sent_start or cand["is_table_cell"] or nxt["is_table_cell"]:
                continue
            between = raw_text[cand["_end"] : nxt["_start"]]

            if _CHANGE_FROM_RE.search(before) and _TO_BETWEEN_RE.match(between):
                cand["is_change_prior"] = True
                nxt["is_change_target"] = True
                change_pairs.add((idx, idx + 1))
            elif _CHANGE_BY_RE.search(before) and _BY_TO_BETWEEN_RE.match(between):
                cand["is_change_prior"] = True
                nxt["is_change_target"] = True
                change_pairs.add((idx, idx + 1))
            elif re.search(r"\bfrom\s*$", before, re.I) and _FROM_VERB_TO_RE.search(between):
                cand["is_change_prior"] = True
                nxt["is_change_target"] = True
                change_pairs.add((idx, idx + 1))
            elif _POST_PRIOR_BETWEEN_RE.match(between):
                if not cand["is_change_prior"] and not cand["_is_scope_modifier"]:
                    cand["is_change_target"] = True
                nxt["is_change_prior"] = True
                change_pairs.add((idx, idx + 1))
                # Handle 3-part "Y, up D from X"
                if idx + 2 < len(candidates) and candidates[idx + 2]["_sent_start"] == sent_start:
                    between_2 = raw_text[nxt["_end"] : candidates[idx + 2]["_start"]]
                    if re.match(r"^\s*(?:from|vs\.?|versus|compared\s+(?:with|to))\s*$", between_2, re.I):
                        candidates[idx + 2]["is_change_prior"] = True
                        change_pairs.add((idx + 1, idx + 2))

    # True range detection ONLY on non-change pairs
    for idx in range(len(candidates) - 1):
        if (idx, idx + 1) in change_pairs:
            continue
        c1 = candidates[idx]
        c2 = candidates[idx + 1]
        if c1["is_table_cell"] or c2["is_table_cell"] or c1["_sent_start"] != c2["_sent_start"]:
            continue
        before = raw_text[c1["_sent_start"] : c1["_start"]]
        between = raw_text[c1["_end"] : c2["_start"]]
        is_range = False
        if _BETWEEN_LEAD_RE.search(before) and _RANGE_AND_RE.match(between):
            is_range = True
        elif _RANGE_DASH_RE.match(between):
            is_range = True
        elif _RANGE_TO_RE.match(between) and not c1["is_change_prior"] and not c2["is_change_target"]:
            is_range = True

        if is_range:
            c1["_in_range"] = True
            c2["_in_range"] = True
            if not c1["unit"] and c2["unit"]:
                c1["unit"] = c2["unit"]
                c1["currency"] = c2["currency"]
            if not c1["has_scale_word"] and c2["has_scale_word"] and c1["scale"] == 1.0:
                c1["scale"] = c2["scale"]
                c1["has_scale_word"] = True
                c1["value"] = c1["value"] * c2["scale"]
                c1["ulp"] = c1["ulp"] * c2["scale"]

    return candidates


def parse_numbers(text: str, *, number_locale: str = "auto") -> list[dict[str, Any]]:
    """Backwards-compatible v1 wrapper returning Decimal values and kind/step metadata."""
    out: list[dict[str, Any]] = []
    for c in extract_numbers(text, number_locale=number_locale):
        if c["unit"] == "percent":
            kind = "percent"
        elif c["unit"] == "currency":
            kind = "currency"
        else:
            kind = "number"
        out.append(
            {
                "value": c["_decimal"],
                "raw": c["raw"],
                "kind": kind,
                "scaled": c["has_scale_word"],
                "decimals": c["decimals"],
                "step": c["_step"],
                "unit": c["unit"],
                "currency": c["currency"],
                "span": c["span"],
            }
        )
    return out


def candidates_for_unit(numbers: list[dict[str, Any]], unit: str) -> list[dict[str, Any]]:
    """Pick the numbers compatible with the expected unit, best tier first (v1 helper)."""
    u = (unit or "number").lower()
    if u in ("percent", "%"):
        tiers = [
            [n for n in numbers if n.get("kind") == "percent"],
            [
                n
                for n in numbers
                if n.get("kind") == "number"
                and Decimal(0) < abs(Decimal(str(n["value"]))) <= Decimal(1)
                and n.get("decimals", 0) > 0
            ],
        ]
    elif u == "currency":
        tiers = [
            [n for n in numbers if n.get("kind") == "currency"],
            [n for n in numbers if n.get("kind") == "number" and n.get("scaled")],
            [n for n in numbers if n.get("kind") == "number"],
        ]
    else:
        tiers = [
            [n for n in numbers if n.get("kind") == "number" and not n.get("scaled")],
            [n for n in numbers if n.get("kind") == "number"],
            [n for n in numbers if n.get("kind") == "currency"],
        ]
    for tier in tiers:
        if tier:
            return tier
    return []


def _select_unit_compatible(
    all_cands: list[dict[str, Any]],
    expected_unit: str,
    expected_currency: str,
) -> list[dict[str, Any]]:
    norm_unit, implied_cur = _canonical_unit(expected_unit)
    norm_cur = _CURRENCY_MAP.get((expected_currency or "").strip().lower(), (expected_currency or "").strip().upper())
    if not norm_cur and implied_cur:
        norm_cur = implied_cur

    def cur_ok(c: dict[str, Any], *, require_explicit: bool = False) -> bool:
        if not norm_cur:
            return True
        if c["currency"] and c["currency"] != norm_cur:
            return False
        if require_explicit:
            return bool(c["currency"] == norm_cur)
        return True

    if norm_unit == "currency":
        if norm_cur:
            tiers = [[c for c in all_cands if c["unit"] == "currency" and c["currency"] == norm_cur]]
            has_conflict = any(c["currency"] and c["currency"] != norm_cur for c in all_cands)
            if not has_conflict:
                tiers.append([c for c in all_cands if c["unit"] == "" and c["has_scale_word"]])
        else:
            tiers = [
                [c for c in all_cands if c["unit"] == "currency"],
                [c for c in all_cands if c["unit"] == "" and c["has_scale_word"]],
                [c for c in all_cands if c["unit"] == ""],
            ]
    elif norm_unit == "percent":
        tiers = [
            [c for c in all_cands if c["unit"] == "percent"],
            [c for c in all_cands if c["unit"] == "pp"],
            [c for c in all_cands if c["unit"] == "" and 0.0 < abs(c["value"]) <= 1.0 and c["decimals"] >= 1],
        ]
    elif norm_unit == "pp":
        tiers = [
            [c for c in all_cands if c["unit"] == "pp"],
            [c for c in all_cands if c["unit"] == "percent"],
        ]
    elif norm_unit == "bps":
        tiers = [[c for c in all_cands if c["unit"] == "bps"]]
    elif norm_unit in ("ratio", "x"):
        tiers = [
            [c for c in all_cands if c["unit"] in ("ratio", "x")],
            [c for c in all_cands if c["unit"] in ("", "count") and cur_ok(c)],
        ]
    elif norm_unit in ("units", "orders", "customers", "days", "hours", "headcount", "employees", "items"):
        tiers = [
            [c for c in all_cands if c["unit"] == norm_unit],
            [c for c in all_cands if c["unit"] in ("", "count") and cur_ok(c)],
        ]
    elif norm_unit == "count":
        count_units = (
            "units",
            "orders",
            "customers",
            "days",
            "hours",
            "headcount",
            "employees",
            "items",
            "count",
            "",
        )
        tiers = [[c for c in all_cands if c["unit"] in count_units and cur_ok(c)]]
    else:  # "number" or ""
        if norm_cur:
            tiers = [[c for c in all_cands if cur_ok(c, require_explicit=True)]]
            if not any(c["currency"] and c["currency"] != norm_cur for c in all_cands):
                tiers.append([c for c in all_cands if c["currency"] == ""])
        else:
            tiers = [[c for c in all_cands if cur_ok(c)]]

    for tier in tiers:
        if tier:
            return tier
    return []


def _discourse_tier(c: dict[str, Any]) -> int:
    if c["in_parens"] and c["is_change_prior"]:
        return 80
    if c["in_parens"]:
        return 75
    if c["is_change_prior"]:
        return 70
    if c["_is_delta"]:
        return 68
    if c["_is_scope_modifier"]:
        return 65
    if c["_is_bullet"]:
        if c["_is_explicit_cue"]:
            return 28
        return 50
    if (c["is_change_target"] and c["in_first_sentence"]) or (c["is_bold"] and c["in_first_sentence"]):
        return 10
    if c["_is_explicit_cue"] and (c["is_bold"] or c["in_first_sentence"]):
        return 12
    if c["is_change_target"] or c["is_bold"]:
        return 18
    if c["in_first_sentence"]:
        return 22
    if c["_is_explicit_cue"]:
        return 28
    return 40


def _public_cand(c: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in c.items() if not k.startswith("_")}


def _distinct_value_clusters(cands: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for c in cands:
        val = c["value"]
        placed = False
        for cl in clusters:
            ref = cl[0]["value"]
            if abs(val - ref) <= max(1e-9, abs(ref) * 1e-9):
                cl.append(c)
                placed = True
                break
        if not placed:
            clusters.append([c])
    return clusters


def extract_answer_value(
    text: str,
    expected_unit: str = "",
    expected_currency: str = "",
    *,
    number_locale: str = "auto",
) -> dict[str, Any]:
    """Select the primary discourse scalar without consulting the expected numeric value."""
    raw_text = text or ""
    tables = _find_markdown_tables(raw_text)
    all_cands = extract_numbers(raw_text, number_locale=number_locale)
    compatible = _select_unit_compatible(all_cands, expected_unit, expected_currency)
    public_compat = [_public_cand(c) for c in compatible]

    if not compatible:
        # Check if any range existed even before unit filtering when unit is empty/compatible
        range_any = [c for c in all_cands if c["_in_range"]]
        if range_any and not expected_currency:
            norm_u, _ = _canonical_unit(expected_unit)
            if norm_u in ("", "number") or any(c["unit"] == norm_u for c in range_any):
                return {
                    "status": "range",
                    "value": None,
                    "unit": range_any[0]["unit"],
                    "currency": range_any[0]["currency"],
                    "span": range_any[0]["span"],
                    "scale": range_any[0]["scale"],
                    "sig_figs": range_any[0]["sig_figs"],
                    "has_scale_word": range_any[0]["has_scale_word"],
                    "candidates": public_compat,
                }
        return {
            "status": "none",
            "value": None,
            "unit": "",
            "currency": "",
            "span": "",
            "scale": 1.0,
            "sig_figs": 0,
            "has_scale_word": False,
            "candidates": [],
        }

    non_table = [c for c in compatible if not c["is_table_cell"]]
    in_table = [c for c in compatible if c["is_table_cell"]]

    if not non_table:
        max_table_rows = max((len(t["rows"]) for t in tables), default=0)
        if max_table_rows >= 2:
            return {
                "status": "ambiguous",
                "value": None,
                "unit": in_table[0]["unit"],
                "currency": in_table[0]["currency"],
                "span": "",
                "scale": in_table[0]["scale"],
                "sig_figs": 0,
                "has_scale_word": False,
                "candidates": public_compat,
            }
        clusters = _distinct_value_clusters(in_table)
        if len(clusters) == 1:
            best = max(clusters[0], key=lambda x: x["sig_figs"])
            return {
                "status": "ok",
                "value": best["value"],
                "unit": best["unit"],
                "currency": best["currency"],
                "span": best["span"],
                "scale": best["scale"],
                "sig_figs": best["sig_figs"],
                "decimals": best["decimals"],
                "ulp": best["ulp"],
                "has_scale_word": best["has_scale_word"],
                "candidates": public_compat,
            }
        return {
            "status": "ambiguous",
            "value": None,
            "unit": in_table[0]["unit"],
            "currency": in_table[0]["currency"],
            "span": "",
            "scale": in_table[0]["scale"],
            "sig_figs": 0,
            "has_scale_word": False,
            "candidates": public_compat,
        }

    range_cands = [c for c in non_table if c["_in_range"]]
    non_range = [c for c in non_table if not c["_in_range"]]

    if range_cands:
        primary_scalars = [
            c
            for c in non_range
            if not c["in_parens"] and not c["is_change_prior"] and not c["_is_scope_modifier"] and not c["_is_delta"]
        ]
        lead_range = any(not r["in_parens"] and r["in_first_sentence"] for r in range_cands)
        strong_override = any(c["is_bold"] or c["_is_explicit_cue"] for c in primary_scalars)
        if not primary_scalars or (lead_range and not strong_override):
            r0 = range_cands[0]
            return {
                "status": "range",
                "value": None,
                "unit": r0["unit"],
                "currency": r0["currency"],
                "span": r0["span"],
                "scale": r0["scale"],
                "sig_figs": r0["sig_figs"],
                "has_scale_word": r0["has_scale_word"],
                "candidates": public_compat,
            }

    best_tier = min(_discourse_tier(c) for c in non_range)
    top_cands = [c for c in non_range if _discourse_tier(c) == best_tier]
    clusters = _distinct_value_clusters(top_cands)

    if len(clusters) > 1:
        return {
            "status": "ambiguous",
            "value": None,
            "unit": top_cands[0]["unit"],
            "currency": top_cands[0]["currency"],
            "span": "",
            "scale": top_cands[0]["scale"],
            "sig_figs": 0,
            "has_scale_word": False,
            "candidates": public_compat,
        }

    best = max(clusters[0], key=lambda x: x["sig_figs"])
    return {
        "status": "ok",
        "value": best["value"],
        "unit": best["unit"],
        "currency": best["currency"],
        "span": best["span"],
        "scale": best["scale"],
        "sig_figs": best["sig_figs"],
        "decimals": best["decimals"],
        "ulp": best["ulp"],
        "has_scale_word": best["has_scale_word"],
        "candidates": public_compat,
    }


def _find_item_pos(norm_text: str, raw_lower: str, item: Any) -> int:
    variants: list[str] = []
    if isinstance(item, dict):
        if item.get("name"):
            variants.append(str(item["name"]))
        variants.extend(str(a) for a in (item.get("aliases") or []))
    else:
        variants.extend(p.strip() for p in str(item).split("|") if p.strip())

    best_pos = -1
    for var in variants:
        v_low = var.lower().strip()
        if not v_low:
            continue
        idx = raw_lower.find(v_low)
        if idx == -1:
            v_norm = normalize_name(var)
            idx = norm_text.find(v_norm) if v_norm else -1
        if idx != -1 and (best_pos == -1 or idx < best_pos):
            best_pos = idx
    return best_pos


def _score_rich_expectation(
    text: str,
    case_type: str,
    expected: Any,
    expect: dict[str, Any] | None,
    expected_unit: str,
    rel_tol: float,
    abs_tol: float | None,
    display_tol: float,
    expected_currency: str,
    number_locale: str,
    percent_accepts_ratio: bool,
) -> dict[str, Any]:
    raw_text = text or ""
    raw_lower = raw_text.lower()
    norm_text = normalize_name(raw_text)
    spec = dict(expect or {})
    ct = case_type.lower().strip()

    if ct == "ranked_list":
        items = list(spec.get("items") or [])
        top_n = spec.get("top_n")
        if isinstance(top_n, int) and top_n > 0:
            items = items[:top_n]
        ordered = bool(spec.get("ordered", True))
        forbidden = list(spec.get("forbidden_items") or spec.get("forbidden") or [])
        for f_item in forbidden:
            if _find_item_pos(norm_text, raw_lower, f_item) != -1:
                return _check_dict(0, f"forbidden item present: {f_item}", match_kind="forbidden_item", extracted=None)
        if not items:
            return _check_dict(-1, "ranked_list expectation has no items", match_kind="no_expectation", extracted=None)
        positions = [_find_item_pos(norm_text, raw_lower, it) for it in items]
        missing = [str(items[i]) for i, p in enumerate(positions) if p == -1]
        if missing:
            return _check_dict(
                0,
                f"missing expected items: {', '.join(missing)}",
                match_kind="missing_items",
                extracted=None,
            )
        if ordered and any(positions[i] >= positions[i + 1] for i in range(len(positions) - 1)):
            return _check_dict(
                0, "items present but out of expected rank order", match_kind="wrong_order", extracted=None
            )
        return _check_dict(1, "all ranked items matched in order", match_kind="ranked_list_match", extracted=None)

    if ct == "set":
        if spec.get("ordered") is True:
            rk = _score_rich_expectation(
                text,
                "ranked_list",
                expected,
                spec,
                expected_unit,
                rel_tol,
                abs_tol,
                display_tol,
                expected_currency,
                number_locale,
                percent_accepts_ratio,
            )
            if rk["passed"] == 1:
                rk["match_kind"] = "set_match"
            return rk
        items = list(spec.get("items") or [])
        forbidden = list(spec.get("forbidden_items") or spec.get("forbidden") or [])
        for f_item in forbidden:
            if _find_item_pos(norm_text, raw_lower, f_item) != -1:
                return _check_dict(0, f"forbidden item present: {f_item}", match_kind="forbidden_item", extracted=None)
        if not items:
            return _check_dict(-1, "set expectation has no items", match_kind="no_expectation", extracted=None)
        found = [it for it in items if _find_item_pos(norm_text, raw_lower, it) != -1]
        min_overlap = spec.get("min_overlap")
        if min_overlap is None:
            ok = len(found) == len(items)
        elif isinstance(min_overlap, float) and 0.0 < min_overlap <= 1.0:
            ok = (len(found) / len(items)) >= min_overlap - 1e-12
        else:
            ok = len(found) >= int(min_overlap)
        if ok:
            return _check_dict(
                1, f"matched {len(found)}/{len(items)} set items", match_kind="set_match", extracted=None
            )
        missing = [str(it) for it in items if it not in found]
        return _check_dict(0, f"missing set items: {', '.join(missing)}", match_kind="missing_items", extracted=None)

    if ct == "table":
        exp_rows: list[dict[str, Any]] = list(spec.get("rows") or [])
        if not exp_rows:
            return _check_dict(-1, "table expectation has no rows", match_kind="no_expectation", extracted=None)
        parsed_tbl = parse_markdown_table(raw_text)
        row_tol = float(spec.get("rel_tol", rel_tol))
        row_abs = spec.get("abs_tol", abs_tol)
        row_disp = float(spec.get("display_tol", display_tol))
        key_col = str(spec.get("key") or "")

        if parsed_tbl is not None:
            headers = parsed_tbl["headers"]
            rows = parsed_tbl["rows"]

            def resolve_col_idx(col_name: str) -> int:
                cn = normalize_name(col_name)
                for idx, h in enumerate(headers):
                    hn = normalize_name(h)
                    if hn == cn or (cn and cn in hn) or (hn and hn in cn):
                        return idx
                return -1

            for exp_row in exp_rows:
                matched_actual: list[str] | None = None
                if key_col and key_col in exp_row:
                    k_idx = resolve_col_idx(key_col)
                    if k_idx == -1:
                        return _check_dict(
                            0, f"missing table column: {key_col}", match_kind="table_mismatch", extracted=None
                        )
                    target_key = normalize_name(str(exp_row[key_col]))
                    for r in rows:
                        if k_idx < len(r) and normalize_name(r[k_idx]) == target_key:
                            matched_actual = r
                            break
                else:
                    for r in rows:
                        row_text = " | ".join(r)
                        if all(
                            (
                                value_check(
                                    row_text,
                                    v,
                                    rel_tol=row_tol,
                                    abs_tol=row_abs,
                                    display_tol=row_disp,
                                    number_locale=number_locale,
                                    percent_accepts_ratio=percent_accepts_ratio,
                                )["passed"]
                                == 1
                                if isinstance(v, (int, float)) and not isinstance(v, bool)
                                else normalize_name(str(v)) in normalize_name(row_text)
                            )
                            for v in exp_row.values()
                        ):
                            matched_actual = r
                            break

                if matched_actual is None:
                    return _check_dict(
                        0, f"expected table row not found: {exp_row}", match_kind="table_mismatch", extracted=None
                    )

                for col_name, exp_cell in exp_row.items():
                    if col_name == key_col:
                        continue
                    c_idx = resolve_col_idx(col_name)
                    if c_idx == -1 or c_idx >= len(matched_actual):
                        return _check_dict(
                            0, f"missing table column: {col_name}", match_kind="table_mismatch", extracted=None
                        )
                    cell_str = matched_actual[c_idx]
                    if isinstance(exp_cell, (int, float)) and not isinstance(exp_cell, bool):
                        col_unit = (
                            "percent" if any(w in col_name.lower() for w in ("margin", "rate", "pct", "%")) else ""
                        )
                        vc = value_check(
                            cell_str,
                            float(exp_cell),
                            expected_unit=col_unit,
                            rel_tol=row_tol,
                            abs_tol=row_abs,
                            display_tol=row_disp,
                            number_locale=number_locale,
                            percent_accepts_ratio=percent_accepts_ratio,
                        )
                        if vc["passed"] != 1:
                            return _check_dict(
                                0,
                                f"table cell mismatch for {col_name}: got {cell_str!r}, expected {exp_cell}",
                                match_kind="table_mismatch",
                                extracted=vc.get("extracted"),
                            )
                    else:
                        if normalize_name(str(exp_cell)) not in normalize_name(cell_str):
                            return _check_dict(
                                0,
                                f"table cell text mismatch for {col_name}: got {cell_str!r}, expected {exp_cell!r}",
                                match_kind="table_mismatch",
                                extracted=None,
                            )
            return _check_dict(1, f"matched all {len(exp_rows)} table rows", match_kind="table_match", extracted=None)

        return _check_dict(0, "no Markdown table found in answer", match_kind="table_mismatch", extracted=None)

    if ct == "record":
        fields: dict[str, Any] = dict(spec.get("fields") or {})
        if not fields:
            return _check_dict(-1, "record expectation has no fields", match_kind="no_expectation", extracted=None)
        rec_tol = float(spec.get("rel_tol", rel_tol))
        rec_abs = spec.get("abs_tol", abs_tol)
        rec_disp = float(spec.get("display_tol", display_tol))

        parsed_tbl = parse_markdown_table(raw_text)
        field_positions: list[tuple[int, str]] = []
        for fname in fields:
            m_f = re.search(re.escape(fname), raw_text, re.I)
            if m_f:
                field_positions.append((m_f.start(), fname))
        field_positions.sort()

        for fname, fval in fields.items():
            segment = ""
            if parsed_tbl is not None:
                # Check two-column key/value table or multi-column header table
                col_idx = -1
                for idx, h in enumerate(parsed_tbl["headers"]):
                    if normalize_name(fname) in normalize_name(h):
                        col_idx = idx
                        break
                if col_idx != -1 and parsed_tbl["rows"] and col_idx < len(parsed_tbl["rows"][0]):
                    segment = parsed_tbl["rows"][0][col_idx]
                else:
                    for r in parsed_tbl["rows"]:
                        if r and normalize_name(fname) in normalize_name(r[0]) and len(r) >= 2:
                            segment = " ".join(r[1:])
                            break
            if not segment:
                m_f = re.search(re.escape(fname), raw_text, re.I)
                if not m_f:
                    return _check_dict(
                        0, f"missing record field: {fname}", match_kind="record_mismatch", extracted=None
                    )
                seg_start = m_f.end()
                next_starts = [pos for pos, other in field_positions if pos > m_f.start() and other != fname]
                nl_pos = raw_text.find("\n", seg_start)
                semi_pos = raw_text.find(";", seg_start)
                stops = [p for p in ([nl_pos, semi_pos] + next_starts) if p != -1 and p > seg_start]
                seg_end = min(stops) if stops else len(raw_text)
                segment = raw_text[seg_start:seg_end]

            if isinstance(fval, (int, float)) and not isinstance(fval, bool):
                pct_words = ("margin", "rate", "pct", "%", "share", "churn")
                f_unit = "percent" if any(w in fname.lower() for w in pct_words) else ""
                vc = value_check(
                    segment,
                    float(fval),
                    expected_unit=f_unit,
                    rel_tol=rec_tol,
                    abs_tol=rec_abs,
                    display_tol=rec_disp,
                    number_locale=number_locale,
                    percent_accepts_ratio=percent_accepts_ratio,
                )
                if vc["passed"] != 1:
                    return _check_dict(
                        0,
                        f"record field {fname} mismatch in {segment.strip()!r}",
                        match_kind="record_mismatch",
                        extracted=vc.get("extracted"),
                    )
            else:
                if normalize_name(str(fval)) not in normalize_name(segment):
                    return _check_dict(
                        0,
                        f"record field {fname} text mismatch in {segment.strip()!r}",
                        match_kind="record_mismatch",
                        extracted=None,
                    )
        return _check_dict(1, f"matched all {len(fields)} record fields", match_kind="record_match", extracted=None)

    if ct in ("abstention", "negative", "refusal"):
        forbidden = list(spec.get("forbidden") or spec.get("forbidden_items") or [])
        for f_str in forbidden:
            if str(f_str).lower() in raw_lower:
                return _check_dict(
                    0,
                    f"forbidden content present in abstention case: {f_str!r}",
                    match_kind="hallucinated_on_abstention",
                    extracted=None,
                )
        if not _ABSTAIN_RE.search(raw_text):
            return _check_dict(
                0,
                "expected abstention/refusal but answer stated an assertion",
                match_kind="hallucinated_on_abstention",
                extracted=None,
            )
        if not spec.get("allow_numbers", False):
            allowed_nums = {float(x) for x in (spec.get("allowed_numbers") or [])}
            nums = extract_numbers(raw_text, number_locale=number_locale)
            fabricated = [
                n
                for n in nums
                if (n["unit"] in ("currency", "percent", "pp", "bps") or n["has_scale_word"])
                and all(abs(n["value"] - a) > 1e-6 for a in allowed_nums)
            ]
            if fabricated:
                return _check_dict(
                    0,
                    f"answer hedged but fabricated metric value: {fabricated[0]['span']}",
                    match_kind="hallucinated_on_abstention",
                    extracted=fabricated[0]["value"],
                )
        return _check_dict(
            1, "abstention verified without fabricated metrics", match_kind="abstention_verified", extracted=None
        )

    if ct == "clarification":
        has_clarify = "?" in raw_text or bool(_CLARIFY_RE.search(raw_text))
        if has_clarify and not extract_numbers(raw_text, number_locale=number_locale):
            return _check_dict(1, "clarifying question verified", match_kind="clarification_verified", extracted=None)
        return _check_dict(
            0,
            "expected clarifying question without ungrounded metric",
            match_kind="clarification_failed",
            extracted=None,
        )

    if ct == "direction":
        exp_dir = str(spec.get("direction") or expected or "").strip().lower()
        if exp_dir not in ("up", "down", "flat"):
            return _check_dict(
                -1, f"invalid expected direction: {exp_dir!r}", match_kind="no_expectation", extracted=None
            )
        has_up = bool(_DIR_UP_RE.search(raw_text)) or bool(re.search(r"(?<!\w)\+\s*[$€£]?\d", raw_text))
        has_down = bool(_DIR_DOWN_RE.search(raw_text)) or bool(re.search(r"(?<!\w)-\s*[$€£]?\d", raw_text))
        has_flat = bool(_DIR_FLAT_RE.search(raw_text))

        dir_ok = (
            (exp_dir == "up" and has_up and not has_flat)
            or (exp_dir == "down" and has_down and not has_flat)
            or (exp_dir == "flat" and has_flat and not has_up and not has_down)
        )
        # Disambiguate when sentence has lead polarity + prior comparison
        if exp_dir == "up" and has_up and has_down:
            m_up = _DIR_UP_RE.search(raw_text)
            m_dn = _DIR_DOWN_RE.search(raw_text)
            dir_ok = bool(m_up and (not m_dn or m_up.start() < m_dn.start()))
        elif exp_dir == "down" and has_down and has_up:
            m_up = _DIR_UP_RE.search(raw_text)
            m_dn = _DIR_DOWN_RE.search(raw_text)
            dir_ok = bool(m_dn and (not m_up or m_dn.start() < m_up.start()))

        if not dir_ok:
            return _check_dict(
                0, f"expected direction {exp_dir!r} not observed", match_kind="direction_mismatch", extracted=None
            )

        mag = spec.get("value")
        if mag is not None:
            d_unit = str(spec.get("unit") or expected_unit)
            vc = value_check(
                raw_text,
                float(mag),
                expected_unit=d_unit,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                display_tol=display_tol,
                expected_currency=expected_currency,
                number_locale=number_locale,
                percent_accepts_ratio=percent_accepts_ratio,
            )
            if vc["passed"] != 1:
                return _check_dict(
                    0,
                    f"direction {exp_dir!r} matched but magnitude {vc.get('extracted')} != {mag}",
                    match_kind="direction_mismatch",
                    extracted=vc.get("extracted"),
                )
            return _check_dict(
                1,
                f"direction {exp_dir!r} and magnitude matched",
                match_kind="direction_match",
                extracted=vc.get("extracted"),
            )
        return _check_dict(1, f"direction {exp_dir!r} matched", match_kind="direction_match", extracted=None)

    if ct == "citation_only":
        if raw_text.strip() and not _ABSTAIN_RE.search(raw_text):
            return _check_dict(1, "non-empty grounded response", match_kind="citation_only", extracted=None)
        return _check_dict(
            0, "empty or refusal response on citation_only case", match_kind="empty_or_refusal", extracted=None
        )

    if ct == "categorical":
        target_val = str(spec.get("value") if spec.get("value") is not None else (expected or "")).strip()
        aliases = [str(a) for a in (spec.get("aliases") or [])]
        forbidden = [str(f) for f in (spec.get("forbidden") or [])]
        for f_cat in forbidden:
            if _find_item_pos(norm_text, raw_lower, f_cat) != -1:
                return _check_dict(
                    0, f"forbidden category present: {f_cat}", match_kind="categorical_mismatch", extracted=None
                )
        if not target_val and not aliases:
            return _check_dict(
                -1, "categorical expectation has no target value", match_kind="no_expectation", extracted=None
            )
        if _find_item_pos(norm_text, raw_lower, {"name": target_val, "aliases": aliases}) != -1:
            return _check_dict(
                1, f"categorical value {target_val!r} matched", match_kind="categorical_match", extracted=target_val
            )
        return _check_dict(
            0, f"categorical value {target_val!r} not found", match_kind="categorical_mismatch", extracted=None
        )

    if ct in ("text", "facts"):
        facts = [str(f) for f in (spec.get("facts") or spec.get("items") or ([expected] if expected else []))]
        if not facts:
            return _check_dict(
                -1, "facts expectation has no required facts", match_kind="no_expectation", extracted=None
            )
        missing_facts = [f for f in facts if _find_item_pos(norm_text, raw_lower, f) == -1]
        if missing_facts:
            return _check_dict(
                0,
                f"missing required facts: {', '.join(missing_facts)}",
                match_kind="facts_mismatch",
                extracted=None,
            )
        return _check_dict(1, "all required facts matched", match_kind="facts_match", extracted=None)

    return _check_dict(-1, f"unsupported case_type: {case_type!r}", match_kind="unsupported_case_type", extracted=None)


def value_check(
    text: str,
    expected: float | str | None = None,
    expected_unit: str = "",
    rel_tol: float = 0.005,
    abs_tol: float | None = None,
    *,
    display_tol: float = 0.01,
    case_type: str = "scalar",
    expect: dict[str, Any] | None = None,
    extracted_override: dict[str, Any] | None = None,
    expected_currency: str = "",
    number_locale: str = "auto",
    percent_accepts_ratio: bool = True,
) -> dict[str, Any]:
    """Evaluate answer value or structured expectation with scale-aware rounding tolerance."""
    ct = (case_type or "scalar").strip().lower()
    if expect and not expected_currency and expect.get("currency"):
        expected_currency = str(expect["currency"])
    if expect and not expected_unit and expect.get("unit"):
        expected_unit = str(expect["unit"])

    if ct not in ("scalar", "numeric", "number"):
        return _score_rich_expectation(
            text=text,
            case_type=ct,
            expected=expected,
            expect=expect,
            expected_unit=expected_unit,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
            display_tol=display_tol,
            expected_currency=expected_currency,
            number_locale=number_locale,
            percent_accepts_ratio=percent_accepts_ratio,
        )

    raw_expected = expected if expected is not None else (expect or {}).get("value")
    if raw_expected is None or raw_expected == "" or isinstance(raw_expected, bool):
        return _check_dict(
            -1,
            "no expected value configured",
            match_kind="no_expectation",
            extracted=None,
            unit="",
            currency="",
            expected=None,
            rel_error=None,
            validated_span="",
        )
    try:
        exp_val = float(raw_expected)
    except (TypeError, ValueError):
        return _check_dict(
            -1,
            f"non-numeric expected value: {raw_expected!r}",
            match_kind="no_expectation",
            extracted=None,
            unit="",
            currency="",
            expected=None,
            rel_error=None,
            validated_span="",
        )

    if rel_tol < 0 or (abs_tol is not None and abs_tol < 0) or display_tol < 0:
        return _check_dict(
            -1,
            "value tolerances must be finite and non-negative",
            match_kind="invalid_tolerance",
            extracted=None,
            unit="",
            currency="",
            expected=exp_val,
            rel_error=None,
            validated_span="",
        )

    ext = (
        extracted_override
        if extracted_override is not None
        else extract_answer_value(
            text,
            expected_unit=expected_unit,
            expected_currency=expected_currency,
            number_locale=number_locale,
        )
    )
    status = ext.get("status", "none")
    cand_count = len(ext.get("candidates") or [])

    if status == "range":
        return _check_dict(
            0,
            f"interval range rejected ({ext.get('span') or 'range'})",
            match_kind="range_rejected",
            extracted=None,
            raw=ext.get("span", ""),
            unit=ext.get("unit", ""),
            currency=ext.get("currency", ""),
            expected=exp_val,
            rel_error=None,
            validated_span=ext.get("span", ""),
            candidates=cand_count,
        )
    if status == "ambiguous":
        return _check_dict(
            -1,
            "multiple unranked candidate values in answer",
            match_kind="ambiguous",
            extracted=None,
            raw="",
            unit=ext.get("unit", ""),
            currency=ext.get("currency", ""),
            expected=exp_val,
            rel_error=None,
            validated_span="",
            candidates=cand_count,
        )
    if status != "ok" or ext.get("value") is None:
        return _check_dict(
            0,
            f"no {expected_unit or 'numeric'} value found in the answer",
            match_kind="no_number",
            extracted=None,
            raw="",
            unit="",
            currency="",
            expected=exp_val,
            rel_error=None,
            validated_span="",
            candidates=0,
        )

    got = float(ext["value"])
    got_unit = str(ext.get("unit") or "")
    got_cur = str(ext.get("currency") or "")
    span_str = str(ext.get("span") or "")
    scale_val = float(ext.get("scale", 1.0))
    sig_figs = int(ext.get("sig_figs", 0))
    decimals = int(ext.get("decimals", 0))
    has_scale_word = bool(ext.get("has_scale_word", scale_val != 1.0))
    ulp = float(ext.get("ulp", (10.0 ** (-decimals)) * scale_val))

    norm_exp_unit, _ = _canonical_unit(expected_unit)
    if percent_accepts_ratio:
        if norm_exp_unit == "percent" and got_unit == "" and 0.0 < abs(got) <= 1.0 < abs(exp_val) <= 100.0:
            got *= 100.0
            ulp *= 100.0
        elif got_unit == "percent" and 0.0 < abs(exp_val) <= 1.0 < abs(got) <= 100.0:
            got /= 100.0
            ulp /= 100.0

    err = abs(got - exp_val)
    rel_error = (err / abs(exp_val)) if exp_val != 0.0 else (0.0 if err == 0.0 else float("inf"))
    error_pct = (rel_error * 100.0) if (exp_val != 0.0 and math.isfinite(rel_error)) else None

    exact_bound = (
        (abs_tol if abs_tol is not None else 1e-6)
        if exp_val == 0.0
        else max(
            abs_tol if abs_tol is not None else 0.0,
            abs(exp_val) * rel_tol,
        )
    )

    is_coarse_pct = (
        (got_unit == "percent" or norm_exp_unit == "percent")
        and decimals <= 1
        and (sig_figs <= 3 or (decimals == 1 and abs(got) >= 100.0 and sig_figs == 4))
    )
    is_display_candidate = has_scale_word or is_coarse_pct
    half_ulp = 0.5 * ulp
    display_bound = min(half_ulp, abs(exp_val) * display_tol) if exp_val != 0.0 else half_ulp

    common_details: dict[str, Any] = {
        "extracted": got,
        "raw": span_str,
        "unit": got_unit,
        "currency": got_cur,
        "expected": exp_val,
        "difference": err,
        "allowed": max(exact_bound, display_bound if is_display_candidate else 0.0),
        "rel_error": rel_error,
        "error_pct": error_pct,
        "validated_span": span_str,
        "candidates": cand_count,
    }

    eps = max(1e-12, abs(exp_val) * 1e-12)
    if err <= eps:
        return _check_dict(
            1,
            f"value {span_str} matches expected {show(exp_val)}",
            match_kind="exact_match",
            **common_details,
        )

    if is_display_candidate and display_tol > 0.0 and ulp >= abs(exp_val) * 1e-4 - 1e-12 and err <= display_bound + eps:
        return _check_dict(
            1,
            f"value {span_str} matches expected {show(exp_val)} within display rounding",
            match_kind="display_rounded",
            **common_details,
        )

    if err <= exact_bound + eps:
        return _check_dict(
            1,
            f"value {span_str} matches expected {show(exp_val)} within tolerance",
            match_kind="exact_match",
            **common_details,
        )

    return _check_dict(
        0,
        f"value {span_str} differs from expected {show(exp_val)}",
        match_kind="mismatch",
        **common_details,
    )


def score_value(
    answer: str,
    expected: Any,
    unit: str = "number",
    rel_tol: float = 0.005,
    abs_tol: float = 0.0,
    display_aware: bool = True,
    max_display_rel: float = 0.01,
    *,
    display_tol: float | None = None,
    case_type: str = "scalar",
    expect: dict[str, Any] | None = None,
    expected_currency: str = "",
    number_locale: str = "auto",
    percent_accepts_ratio: bool = True,
) -> dict[str, Any]:
    """Backwards-compatible v1/v2 value scorer."""
    eff_display_tol = 0.0 if not display_aware else (display_tol if display_tol is not None else max_display_rel)
    return value_check(
        text=answer,
        expected=expected,
        expected_unit=unit,
        rel_tol=rel_tol,
        abs_tol=abs_tol,
        display_tol=eff_display_tol,
        case_type=case_type,
        expect=expect,
        expected_currency=expected_currency,
        number_locale=number_locale,
        percent_accepts_ratio=percent_accepts_ratio,
    )


def normalize_name(name: str | None) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (name or "").lower()).split())


def split_list(value: Any) -> list[str]:
    """Accept a list/tuple or a ';' / '|' separated string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items: Sequence[Any] = list(value)
    else:
        items = re.split(r"[;|]", str(value))
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            val = str(item.get("name") or item.get("id") or "").strip()
        else:
            val = str(item).strip()
        if val:
            out.append(val)
    return out


def name_matches(candidate: str | None, target: str | None) -> bool:
    c, t = normalize_name(candidate), normalize_name(target)
    if not c or not t:
        return False
    return c == t or (" " + t + " ") in (" " + c + " ")


def _artifact_hit(artifact: Mapping[str, Any], targets: Sequence[str]) -> bool:
    name = str(artifact.get("name") or artifact.get("title") or "")
    ids = [
        str(artifact.get(k) or "").strip().lower()
        for k in ("id", "item_id", "artifactId", "resourceId")
        if artifact.get(k)
    ]
    url = str(artifact.get("url") or artifact.get("webUrl") or "").strip().lower()
    for t in targets:
        tl = t.strip().lower()
        if not tl:
            continue
        if tl in ids or (url and len(tl) >= 8 and tl in url):
            return True
        if name_matches(name, t):
            return True
    return False


def citation_artifacts(artifacts: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Answer links and model citations, not grounding-only discovery metadata."""
    out: list[dict[str, Any]] = []
    for a in artifacts or []:
        if (
            a.get("answer_cited")
            or a.get("source") == "answer_link"
            or (
                str(a.get("attribution_source") or "").lower() in ("", "model")
                and str(a.get("attribution_type") or "").lower() in ("", "citation")
            )
        ):
            out.append(dict(a))
    return out


def artifact_check(
    attributions: Sequence[Mapping[str, Any]] | None,
    artifacts: Sequence[Mapping[str, Any]] | None,
    expected_name: str = "",
    expected_id: str = "",
    *,
    aliases: Any = None,
    decoys: Any = None,
    expected_kind: str | Sequence[str] | None = None,
) -> dict[str, Any]:
    """Check cited artifacts and attributions by stable artifact ID first, then name."""
    cited_arts = citation_artifacts(artifacts)
    att_list = [dict(a) for a in (attributions or [])]

    all_records: list[dict[str, Any]] = list(cited_arts)
    for att in att_list:
        raw_rv = att.get("resourceVisualization")
        rv: dict[str, Any] = dict(raw_rv) if isinstance(raw_rv, Mapping) else {}
        all_records.append(
            {
                "name": att.get("name") or att.get("title") or rv.get("title") or att.get("providerDisplayName") or "",
                "id": att.get("id") or att.get("artifactId") or att.get("resourceId") or "",
                "artifactId": att.get("artifactId") or "",
                "resourceId": att.get("resourceId") or "",
                "url": att.get("url") or att.get("webUrl") or att.get("seeMoreWebUrl") or "",
                "kind": att.get("kind") or rv.get("type") or "",
            }
        )

    decoy_list = split_list(decoys)
    decoy_hits = sorted(
        {str(r.get("name") or r.get("url") or "?") for r in all_records if _artifact_hit(r, decoy_list)}
    )
    cited_names = sorted(
        {str(r.get("name") or r.get("url") or "?") for r in all_records if r.get("name") or r.get("url")}
    )
    if decoy_hits:
        return _check_dict(
            0,
            "decoy cited: " + ", ".join(decoy_hits),
            decoy_hit=True,
            cited=cited_names,
            matched_by="decoy",
        )

    exp_id_clean = (expected_id or "").strip().lower()
    name_targets = split_list(expected_name) + split_list(aliases)
    if not exp_id_clean and not name_targets:
        return _check_dict(
            -1,
            "no expected artifact configured",
            decoy_hit=False,
            cited=cited_names,
            matched_by="none",
        )

    allowed_kinds: set[str] | None = None
    if expected_kind is not None:
        allowed_kinds = (
            {expected_kind.lower()} if isinstance(expected_kind, str) else {str(k).lower() for k in expected_kind}
        )

    def kind_ok(rec: Mapping[str, Any]) -> bool:
        if allowed_kinds is None:
            return True
        rk = str(rec.get("kind") or "").lower()
        return not rk or rk in allowed_kinds

    if exp_id_clean:
        for rec in all_records:
            if not kind_ok(rec):
                continue
            cand_ids = [
                str(rec.get(k) or "").strip().lower()
                for k in ("id", "item_id", "artifactId", "resourceId")
                if rec.get(k)
            ]
            cand_url = str(rec.get("url") or "").strip().lower()
            if exp_id_clean in cand_ids or (cand_url and exp_id_clean in cand_url):
                return _check_dict(
                    1,
                    f"expected artifact ID {expected_id} cited",
                    decoy_hit=False,
                    cited=cited_names,
                    matched_by="id",
                )

    if name_targets:
        for rec in all_records:
            if not kind_ok(rec):
                continue
            rec_name = str(rec.get("name") or "").strip()
            rec_url = str(rec.get("url") or "").strip().lower()
            for target in name_targets:
                tl = target.strip().lower()
                if tl and (tl in rec_name.lower() or name_matches(rec_name, target) or (rec_url and tl in rec_url)):
                    return _check_dict(
                        1,
                        "expected artifact cited",
                        decoy_hit=False,
                        cited=cited_names,
                        matched_by="name",
                    )

    return _check_dict(
        0,
        "expected artifact not cited",
        decoy_hit=False,
        cited=cited_names,
        matched_by="none",
    )


def score_artifact(
    artifacts: Sequence[Mapping[str, Any]] | None,
    expected: Any,
    aliases: Any = None,
    decoys: Any = None,
    expected_id: str = "",
    expected_kind: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Did Copilot cite the expected report or semantic model, and no decoy?"""
    cited_arts = citation_artifacts(artifacts)
    targets = split_list(expected) + split_list(aliases)
    if expected_id.strip():
        targets = [expected_id.strip()] + targets
    decoy_list = split_list(decoys)
    decoy_hits = sorted({str(a.get("name") or a.get("url") or "?") for a in cited_arts if _artifact_hit(a, decoy_list)})
    if expected_kind is not None:
        valid_kinds = {str(k).lower() for k in expected_kind}
        matching_kind = [a for a in cited_arts if str(a.get("kind") or "").lower() in valid_kinds]
    else:
        pbi_aliases = set(POWERBI_KINDS) | {"report", "dataset", "semanticmodel", "dashboard", "app", "dataagent"}
        matching_kind = [a for a in cited_arts if not a.get("kind") or str(a.get("kind")).lower() in pbi_aliases]
    cited = sorted({str(a.get("name") or a.get("url") or "?") for a in cited_arts})
    details = {"decoy_hit": bool(decoy_hits), "cited": cited, "powerbi_cited": len(matching_kind)}
    if decoy_hits:
        return _result(FAIL, "decoy cited: " + ", ".join(decoy_hits), **details)
    if not targets:
        return _result(INCONCLUSIVE, "no expected artifact configured", **details)
    if any(_artifact_hit(a, targets) for a in matching_kind):
        return _result(PASS, "expected artifact cited", **details)
    lookalikes = sorted(
        {str(a.get("name") or "?") for a in cited_arts if a not in matching_kind and _artifact_hit(a, targets)}
    )
    if not matching_kind:
        note = f" (cited a non-Power BI item with a matching name: {', '.join(lookalikes)})" if lookalikes else ""
        return _result(FAIL, "no Power BI report or semantic model cited" + note, **details)
    other = ", ".join(sorted({str(a.get("name") or "?") for a in matching_kind}))
    return _result(FAIL, f"cited other Power BI content: {other}", **details)


def _extract_queried_models(trace_info: Mapping[str, Any]) -> list[str]:
    models: list[str] = []
    for m in trace_info.get("models") or []:
        if m and str(m).strip():
            models.append(str(m).strip())
    for q in trace_info.get("queries") or []:
        if isinstance(q, Mapping):
            for key in ("model", "semantic_model", "item_name", "ItemName", "dataset", "item_id", "ItemId", "model_id"):
                val = q.get(key)
                if val and str(val).strip():
                    models.append(str(val).strip())
            args = q.get("arguments")
            if isinstance(args, Mapping):
                for key in ("model", "semantic_model", "dataset", "item_id", "model_id", "artifact_name"):
                    val = args.get(key)
                    if val and str(val).strip():
                        models.append(str(val).strip())
        else:
            for attr in ("item_name", "model", "item_id"):
                val = getattr(q, attr, None)
                if val and str(val).strip():
                    models.append(str(val).strip())
    return sorted(set(models))


def model_check(
    trace_info: Mapping[str, Any] | Any | None,
    expected_model: str = "",
    *,
    decoys: Any = None,
) -> dict[str, Any]:
    """Verify semantic-model routing from engine DAX telemetry or MCP/agent tool calls."""
    if trace_info is None:
        info: dict[str, Any] = {}
    elif isinstance(trace_info, Mapping):
        info = dict(trace_info)
    else:
        info = {
            "status": getattr(trace_info, "status", ""),
            "queries": getattr(trace_info, "queries", []),
            "correlation_confidence": getattr(trace_info, "correlation_confidence", "none"),
            "routing_evidence": getattr(trace_info, "routing_evidence", ""),
        }

    status = str(info.get("status") or "disabled").lower()
    routing_evidence = str(info.get("routing_evidence") or "")
    if not routing_evidence and status in ("observed", "complete", "ok"):
        routing_evidence = "engine+citations"
    correlation_confidence = str(
        info.get("correlation_confidence") or ("high" if routing_evidence == "tool_call" else "none")
    )
    models = _extract_queried_models(info)

    common = {
        "queried": models,
        "trace_status": status,
        "routing_evidence": routing_evidence,
        "correlation_confidence": correlation_confidence,
        "decoy_hit": False,
    }

    decoy_list = split_list(decoys)
    decoy_hits = [m for m in models if any(d.lower() == m.lower() or name_matches(m, d) for d in decoy_list)]
    if decoy_hits:
        common["decoy_hit"] = True
        return _check_dict(0, "decoy semantic model queried: " + ", ".join(decoy_hits), **common)

    targets = split_list(expected_model)
    if not targets:
        return _check_dict(-1, "no expected semantic model configured", **common)

    has_tool_evidence = routing_evidence == "tool_call" and (status not in ("missing", "incomplete", "error"))
    has_engine_evidence = status in ("observed", "complete", "ok")

    if has_engine_evidence or has_tool_evidence:
        if not models:
            return _check_dict(0, "no semantic model queries recorded in observed evidence", **common)
        matched = any(
            t.lower() == m.lower() or t.lower() in m.lower() or name_matches(m, t) for m in models for t in targets
        )
        if matched:
            return _check_dict(1, "expected semantic model observed in captured queries", **common)
        return _check_dict(0, "queried other semantic models: " + ", ".join(models), **common)

    if status == "none":
        return _check_dict(0, "trace observed zero semantic model queries during ask window", **common)

    return _check_dict(-1, f"engine trace capture is unavailable or unsettled ({status})", **common)


def score_model(
    trace_status: str | None,
    queried_models: Sequence[str] | None,
    expected_model: Any,
    decoys: Any = None,
    *,
    routing_evidence: str = "",
    correlation_confidence: str = "none",
) -> dict[str, Any] | None:
    """Backwards-compatible v1 wrapper for semantic-model query verification."""
    status = (trace_status or "disabled").lower()
    models = sorted(set(queried_models or []))
    decoy_hits = [m for m in models if any(name_matches(m, d) for d in split_list(decoys))]
    if decoy_hits:
        return _result(
            FAIL,
            "decoy semantic model queried: " + ", ".join(decoy_hits),
            decoy_hit=True,
            queried=models,
            trace_status=status,
            routing_evidence=routing_evidence,
            correlation_confidence=correlation_confidence,
        )
    if status == "disabled" and routing_evidence != "tool_call":
        return None
    if status not in ("complete", "observed", "ok") and routing_evidence != "tool_call":
        return _result(
            INCONCLUSIVE,
            f"DAX capture is missing or not settled ({status})",
            queried=models,
            trace_status=status,
            routing_evidence=routing_evidence,
            correlation_confidence=correlation_confidence,
        )
    if not models:
        return _result(
            INCONCLUSIVE,
            f"DAX capture is missing or not settled ({status})",
            queried=models,
            trace_status=status,
            routing_evidence=routing_evidence,
            correlation_confidence=correlation_confidence,
        )
    targets = split_list(expected_model)
    if not targets:
        return _result(
            INCONCLUSIVE,
            "no expected semantic model configured",
            queried=models,
            trace_status=status,
            routing_evidence=routing_evidence,
            correlation_confidence=correlation_confidence,
        )
    if any(name_matches(m, t) for m in models for t in targets):
        return _result(
            PASS,
            "expected semantic model observed in the captured queries",
            queried=models,
            trace_status=status,
            routing_evidence=routing_evidence,
            correlation_confidence=correlation_confidence,
        )
    return _result(
        FAIL,
        "queried other semantic models: " + ", ".join(models),
        queried=models,
        trace_status=status,
        routing_evidence=routing_evidence,
        correlation_confidence=correlation_confidence,
    )


def why_check(
    why_text: str | Mapping[str, Any] = "",
    why_json: Mapping[str, Any] | None = None,
    *,
    expected_artifact: str = "",
    expected_model: str = "",
    answer_value: float | None = None,
    rel_tol: float = 0.01,
) -> dict[str, Any]:
    """Deterministic consistency check on Copilot's structured or free-text follow-up explanation."""
    if isinstance(why_text, Mapping) and why_json is None:
        why_json = why_text
        why_str = str(why_json.get("explanation") or why_json.get("why") or "")
    else:
        why_str = str(why_text or "")

    wj = dict(why_json or {})
    if not why_str.strip() and not wj:
        return _check_dict(-1, "no follow-up explanation captured")

    combined_sources: list[str] = []
    for k in ("sources", "artifacts", "models", "semantic_model", "report", "artifact"):
        val = wj.get(k)
        if isinstance(val, (list, tuple)):
            combined_sources.extend(str(x) for x in val if x)
        elif val:
            combined_sources.append(str(val))
    haystack = " ".join([why_str] + combined_sources)

    targets = split_list(expected_artifact) + split_list(expected_model)
    if targets:
        matched = any(t.lower() in haystack.lower() or name_matches(haystack, t) for t in targets)
        if not matched and combined_sources:
            return _check_dict(0, f"explanation named {combined_sources} rather than expected {targets[0]}")
        if not matched and why_str.strip() and not wj:
            return _check_dict(0, f"explanation did not reference expected source {targets[0]}")

    if answer_value is not None and wj.get("answer") is not None:
        ans_raw = wj["answer"]
        ans_str = str(ans_raw.get("value") if isinstance(ans_raw, Mapping) else ans_raw)
        vc = value_check(ans_str, answer_value, rel_tol=rel_tol, display_tol=max(rel_tol, 0.01))
        if vc["passed"] == 0:
            return _check_dict(0, f"follow-up value {ans_str!r} inconsistent with answer value {show(answer_value)}")

    return _check_dict(1, "follow-up explanation is consistent")


def _default_gates_path() -> Path:
    repo_candidate = Path(__file__).resolve().parents[2] / "config" / "gates.yaml"
    if repo_candidate.exists():
        return repo_candidate
    return Path(__file__).resolve().parent / "resources" / "gates.yaml"


def load_gate_policy(
    profile: str = "auto",
    *,
    config_path: str | Path | None = None,
    trace_enabled: bool = False,
    surface: str = "copilot-chat",
    case_gates: Sequence[str] | str | None = None,
    judge_gates_verdict: bool = False,
) -> dict[str, Any]:
    """Load gate policy from config/gates.yaml, resolve 'auto', and compute gate_policy_hash."""
    raw_cfg: dict[str, Any] = _DEFAULT_GATE_CONFIG
    path = Path(config_path) if config_path is not None else _default_gates_path()
    if path.exists():
        try:
            import yaml

            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw_cfg = loaded
        except ImportError:
            pass

    profiles = dict(raw_cfg.get("profiles") or _DEFAULT_GATE_CONFIG["profiles"])
    parsed_case_gates: list[str] = []
    if case_gates is not None:
        if isinstance(case_gates, str):
            parsed_case_gates = [g.strip() for g in re.split(r"[,;|]", case_gates) if g.strip()]
        else:
            parsed_case_gates = [str(g).strip() for g in case_gates if str(g).strip()]

    surf_norm = (surface or "").strip().lower()
    req_profile = (profile or "auto").strip()

    if parsed_case_gates:
        resolved_profile = "case_override" if req_profile == "auto" else req_profile
        gates = list(parsed_case_gates)
        incomplete_on_missing_trace = ("model" in gates) and bool(trace_enabled)
        routing_evidence = (
            "engine+citations"
            if ("model" in gates and "artifact" in gates)
            else ("tool_call" if "model" in gates else "citations-only")
        )
    else:
        if req_profile == "auto":
            if surf_norm in ("work-iq", "work_iq"):
                resolved_profile = "work_iq"
            elif surf_norm in ("mcp", "fabric-iq-mcp-reference", "tool_call"):
                resolved_profile = "tool_call_evidence"
            elif trace_enabled:
                resolved_profile = "with_engine_evidence"
            else:
                resolved_profile = "without_engine_evidence"
        else:
            if req_profile not in profiles:
                raise ValueError(f"Unknown gate profile: {req_profile!r}")
            resolved_profile = req_profile

        prof_cfg = dict(profiles[resolved_profile])
        gates = [str(g) for g in (prof_cfg.get("gates") or ["value", "artifact"])]
        incomplete_on_missing_trace = bool(prof_cfg.get("incomplete_on_missing_trace", False))
        routing_evidence = str(prof_cfg.get("routing_evidence") or "citations-only")

    if judge_gates_verdict and "judge_answer" not in gates:
        gates.append("judge_answer")

    canonical = json.dumps(
        {
            "profile": resolved_profile,
            "gates": gates,
            "incomplete_on_missing_trace": incomplete_on_missing_trace,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    gate_policy_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    return {
        "profile": resolved_profile,
        "gates": tuple(gates),
        "incomplete_on_missing_trace": incomplete_on_missing_trace,
        "routing_evidence": routing_evidence,
        "thresholds": dict(raw_cfg.get("thresholds") or {}),
        "gate_policy_hash": gate_policy_hash,
    }


def _extract_gate_state(entry: Any) -> int:
    """Normalize a check dict, int (1/0/-1), or v1 float score (1.0/0.0/0.5) into {1, 0, -1}."""
    if entry is None:
        return -1
    if isinstance(entry, Mapping):
        if "passed" in entry and entry["passed"] is not None:
            p = int(entry["passed"])
            return 1 if p == 1 else 0 if p == 0 else -1
        sc = entry.get("score")
        if sc is None:
            return -1
        return 1 if sc == PASS else 0 if sc == FAIL else -1
    if isinstance(entry, bool):
        return 1 if entry else 0
    if isinstance(entry, int):
        return 1 if entry == 1 else 0 if entry == 0 else -1
    if isinstance(entry, float):
        if entry == PASS:
            return 1
        if entry == FAIL:
            return 0
        return -1
    return -1


def verdict(
    checks: Mapping[str, Any],
    *,
    ask_ok: bool = True,
    trace_status: str = "observed",
    gates: Sequence[str] = ("value", "artifact", "model"),
    incomplete_on_missing_trace: bool = True,
    required: Sequence[str] | None = None,
) -> str:
    """Combine gated check outcomes into PASS, FAIL, INCONCLUSIVE, or ERROR."""
    if not ask_ok:
        return "ERROR"
    ts = (trace_status or "").strip().lower()
    if incomplete_on_missing_trace and ts in ("missing", "incomplete", "error"):
        return "INCONCLUSIVE"

    active_gates = tuple(required) if required is not None else tuple(gates)
    if not active_gates:
        return "INCONCLUSIVE"

    states = [_extract_gate_state(checks.get(g)) for g in active_gates]
    if any(s == 0 for s in states):
        return "FAIL"
    if any(s != 1 for s in states):
        return "INCONCLUSIVE"
    return "PASS"
