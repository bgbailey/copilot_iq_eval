# Security

Please don't report security problems in public issues. Use GitHub's private vulnerability reporting on this repository's **Security** tab, and include the commit, the steps to reproduce and the impact. Don't include real tenant IDs, tokens or customer data.

## Using this accelerator safely

- Run it only as a dedicated test user in a demo or test tenant. The Copilot Chat API needs broad delegated read permissions, so Copilot can use everything that account can see.
- Keep `.env`, `.token_cache.json` and `results/` on your machine. They're in `.gitignore`.
- The results Eventhouse, the Lakehouse and the scorecard app contain Copilot's answers and the DAX it ran. Grant access to them deliberately.
- Turn on GitHub secret scanning in any copy of this repository.
