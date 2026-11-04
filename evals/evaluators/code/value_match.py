"""value_match: the answer states the live expected value within tolerance (PLAN §9.6.1).

STATUS: skeleton. Backlog task P2.5 implements the numeric parsing and tolerance rules below. Until
then grade() raises NotImplementedError for ``answer`` rows, which either backend records as an
error and the gate counts as INCONCLUSIVE, so this evaluator can never produce a false pass.

How the check works once implemented:

1. Parse every number in ``item["response"]`` with ``parse_numbers`` (Decimal values; currency,
   scale words, percentages and negatives; fiscal labels, dates and years ignored).
2. Keep the candidates whose unit fits ``item["expected_unit"]`` (``select_candidate``). The
   expected value is never used to choose.
3. If more than one candidate remains, read the expected-blind extraction that the backend
   generated for this row (``item["sample"]["output_text"]``, from prompts/value_extraction.md),
   and accept it only if it matches one of the parsed candidates.
4. Compare with ``item["expected_value"]`` (a decimal string, computed live from the semantic model
   as the persona) using display-aware tolerance (``within_tolerance``). For table answers, compare
   every key in ``item["expected_table"]`` the same way (``item["table_match"]``).
5. Joint Work IQ + Fabric IQ cases also list ``item["expected_facts"]``: figures from a seeded
   document, such as the approved target. Each fact must match at least one parsed number of a
   compatible unit within the same tolerance. Facts are checked by presence, because the answer
   states the actual and the target side by side.

Code-based evaluator listed in evals/evaluators/evaluators.yaml, run unchanged by Microsoft Foundry
Evaluations or by the local backend. Score: 1.0 pass, 0.0 fail. Self-contained by design: standard
library only, no imports from copilot_evals, under 256 KB, no network.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

SCORE_PASS = 1.0
SCORE_FAIL = 0.0


class InconclusiveError(Exception):
    """The row does not hold enough information to decide this check."""


@dataclass(frozen=True)
class ParsedNumber:
    """One number found in the answer text (PLAN §9.6.1)."""

    value: Decimal  # already scaled, so "$1.2M" is Decimal("1200000")
    text: str  # the figure exactly as written
    unit: str | None  # "currency", "percent" or None for a plain number
    scale: Decimal  # 1, 1E3, 1E6 or 1E9
    decimals: int  # decimal places as displayed, used for display-aware tolerance
    is_percent: bool


@dataclass(frozen=True)
class Extraction:
    """The expected-blind extraction that the backend's extraction step generated for this row."""

    status: str  # "one", "several", "none" or "table"
    value: str | None  # the figure as written in the answer
    rows: tuple[tuple[str, str], ...]  # (key, figure as written) for table answers


def grade(sample: dict[str, Any], item: dict[str, Any]) -> float:
    """Return 1.0 when the stated value is within tolerance of the live expected value."""
    _require_usable_attempt(item)
    if item.get("expected_behavior") != "answer":
        return SCORE_PASS  # no value is expected; behavior_match judges these cases
    raise NotImplementedError("value_match is implemented by backlog task P2.5 (PLAN §9.6.1)")


def parse_numbers(text: str) -> list[ParsedNumber]:
    """Find every number in ``text``.

    TODO(P2.5): handle currency symbols and codes, thousands separators (",", NBSP, narrow NBSP),
    K/M/MM/B/bn and thousand/million/billion, percentages, and negatives written as "-", "−" or in
    parentheses. Strip fiscal labels, quarters, dates and years first. Use Decimal throughout.
    """
    raise NotImplementedError("P2.5")


def display_step(number: ParsedNumber) -> Decimal:
    """Precision step of a displayed number: ``10^(-decimals) x scale`` (PLAN §9.6.1). TODO(P2.5)."""
    raise NotImplementedError("P2.5")


def within_tolerance(expected: Decimal, number: ParsedNumber, tolerance: dict[str, Any]) -> tuple[bool, str]:
    """Display-aware tolerance with the over-rounding cap ``max_display_rel`` (PLAN §9.6.1). TODO(P2.5).

    Settle the open question in ADR-000 (the "$13M" example) with an ADR before writing fixtures.
    """
    raise NotImplementedError("P2.5")


def select_candidate(numbers: list[ParsedNumber], unit: str | None) -> ParsedNumber | None:
    """The single unit-compatible candidate, or None when ambiguous. Never uses the expected value. TODO(P2.5)."""
    raise NotImplementedError("P2.5")


def read_extraction(item: dict[str, Any]) -> Extraction | None:
    """Parse the expected-blind extraction from ``item["sample"]["output_text"]``.

    Returns None when the run produced no usable extraction. The local backend puts the extraction
    where Foundry does; Foundry documents that path as subject to change, and spike S7 confirms it
    (config/contracts.yaml).
    """
    sample = item.get("sample")
    text = sample.get("output_text") if isinstance(sample, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("status") not in ("one", "several", "none", "table"):
        return None
    rows = tuple(
        (str(row["key"]), str(row["value"]))
        for row in data.get("rows") or []
        if isinstance(row, dict) and "key" in row and "value" in row
    )
    value = data.get("value")
    return Extraction(status=str(data["status"]), value=str(value) if value is not None else None, rows=rows)


def _require_usable_attempt(item: dict[str, Any]) -> None:
    """Raise InconclusiveError when the surface call itself failed (timeout, throttling, error)."""
    status = item.get("status")
    if status != "ok":
        raise InconclusiveError(f"surface status {status!r}: there is no answer to evaluate")
