"""One set of evaluators, two places to run them (PLAN §9.6, §9.11, §9.12, ADR-007, ADR-009).

Every verdict comes from the evaluators in ``evals/evaluators/``: code-based ``grade()`` files for
the right number, the right semantic model, no decoy and citations, and a prompt-based AI judge for
the clarify, refuse and no-access behaviours. Where they run is a per-run choice:

* ``foundry`` (default): Microsoft Foundry Evaluations runs them in the customer's Azure
  subscription and keeps every verdict, with a report page per run. Client: ``copilot_evals.foundry``
  (P2.7).
* ``local``: the harness runs the same files in its own process, on the GitHub Actions runner or a
  developer machine, and calls the AI judge directly on an Azure OpenAI deployment. No Foundry
  project is needed. Backend: ``copilot_evals.evaluation.local``.

Both backends return the same ``EvaluatorResult`` rows, with the same evaluator names and
content-addressed versions, so the gate, the results sink and the Power BI scorecard work the same
way on either.

Modules:

* ``definitions``  Load ``evals/evaluators/`` and check it offline (``evals validate``).
* ``backend``      The ``EvaluationBackend`` protocol, ``BackendName`` and ``EvaluationRun``.
* ``local``        The local backend.
* ``verdict``      How evaluator results combine into an attempt's verdict (PLAN §3.4, §9.6.7).
"""
