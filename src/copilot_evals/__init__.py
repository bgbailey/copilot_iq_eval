"""Copilot x Fabric IQ evaluation harness.

Proves that Microsoft 365 Copilot surfaces route business questions to the intended Power BI
semantic model (through Fabric IQ) and return the expected value, consistently, per persona.

The design lives in docs/PLAN.md; section references such as "PLAN §9.6.1" in docstrings and
comments point there. Package map:

* ``schemas``       data contracts shared by every component, including the evaluation row (PLAN §5.1, §9.1)
* ``golden``        golden-set loading and cross-file checks (PLAN §5)
* ``config``        non-secret settings from config/settings.toml
* ``cli``           the ``evals`` command
* ``auth``          persona and daemon credentials (PLAN §11)
* ``ground_truth``  live reference values from the semantic models (PLAN §9.4)
* ``targets``       surface adapters: one per Copilot surface under test (PLAN §9.3)
* ``evidence``      engine logs, citations, audit and correlation (PLAN §9.5)
* ``evaluation``    runs the evaluators on the chosen backend, and the local backend (PLAN §9.11, §9.12)
* ``foundry``       the Foundry backend: a thin client for Microsoft Foundry Evaluations (PLAN §9.11)
* ``sinks``         evaluation results to OneLake, JUnit and Markdown (PLAN §9.8)

Every verdict comes from the evaluators in ``evals/evaluators/``, run either by Microsoft Foundry
Evaluations or by the local backend (ADR-007, ADR-009). No other code in this package scores an answer.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("copilot-fabriciq-evals")
except PackageNotFoundError:  # pragma: no cover - only when running from a source tree without installing
    __version__ = "0.0.0+unknown"
