# Copilot Studio agent (optional L2)

An optional second L2 surface: a Copilot Studio agent with the Fabric IQ MCP tool or a Fabric data agent tool, evaluated through the Copilot Studio evaluation REST API and its *Tool use* grader (PLAN §9.3.4).

> **Gated by spike S4.** The current Fabric data agent tool needs the newer GitHub Copilot harness, while the evaluation REST API and the Tool use grader are documented for the standard harness (PLAN §2.1 finding 6). This path is built (task **P7.1**) only if **ADR-004** records that the combination works.

If it goes ahead, this folder holds:

- the generated test-set CSV (`Question`, `Expected response`) for the one-time manual import into Copilot Studio;
- notes on the agent's configuration, the user-profile connection used for authenticated runs, and the Application Insights telemetry used as extra routing evidence.
