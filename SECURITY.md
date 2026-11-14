# Security

Please do not report security vulnerabilities in public issues or pull requests.

* **Reporting**: use GitHub's **private vulnerability reporting** on the repository's **Security** tab (**Report a vulnerability**). Maintainers aim to acknowledge reports within 5 business days.
* **What to include**: affected version/commit, minimal reproduction steps, and potential impact. Do not include real tenant IDs, tokens, secrets, or customer data; use synthetic Contoso placeholders.

## Security invariants in `cfeval`

* **Dedicated synthetic test identity**: Because the Microsoft 365 Copilot Chat API requires broad delegated Graph read scopes (`Mail.Read`, `Chat.Read`, `ChannelMessage.Read.All`, `Sites.Read.All`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, `ExternalItem.Read.All`), live evaluations must run under a dedicated synthetic test account (such as `eval.tester@contoso.com` in an isolated demo tenant), never a real employee mailbox.
* **Secret and cache protection**: Settings live in `.env` (gitignored) or Azure Key Vault, with local tokens protected by OS credential stores (Windows DPAPI / Keychain / libsecret). Never commit `.env`, token caches (`.cache/`), or live run folders (`runs/`).
* **Explicit identity verification (no silent account switching)**: Live commands verify JWT `tid` and `upn` claims against `CFEVAL_TENANT_ID`, `CFEVAL_OPERATOR_UPN`, and `CFEVAL_TEST_USER_UPN` (`src/cfeval/auth.py`, `src/cfeval/runtime.py`) before issuing requests and abort on mismatch. Ambient credential chains (`DefaultAzureCredential`) and shared `~/.azure` profiles are rejected by design.
* **Telemetry workspace governance**: Run folders and Eventhouse tables (`EvalAsk`, `EvalResult`, `FabricIqQuery`) store model answers and observed DAX queries. Apply least-privilege RBAC as documented in the [Threat Model](docs/responsible-use/threat-model.md).
