"""The Foundry backend: Microsoft Foundry Evaluations runs the evaluators (PLAN §9.11, ADR-007).

The default evaluation backend (ADR-009). Foundry runs the evaluators in ``evals/evaluators/`` in the
customer's Azure subscription, keeps every verdict and publishes a report page per run. This package
is the thin client around it and never scores an answer itself. It implements
``copilot_evals.evaluation.backend.EvaluationBackend``, so the runner and the gate treat it exactly
like the local backend (``copilot_evals.evaluation.local``).

Planned (P2.7, after spike S7):

* ``catalog``  ``evals foundry sync``: register each evaluator with
               ``project_client.beta.evaluators.create_version`` under its content-addressed name
               (``evaluation.definitions.catalog_name``), so a run always uses the evaluators in its commit.
* ``runs``     Substitute the placeholders in ``eval-definition.yaml``, upload ``eval_items.jsonl`` with
               ``project_client.datasets.upload_file``, create the eval and the run, poll until
               ``completed``, ``failed`` or ``canceled``, and read the output items and ``report_url``.
* ``results``  Map output items to ``schemas.EvaluatorResult``: passed -> PASS, failed -> FAIL,
               errored (the evaluator raised, for example on incomplete evidence) -> INCONCLUSIVE.

Every call reads its endpoint and field names from ``config/contracts.yaml`` (``foundry_evaluations``).
"""
