# Test fixtures

Sanitised recordings and sample inputs used by unit and contract tests, one folder per service (for example `foundry/`, `azure_openai/`, `mcp/`, `chat_api/`, `agent_cli/`, `kusto/`), plus parser fixtures such as `numbers.yaml` for the numeric scorer (P2.5).

Never commit a fixture that contains a tenant ID, domain, user principal name, workspace or item ID, token or customer data.
