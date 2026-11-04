"""routing_match: the answer came from the expected certified semantic model(s) (PLAN §9.6.2).

Code-based evaluator listed in evals/evaluators/evaluators.yaml. Microsoft Foundry Evaluations or
the local backend calls grade() once per dataset row; one row is one attempt (schema:
eval-definition.yaml). The runner has already turned the engine logs and any tool trace into
`observed_models`, because evaluators have no network access.

Score: 1.0 pass, 0.0 fail. When the evidence cannot decide, grade() raises InconclusiveError: the
backend records an error for the row and the gate counts the attempt as INCONCLUSIVE, never FAIL.

Foundry receives this file as-is and the local backend executes it the same way, so it must stay
self-contained: standard library only, no imports from copilot_evals, under 256 KB.
"""

from typing import Any

SCORE_PASS = 1.0
SCORE_FAIL = 0.0


class InconclusiveError(Exception):
    """The row does not hold enough evidence to decide this check."""


def grade(sample: dict[str, Any], item: dict[str, Any]) -> float:
    """Check the semantic models the persona queried against the case's expectation.

    Route modes (``item["route_mode"]``):

    * ``includes``  every expected model was queried; other certified models may also appear.
    * ``exclusive`` exactly the expected models were queried.
    * ``any_of``    at least one expected model was queried.

    Engine logs can arrive late. A model seen in the logs is a fact even when the logs are still
    incomplete, so a definite result is returned as soon as the evidence allows; otherwise the
    check is inconclusive until the attempt's heartbeat proves the logs are complete (PLAN §9.5).
    Decoy models are scored by ``no_decoy``, not here.
    """
    _require_usable_attempt(item)
    if item.get("expected_behavior") != "answer":
        return SCORE_PASS  # nothing should be answered; behavior_match and no_decoy cover these cases

    expected = set(_strings(item.get("expected_models")))
    observed = set(_strings(item.get("observed_models")))
    complete = item.get("evidence_complete") is True
    mode = item.get("route_mode") or "includes"
    if not expected:
        raise InconclusiveError("answer case without expected models: fix the golden case")

    if mode == "includes":
        satisfied = expected <= observed
    elif mode == "any_of":
        satisfied = bool(expected & observed)
    elif mode == "exclusive":
        if observed - expected:
            return SCORE_FAIL  # another model was queried; later logs cannot undo that
        satisfied = observed == expected
        if satisfied and not complete:
            raise InconclusiveError("expected models seen, but later logs could still show another model")
    else:
        raise InconclusiveError(f"unknown route_mode {mode!r}")

    if satisfied:
        return SCORE_PASS
    if complete:
        return SCORE_FAIL  # includes "no Fabric query observed" once the logs are known to be complete
    raise InconclusiveError("engine-log evidence incomplete: the expected model may not be visible yet")


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
