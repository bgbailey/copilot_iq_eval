# Responsible Use, Transparency, and Limitations

`cfeval` helps engineering, BI, and analytics teams measure grounding quality systematically before and after changes to semantic models, workplace content, prompts, or MCP tools. Responsible deployment requires understanding its methodological boundaries.

> For a concise Q&A summary, read the top-level [Transparency & Limitations FAQ](../../TRANSPARENCY_FAQ.md).

## Intended Uses

- **Pre-release & CI regression testing:** Catching broken DAX measures, ambiguous column synonyms, decoy-model routing regressions, or broken MCP tool schemas before rollout.
- **Controlled A/B tuning comparisons:** Quantifying whether semantic-model Prep-for-AI descriptions, endorsement badges, or custom instructions measurably improve `pass^k` with paired McNemar significance.
- **Offline pilot transcript audits:** Scoring curated transcripts exported from user acceptance testing via `transcript-import`.

## Out-of-Scope Uses

- **Employee surveillance or individual performance grading:** Never run `cfeval` against real employee chat histories without organizational privacy review and consent. Always evaluate live tenants using dedicated synthetic or test accounts (`eval.tester@contoso.com`).
- **Sole release gate for high-stakes financial/regulatory disclosures:** Passing a 42-question benchmark reduces risk within covered intents but does not guarantee zero errors on novel phrasing or unmodeled edge cases.
- **Security / RLS compliance certification:** Passing value and routing checks under one persona does not prove absence of cross-role data leakage unless paired with explicit per-role negative/abstention suites.

## Key Technical Limitations

1. **Sample size & confidence width:** Small smoke suites (`N = 8`) carry wide binomial uncertainty; use 40+ domain-representative questions and `trials >= 3` for release decisions.
2. **Observational KQL correlation:** Matching `SemanticModelLogs` by user + time window is high-precision under an isolated test user, but concurrent queries by the same user against the same model can create attribution ambiguity.
3. **Judge model drift:** LLM judge scores (`Coherence`, `Groundedness`, custom explanation checks) depend on the judge deployment version. Keep deterministic gates (`value`, `artifact`, `model`) primary, and re-run `calibrate-judge` whenever changing judge models.
4. **Workspace preservation & cost governance:** Evaluation scripts must never delete or empty Fabric workspaces; manage evaluation environment cost via bounded capacity windows and capacity pause.
