# Metrics & Statistics Guide (Moved)

Metric definitions, structured v2 scorers, and statistical confidence intervals live in the canonical Concepts and How-To pages:

- **[Metrics and Statistical Tests](concepts/metrics.md)** — `pass@1`, `pass^k`, Wilson 95% score intervals, exact paired McNemar `p`-values, `MatchKind` taxonomy (`exact_match`, `display_rounded`), and why `LatencyMs` and `DaxTotalMs` are non-additive.
- **[Evidence Tiers and Verdicts](concepts/evidence-and-verdicts.md)** — `RoutingEvidence`, `CorrelationConfidence`, and `PASS` / `FAIL` / `INCONCLUSIVE` / `ERROR` rules.
- **[Calibrate the LLM Judge](how-to/calibrate-the-judge.md)** — Running `cfeval judge calibrate`, Cohen's kappa (`>= 0.70`), fail-class recall, and pass-class precision.
- **[Metrics Methodology (Extended Notes)](concepts/metrics-and-statistics.md)** and **[Glossary](reference/glossary.md)** — Extended statistical notes and Microsoft evaluation vocabulary mapping.
- **[Telemetry Schema Reference](reference/telemetry-schema.md)** and **[Transparency & Limitations FAQ](../TRANSPARENCY_FAQ.md)** — Column definitions and interpretation guardrails.

