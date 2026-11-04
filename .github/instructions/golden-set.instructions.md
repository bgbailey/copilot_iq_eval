---
applyTo: "evals/golden/**"
---

# Golden-set files

The golden set is the contract the demo is judged against. Schema: `src/copilot_evals/schemas.py` (`Case`, `Persona`, `SemanticModelRef`, `DocumentRef`); design: PLAN §5.

- Case IDs follow `<PREFIX>-<NNN>` (for example `REV-001`), are stable and are **never reused**. Prefixes in use: `REV` revenue, `FIN` finance, `OPS` service operations, `TI` time intelligence, `X` cross-model, `CLR` clarification, `NOA` no access, `JNT` joint Work IQ + Fabric IQ.
- Every case belongs to one category in PLAN §5.2 and is tagged for it. Group paraphrases of one question under one `intent`.
- `persona`, `models`, `decoys` and `doc_decoys` must be keys that exist in `personas.yaml` and `models.yaml`. A decoy model can never be an expected model.
- Reference DAX uses the business-friendly names from PLAN §4.2 (`'Date'[Fiscal Year]`, `'Region'[Region]`, `[Gross Revenue]`, ...) and runs as the case's persona against the first expected model. Use `composite` only when no single query can produce the value, and implement the resolver in `ground_truth/composite.py`.
- Never write expected values into a case: they are computed live (and frozen in `expected_snapshot.json` by P1.7).
- Joint cases (PLAN §4.4, ADR-010) list the documents the answer must cite in `expect.work_sources` and the document figures it must state in `expect.work_facts` (`<document>.<fact>`). Documents and their facts live in `models.yaml`; a work source can never also be a `doc_decoy`. Document text lives in `workiq/content.yaml`.
- Tolerances: currency `{rel: 0.005, display_aware: true}`, counts `{abs: 0}`, percentages `{abs: 0.001, display_aware: true}`, unless a case needs otherwise; say why in `notes`.
- `critical` cases use `runs: 3` and must pass k of k.
- Synthetic data only: no real customer names, people or figures. Never commit a tenant domain or UPN: personas use the `{tenant_domain}` template.
- Validate before you finish: `uv run evals validate --strict`.
