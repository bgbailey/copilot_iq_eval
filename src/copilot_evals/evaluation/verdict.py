"""How evaluator results combine into an attempt's verdict (PLAN §3.4, §9.6.7).

The rule is the same whichever backend produced the results. The gate (P2.6) builds case results and
the pass^k checks on top of it.
"""

from collections.abc import Iterable

from copilot_evals.schemas import EvaluatorResult, Outcome


def attempt_outcome(results: Iterable[EvaluatorResult]) -> Outcome:
    """Combine one attempt's evaluator results into its verdict.

    Any FAIL fails the attempt. Otherwise any INCONCLUSIVE result (an evaluator could not decide, for
    example because the engine logs were incomplete) makes the attempt INCONCLUSIVE. Otherwise it
    passes. An attempt with no results is INCONCLUSIVE: nothing was checked.
    """
    outcomes = {result.outcome for result in results}
    if Outcome.FAIL in outcomes:
        return Outcome.FAIL
    if Outcome.INCONCLUSIVE in outcomes or not outcomes:
        return Outcome.INCONCLUSIVE
    return Outcome.PASS
