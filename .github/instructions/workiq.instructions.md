---
applyTo: "workiq/**"
---

# Work IQ content pack

- **Edit `workiq/content.yaml`, never the `.docx` files.** Rebuild them with `uv run python scripts/build_workiq_documents.py`; CI fails if a committed document differs from its source.
- **Figures only through `{fact}` placeholders.** Every number a document states comes from `evals/golden/models.yaml` `documents.<key>.facts`, the single source the joint cases score against. Every fact must be stated at least once.
- **Synthetic content only.** Contoso is fictional; never paste real customer, employee or tenant content, names or URLs.
- **Permissions are part of the test.** A `source` document must live on a site that no persona without data access (`rls_role` unset, such as `noaccess`) can read; decoys may be readable by everyone. `tests/unit/test_workiq_content.py` enforces it.
- The calibrated FY2025 figures in nb_01 make the comparisons true (PLAN §4.4); change a target or objective only together with the cases that depend on it.
