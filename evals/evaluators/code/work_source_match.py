"""work_source_match: the answer cites every seeded work document it relies on (PLAN §9.6.3, §4.4).

Joint Work IQ + Fabric IQ cases ask questions that need both a seeded SharePoint document (for
example the approved FY2025 revenue targets) and a certified semantic model (the actual figure).
This check proves the document side: every expected work source must be cited, attributed or named
in the answer. Each source carries the fragments that identify it (`work_sources[].match`), compared
case-insensitively with citation titles and URLs (also URL-decoded) and with the answer text.
`no_decoy` separately fails an answer that uses a draft; `routing_match` proves the model side.

Code-based evaluator listed in evals/evaluators/evaluators.yaml, run unchanged by Microsoft Foundry
Evaluations or by the local backend. Score: 1.0 pass, 0.0 fail; raises InconclusiveError when the
row cannot be scored (the backend records an error, the gate counts INCONCLUSIVE).

Self-contained by design: standard library only, no imports from copilot_evals, under 256 KB.
"""

from typing import Any
from urllib.parse import unquote

SCORE_PASS = 1.0
SCORE_FAIL = 0.0


class InconclusiveError(Exception):
    """The row does not hold enough information to decide this check."""


def grade(sample: dict[str, Any], item: dict[str, Any]) -> float:
    """Pass when the row needs no work source, or when every expected work source is cited or named."""
    _require_usable_attempt(item)
    sources = _work_sources(item)
    if item.get("expected_behavior") != "answer" or not sources:
        return SCORE_PASS  # nothing to cite; no_decoy still checks that no draft was used

    texts = [str(item.get("response") or "")]
    for citation in _citations(item):
        url = str(citation.get("url") or "")
        texts += [str(citation.get("title") or ""), url, unquote(url)]
    haystack = "\n".join(texts).lower()

    for key, fragments in sources:
        if not fragments:
            raise InconclusiveError(f"work source {key!r} has no match fragments: fix models.yaml")
        if not any(fragment in haystack for fragment in fragments):
            return SCORE_FAIL
    return SCORE_PASS


def _work_sources(item: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """(key, lower-cased match fragments) for every well-formed entry of ``work_sources``."""
    value = item.get("work_sources")
    if not isinstance(value, list):
        return []
    sources = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        fragments = entry.get("match") if isinstance(entry.get("match"), list) else []
        sources.append((str(entry.get("key")), [str(f).strip().lower() for f in fragments if str(f).strip()]))
    return sources


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
