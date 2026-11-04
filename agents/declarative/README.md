# Declarative agent: Contoso Certified Metrics (L2)

The agent under test at layer L2: a Microsoft 365 Copilot declarative agent with the **Fabric** capability, so it answers from Power BI semantic models as the signed-in user (RLS and OLS apply). The Agent Evaluations CLI drives it once per attempt, per persona (PLAN §9.3.2).

> This folder is built by backlog tasks **P4.1** (agent project), **P4.2** (provision and share, manual) and **P4.4** (A/B variants). Until then it only holds this description.

## What P4.1 adds here

```text
agents/declarative/
└─ appPackage/
   ├─ manifest.json
   ├─ declarativeAgent.json          # schema v1.9, capabilities: [{"name": "Fabric"}]
   ├─ instructions.md                # GENERATED from agents/policy/routing-policy.md: do not edit
   └─ skills/fabric-routing/SKILL.md # routing table, disambiguation, forbidden sources, answer contract
```

Key settings (PLAN §9.7):

- `version` `v1.9`, name **Contoso Certified Metrics**, five conversation starters;
- `capabilities: [{"name": "Fabric"}]`. No property pins specific models, so routing is steered by the instructions, the agent skill and the user's access;
- `agent_skills: [{"folder": "./skills/fabric-routing"}]`;
- `behavior_overrides.special_instructions.discourage_model_knowledge: true`.

`scripts/build_agent.py` regenerates the instructions from the routing policy and fails CI if the policy and the manifest drift. Validate the package with `wiqd agent validate`.

## Variants for the A/B demo (P4.4)

| Variant | Contents |
|---|---|
| `agent-v1` | Instructions only |
| `agent-v2` | Instructions + agent skill + editorial answers for three high-value questions |

The scorecard shows the routing lift between them.
