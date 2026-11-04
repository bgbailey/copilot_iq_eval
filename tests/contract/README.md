# Contract tests

Contract tests replay **recorded, sanitised** responses from external services (Microsoft Foundry evaluation runs and output items, Azure OpenAI judge replies, Fabric IQ MCP, Copilot Chat API, Agent Evaluations CLI reports, Kusto) to prove that adapters parse them as `config/contracts.yaml` describes. They never touch the network, so they run in CI.

- Fixtures live under `tests/fixtures/<service>/`.
- Re-record only with `evals fixtures record` (added with the first adapter, P3.2), then sanitise: no tenant IDs, user names, workspace or item IDs, or URLs containing them.
- Mark tests with `@pytest.mark.contract`.
