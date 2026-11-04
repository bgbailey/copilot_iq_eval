"""Routing and citation evidence (PLAN §9.5). Built by P5.1-P5.4 and P6.3.

Planned modules:

* ``engine_logs``  App-only Kusto client for the workspace-monitoring Eventhouses (certified and sandbox).
* ``correlate``    Per-attempt window query with heartbeat completeness: send ``// eval-hb <attempt_id>``,
                   poll ``SemanticModelLogs`` until it appears (or ``settings.evidence.max_wait_s``
                   expires), then map ItemIds to model keys. Missing heartbeat => ``evidence_complete``
                   is false, so the routing evaluators report INCONCLUSIVE, never FAIL.
* ``normalize``    Chat API attributions, CLI citations and tool traces => ``schemas.Evidence`` rows.
* ``audit``        Daily Purview ``CopilotInteraction`` query: AppHost, AgentId, AccessedResources.

Decoy hits are only visible in the sandbox workspace's logs, so both Eventhouses are always queried.
The evidence becomes the ``observed_models``, ``observed_by_source``, ``citations`` and
``evidence_complete`` fields of each evaluation row (``schemas.EvalItem``); the evaluators judge it,
on whichever backend runs them.
"""
