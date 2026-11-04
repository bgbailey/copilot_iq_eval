"""citation_match: the answer names its certified source when the case requires it (PLAN §9.6.3).

When ``citation_required`` is true, the attempt passes if the answer names an expected source, the
semantic model or report display name, or its URL, in a citation, an attribution or the answer text
itself. The runner fills ``expected_sources`` from evals/golden/models.yaml and the URLs it resolved
at run time; model owners are attached later in the scorecard, so every answer shows its source and
its owner.

Code-based evaluator listed in evals/evaluators/evaluators.yaml, run unchanged by Microsoft Foundry
Evaluations or by the local backend. Score: 1.0 pass, 0.0 fail; raises InconclusiveError when the row
cannot be scored (the backend records an error, the gate counts INCONCLUSIVE).

Self-contained by design: standard library only, no imports from copilot_evals, under 256 KB.
"""

from typing import Any
from urllib.parse import unquote

SCORE_PASS = 1.0
SCORE_FAIL = 0.0


class InconclusiveError(Exception):
    """The row does not hold enough information to decide this check."""


def grade(sample: dict[str, Any], item: dict[str, Any]) -> float:
    """Pass when no citation is required, or when an expected source is named (case-insensitive)."""
    _require_usable_attempt(item)
    if item.get("citation_required") is not True:
        return SCORE_PASS

    names = [name.strip().lower() for name in _strings(item.get("expected_sources")) if name.strip()]
    if not names:
        raise InconclusiveError("citation required but the row lists no expected sources")

    texts = [str(item.get("response") or "")]
    for citation in _citations(item):
        url = str(citation.get("url") or "")
        texts += [str(citation.get("title") or ""), url, unquote(url)]
    haystack = "\n".join(texts).lower()
    return SCORE_PASS if any(name in haystack for name in names) else SCORE_FAIL


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
