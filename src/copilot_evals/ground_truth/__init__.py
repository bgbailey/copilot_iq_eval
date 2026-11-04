"""Live ground truth from the semantic models (PLAN §5.3, §9.4). Built by P2.4.

Planned modules:

* ``dax``        Power BI ``executeQueries`` as the persona (``impersonatedUserName`` where needed), each
                 query tagged ``// eval-gt case=<id>`` so engine-log correlation excludes it; Fabric IQ
                 ``ExecuteQuery`` as the fallback. One query per call, at most 120 requests per minute per
                 user, cached per run x case x persona.
* ``refresh``    Last model refresh (or Direct Lake framing) time, recorded with every expected value.
* ``composite``  Named resolvers for values no single query can produce, such as cross-model cases
                 (``expect.value.composite`` in the golden set, for example ``X-001``).

Ground truth always runs before the attempt window opens (t0), so it never pollutes routing evidence.
"""
