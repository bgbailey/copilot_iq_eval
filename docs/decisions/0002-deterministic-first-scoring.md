# ADR 0002: Deterministic-First Scoring with Calibrated Opt-In Judges

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

Many open-source LLM evaluation toolkits rely primarily on `1–5` Likert LLM-as-judge scores (`Groundedness`, `Relevance`, `Correctness`) to determine pass/fail verdicts. In enterprise BI and workplace grounding (`Fabric IQ` and `Work IQ`), LLM-only grading exhibits three failure modes:

1. **Numeric blindness:** Judges frequently award `5/5` to fluent answers that report `$12.48M` instead of `$12.84M`, confuse gross vs net revenue, or omit unit scale (`bps` vs `%`).
2. **Decoy blindness:** A response quoting a clean number from `Sales Sandbox` looks indistinguishable from `Sales Analytics` in prose unless citations and `SemanticModelLogs` `DatasetId` are checked deterministically.
3. **Non-reproducible CI gates:** Judge prompt or model updates can flip CI status without any change to the system under test.

## Decision

1. **Deterministic v2 gates (`value`, `artifact`, `model`) own the default `PASS` / `FAIL` verdict.** Schema v2 expands deterministic scoring beyond scalars to `ranked_list`, `set`, `table`, `record`, `direction`, `citation_only`, and `abstention`.
2. **LLM judge scores are recorded as diagnostic columns by default** (`JudgeScore`, `FoundryGroundedness`, `FoundryRelevance`, `FoundryCoherence`, `FoundryFluency`) and only participate in pass/fail gating when explicitly requested (`--gate-on-judge`).
3. **Ship `calibrate-judge` (`Cohen's κ`)** so teams that opt into judge gating can quantify human-judge agreement first (`κ >= 0.70` recommended).

## Consequences

- **Positive:** 100% deterministic, zero-cost, zero-network scoring for `transcript-import`, `--mock`, and `rescore`; zero hallucinated passes on wrong KPI figures or decoy semantic models.
- **Negative / Trade-off:** Authoring structured `expect` blocks in golden YAML requires upfront verification of ground-truth figures (`seed_contoso.py --verify` / `grounding_query_dax`), which is intentional discipline for business KPIs.
