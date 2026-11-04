# Architecture decision records

Significant decisions are recorded here as short ADRs, so the reasoning survives the people and the pull requests. PLAN §0 step 5 requires one for every Phase 0 spike *before* any code depends on its result.

## Index

| ADR | Decision | Status | Source |
|---|---|---|---|
| [ADR-000](ADR-000-repository-bootstrap.md) | Repository bootstrap conventions | Accepted | Bootstrap |
| ADR-001 | Role of the Copilot Chat API: primary base-Chat test or negative control | Pending | Spike S1 |
| ADR-002 | Engine-log correlation rules, poll budget, heartbeat on or off | Pending | Spike S2 |
| ADR-003 | Agent Evaluations CLI invocation, auth caching and output mapping | Pending | Spike S3 |
| ADR-004 | Include or drop the Copilot Studio path | Pending | Spike S4 |
| ADR-005 | Audit and Interaction Export reconciliation fields | Pending | Spike S5 |
| ADR-006 | Fabric IQ MCP tool argument names | Pending | Spike S6 |
| [ADR-007](ADR-007-foundry-evaluations-framework-of-record.md) | Microsoft Foundry Evaluations is the evaluation framework of record | Accepted, amended by ADR-009 | Owner decision, PLAN 1.1 |
| ADR-008 | Foundry evaluation contract in our project and region | Pending | Spike S7 |
| [ADR-009](ADR-009-two-evaluation-backends.md) | Two evaluation backends: Microsoft Foundry Evaluations (default) or local | Accepted | Owner decision, PLAN 1.2 |
| [ADR-010](ADR-010-joint-work-iq-fabric-iq-evaluation.md) | Evaluate joint Work IQ + Fabric IQ answers with seeded documents and a sixth evaluator | Accepted | Owner decision, PLAN 1.3 |
| ADR-011 | Which surfaces run the joint Work IQ + Fabric IQ cases, and the indexing wait | Pending | Spike S8 |

## Writing an ADR

1. Copy [adr-template.md](adr-template.md) to `ADR-NNN-short-title.md` with the next free number (ADR-001 to ADR-006, ADR-008 and ADR-011 are reserved for the spikes).
2. Keep it short: context, evidence, decision, consequences. Link the issue and the plan sections.
3. **Sanitise the evidence.** No tenant IDs, domains, user names, workspace or item IDs, tokens or customer data.
4. If the decision confirms or changes an API contract, update [`config/contracts.yaml`](../../config/contracts.yaml) in the same pull request: set `status: confirmed`, set `adr:`, and remove the `TODO(spike-Sx)` markers you resolved.
5. Add the ADR to the index above.

An accepted ADR is not edited later; a new ADR supersedes it.
