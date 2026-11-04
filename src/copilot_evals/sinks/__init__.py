"""Result sinks (PLAN §9.8). Built by P2.6 and P8.1.

The sinks take the evaluation results from either backend, with the runner's attempts and evidence,
to where the business and CI read them. On the Foundry backend, Foundry also keeps the results and a
report page per run; on the local backend, the run artifacts and the Lakehouse are the record.

Planned modules:

* ``onelake``  Append run artifacts to Delta tables in ``ws-eval-results / lh_eval`` with ``deltalake``
               and an app-only OneLake token; fall back to JSONL in ``Files/inbox/`` if needed.
* ``junit``    ``out/junit.xml`` with one test case per case x surface x persona, for PR annotations.
* ``summary``  ``out/summary.md``: pass rates with Wilson 95% intervals, failures with reasons, the
               backend used and, on the Foundry backend, the run's report link.
"""
