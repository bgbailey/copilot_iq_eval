---
applyTo: "**/*.md,docs/**,notebooks/**"
---

# Documentation and notebooks

- Write plain, complete sentences. Lead with runnable commands and expected outcomes, use one term per concept, and follow `docs/reference/glossary.md`.
- Use product names as Microsoft Learn writes them. Label preview/beta features explicitly as preview, include a `Last verified: YYYY-MM-DD` date (`docs/reference/platform-status.md`), and link to official Microsoft Learn documentation instead of restating upstream product internals.
- Use valid relative links inside the repository (`python tools/check_docs_links.py` verifies every Markdown link).
- Use synthetic Contoso examples (`@contoso.com`, `contoso.com`, placeholder UUIDs) and describe environments as `"demo tenant"` and `"demo Azure subscription"`. Never include real tenant IDs, workspace IDs, UPNs, customer names, or wording tied to a single demo, meeting, date, or operator (`python tools/check_public_wording.py` enforces `config/wording-denylist.txt`).
- Do not claim official Microsoft product support, certification, or endorsement. State clearly what is verified by deterministic evidence versus what remains unproven.
- Commit notebooks without cell outputs (`*.ipynb` clean). External notebooks should install a tagged release rather than floating `main`.
- Do not rewrite `docs/PLAN.md` wholesale; tick finished `[x]` items or correct factual status notes only when verified.
