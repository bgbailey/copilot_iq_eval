# Setup Guide (Moved)

Setup instructions are split by workflow so you only configure what you need:

- **[Prerequisites](get-started/prerequisites.md)** — Required Microsoft 365 Copilot and Fabric licences, dedicated synthetic test user (`eval.tester@contoso.com`), and Workspace Monitoring prerequisites.
- **[First Live Run](get-started/first-live-run.md)** — Smallest end-to-end live evaluation in a demo tenant (`cp .env.example .env`, `cfeval doctor --strict`, `cfeval login`, `cfeval setup`, `cfeval run --strict`, `cfeval report`).
- **[Cost and Operational Limits](get-started/cost-and-limits.md)** — Fabric capacity consumption, Eventhouse storage, judge token budgets, and expected wall-clock duration.
- **[Offline Quickstart](get-started/quickstart-offline.md)** and **[Transcript Import Quickstart](get-started/quickstart-transcript-import.md)** — Zero cloud setup; run `cfeval` locally in 60 seconds.
- **[Capture Engine DAX](how-to/capture-dax.md)** and **[Fabric Workspace Setup](how-to/fabric-setup.md)** — Configure Workspace Monitoring (`SemanticModelLogs`), filter index-build noise, and probe traces (`cfeval trace probe`).
- **[Configuration Reference](reference/configuration.md)** and **[Threat Model](responsible-use/threat-model.md)** — Complete `CFEVAL_*` variable listing and security guardrails.

Model preparation improves the model contract, not deterministic API source selection. A named-source success
does not prove repaired unqualified discovery; the API exposes no source/agent selector. The generated why is not
chain of thought. Exact publication counts are not hosted UI/SSO proof; complete those gates in the Fabric portal.
