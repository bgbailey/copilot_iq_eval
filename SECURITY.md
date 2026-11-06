# Security

Please don't report security problems in public issues.

* Use GitHub's **private vulnerability reporting** (the repository's **Security** tab, **Report a vulnerability**).
* Include what you found, how to reproduce it, and its impact. Don't include real tenant IDs, tokens, secrets or
  customer data; use placeholders.

## Handling secrets in this project

* Settings live in `.env` (ignored by git) or Azure Key Vault. Never commit `.env`, token caches (`.cache/`) or run
  folders (`runs/`) that may contain answers from your tenant.
* The Copilot Chat API runs as a dedicated test user. Give that user only the access the golden set needs.
* Run folders and the Eventhouse store Copilot's answers. Treat them with the same sensitivity as the data the
  semantic models hold, and restrict access to the telemetry workspace and the scorecard app accordingly.
