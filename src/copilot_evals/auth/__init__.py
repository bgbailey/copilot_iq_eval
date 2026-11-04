"""Credentials for personas and the daemon app (PLAN §11). Built by P2.3.

Planned modules:

* ``delegated``       MSAL public client per persona; one-time device-code bootstrap
                      (``evals auth login --persona exec``), silent acquisition afterwards. Never ROPC.
* ``keyvault_cache``  MSAL serializable token cache stored as Key Vault secret ``msal-cache-<persona>``,
                      written back whenever it changes.
* ``app_only``        Certificate credential for ``copilot-eval-daemon`` (Interaction Export, audit query,
                      monitoring KQL read, results write).

Scopes come from ``config/contracts.yaml``; nothing here may log or persist a token.
"""
