"""Surface adapters: one per Copilot surface under test (PLAN §9.3).

Every adapter implements ``targets.base.Target``. The runner depends only on that protocol, so unit
tests use fakes and adapters can be added or dropped (per the Phase 0 ADRs) without touching it.

Planned adapters:

* ``ref_mcp``             L1  reference orchestrator: Azure OpenAI model + Fabric IQ MCP (P3.1-P3.3)
* ``agent_cli``           L2  declarative agent through the Agent Evaluations CLI (P4.3)
* ``chat_api``            L3  Microsoft 365 Copilot Chat API, beta (P6.1)
* ``interaction_export``  L3  tester sessions harvested from the Interaction Export API (P6.2)
* ``copilot_studio``      L2  optional, only if ADR-004 is positive (P7.1)
* ``data_agent``          L1-DA optional Fabric data agent diagnostics (P7.2)
"""
