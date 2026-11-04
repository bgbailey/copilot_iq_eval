"""no_decoy: no decoy model was queried and no unofficial document was used (PLAN §9.6.2).

This is the governance check customers care about most. The attempt fails if any of these is true:

1. a decoy semantic model (for example the stale Sales Sandbox) appears in the engine-log or
   tool-trace evidence;
2. a document decoy (for example "FY2025 revenue - DRAFT.docx") is cited or attributed;
3. an ``answer`` case states a figure with no Fabric query behind it, citing only other sources:
   "answered from a non-Fabric source".

Code-based evaluator listed in evals/evaluators/evaluators.yaml, run unchanged by Microsoft Foundry
Evaluations or by the local backend. Score: 1.0 pass, 0.0 fail. A clean result needs complete
engine-log evidence; until then grade() raises InconclusiveError, which the backend records as an
error and the gate counts as INCONCLUSIVE.

Self-contained by design: standard library only, no imports from copilot_evals, under 256 KB.
"""

import re
from typing import Any
from urllib.parse import unquote

SCORE_PASS = 1.0
SCORE_FAIL = 0.0

#: Citation kinds that point at Fabric or Power BI content (set by the runner, PLAN §9.1).
FABRIC_CITATION_KINDS = frozenset({"powerbi", "fabric"})

# Figures that are labels, not values: fiscal years and quarters, ISO dates and plain years.
_NOT_A_FIGURE = re.compile(
    r"\bFY\s?\d{2,4}(?:\s?Q[1-4])?\b|\bQ[1-4]\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_DIGIT = re.compile(r"\d")


class InconclusiveError(Exception):
    """The row does not hold enough evidence to decide this check."""


def grade(sample: dict[str, Any], item: dict[str, Any]) -> float:
    """Fail on any decoy hit; pass only when the engine-log evidence is complete and clean."""
    _require_usable_attempt(item)

    observed = set(_strings(item.get("observed_models")))
    decoys = set(_strings(item.get("decoy_models")))
    if observed & decoys:
        return SCORE_FAIL  # a decoy model was queried; later logs cannot undo that

    if _cites_document_decoy(item):
        return SCORE_FAIL

    complete = item.get("evidence_complete") is True
    if complete and _answered_from_non_fabric_source(item, observed):
        return SCORE_FAIL

    if not complete:
        raise InconclusiveError("engine-log evidence incomplete: a decoy query may not be visible yet")
    return SCORE_PASS


def _cites_document_decoy(item: dict[str, Any]) -> bool:
    """True when a citation's title or URL (decoded or not) contains a document-decoy pattern."""
    patterns = [pattern.lower() for pattern in _strings(item.get("doc_decoy_patterns"))]
    if not patterns:
        return False
    for citation in _citations(item):
        title = str(citation.get("title") or "")
        url = str(citation.get("url") or "")
        text = f"{title}\n{url}\n{unquote(url)}".lower()
        if any(pattern in text for pattern in patterns):
            return True
    return False


def _answered_from_non_fabric_source(item: dict[str, Any], observed: set[str]) -> bool:
    """True when an answer states a figure, no Fabric query was observed and every citation is non-Fabric.

    Only called once the evidence is complete. Without any citation, a missing Fabric query is
    scored by routing_match instead.
    """
    if item.get("expected_behavior") != "answer" or observed:
        return False
    citations = _citations(item)
    if not citations:
        return False
    if any(str(citation.get("kind") or "").lower() in FABRIC_CITATION_KINDS for citation in citations):
        return False
    return _contains_figure(str(item.get("response") or ""))


def _contains_figure(text: str) -> bool:
    """True when the text holds a digit outside fiscal labels, dates and plain years."""
    return bool(_DIGIT.search(_NOT_A_FIGURE.sub(" ", text)))


def _citations(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Citations as dicts, ignoring malformed entries."""
    value = item.get("citations")
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _require_usable_attempt(item: dict[str, Any]) -> None:
    """Raise InconclusiveError when the surface call itself failed (timeout, throttling, error)."""
    status = item.get("status")
    if status != "ok":
        raise InconclusiveError(f"surface status {status!r}: there is no answer to evaluate")


def _strings(value: Any) -> list[str]:
    """Return a list of non-empty strings from a JSON array, ignoring anything else."""
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry]
