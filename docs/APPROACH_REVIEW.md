# Copilot × IQ evaluation accelerator: approach review

| | |
|---|---|
| Repository | `bgbailey/copilot_iq_eval`, commit `a9b0d39` |
| Reviewed | 13 Nov 2026 |
| Basis | The repository's code and documentation, an offline run of its simulated paths, direct calls to its scoring functions, and public documentation read on the review date. No live path was run |
| Companion | `copilot-iq-eval-public-readiness-plan.md` holds the work plan, the findings register and the full source table. "R" numbers below refer to section 12 of that plan |

## 1. Verdict

**The core approach is right.** The repository checks each answer against a value computed live from the semantic model, decides the verdict with deterministic rules, and confirms from the engine's own query log which model was used. That is the test method Microsoft's guidance describes for Copilot over semantic models (R4), and it is the part that Microsoft's own evaluation tools do not cover, as documented today, for analytics questions asked of Microsoft 365 Copilot (R6, R12, R16).

**Three things should change before it is promoted widely.**

1. **Do not depend on one preview driver.** The only way in is the Copilot Chat API under Microsoft Graph `/beta`. Make targets pluggable, accept answers captured by other means, and interoperate with Microsoft's Evaluations CLI.
2. **Raise the rigour of scoring and statistics.** The value check misgrades common answer shapes in both directions, results carry no intervals, the bundled set has 8 cases, and the judge is not calibrated.
3. **Bring the engineering up to the standard of something others rely on.** There are no tests, by policy. Wording is tied to one demonstration. SDK pins are behind. Governance files and settings are incomplete.

Harden now. Re-check the approach after Microsoft Ignite (17–20 Nov 2026) before promoting it broadly, because one session covers an evaluation loop for Microsoft IQ (section 6).

## 2. What the repository does

1. Reads a golden set of business questions. Each has an expected value, a reference DAX query, the expected semantic model and report, and optional decoys.
2. Asks each question of Microsoft 365 Copilot Chat as a licensed test user, through the Microsoft Graph Copilot Chat API, with web grounding switched off, followed by a second turn that asks Copilot to explain its sources.
3. Collects evidence: the citations in the response, and the DAX queries that ran for that user in that time window, read from Fabric workspace monitoring.
4. Scores three checks with code (value, cited artifact, queried model) and adds an optional judge model. Missing evidence is reported as inconclusive, never as a pass.
5. Writes every run to local JSONL files and to a Fabric Eventhouse. A Fabric app shows trends.

A second scoring path sends the same data to Foundry Evaluations. A simulated tenant runs the whole pipeline offline.

## 3. Published guidance compared with the implementation

| Topic | What the public source says | What the repository does | Assessment |
|---|---|---|---|
| How to test Copilot over a semantic model | Define the expected measure, grouping, date context, filters and result for each question, and compare answers with validated results. Verified answers are not used when Fabric IQ answers (R4) | A golden set with reference DAX that is executed live for ground truth | **Aligned.** Add the intent fields to each case |
| How to drive Copilot | The Chat API is a preview under `/beta`, not supported for production use, delegated only, and documented for enterprise search and web grounding (R1, R2) | The Chat API is the only driver | **Risk.** Answers grounded in Power BI through this API are observed behaviour, not documented behaviour. Confirm it first in each tenant and add other targets |
| First-party evaluation tooling | The Microsoft 365 Copilot Evaluations CLI evaluates deployed agents. Its v2 upgrade guide describes a preview that targets Microsoft 365 Copilot itself and can re-score saved responses. Its evaluators cover relevance, coherence, groundedness, similarity, citations, retrieval and string matching (R6) | No interoperability | **Complementary.** None of those evaluators compares a number with live ground truth or checks which semantic model was queried. Exchange files with the CLI; do not compete with it |
| Coverage and repeatability | 20 to 50 cases for a prototype, 50 to 100 before production, more than 100 in production. Run several times and average (R7) | 8 cases, one attempt by default, no intervals | **Below guidance.** Add repeats, pass^k, intervals and run comparison; grow the set |
| Fabric IQ in Copilot Chat | Generally available. Permissions and row-level security apply. Copilot may need to be told to use Power BI data, and an attachment does not limit the answer to that item (R3) | Named-source, routing and decoy cases; one test user | **Good start.** Add paraphrases and personas |
| Engine evidence | The query log has user, application and operation fields. No documented value identifies Copilot as the caller (R8). One monitoring item can serve several workspaces (R9) | Matches queries to a question by user and time window | **Reasonable, but it is correlation.** Read more fields, flag ambiguous matches and label the confidence |
| Noise in the query log | Queries from building Copilot's text index also appear in the log, with a recognisable shape (R18, unofficial) | Only the harness's own marker query is recognised | **Gap.** Exclude the index-build pattern |
| Foundry evaluation | Custom evaluators are in preview, with size, time and network limits (R11). Quality Grader is deprecated (R13). Preview APIs were renamed in October 2026 (R14). The current SDK needs a newer `openai` major version (R15) | An optional second scoring path, pinned to older SDK lines | **Keep optional.** Update the pins and label it experimental until a live run is recorded |
| A second route to the same data | The Fabric IQ MCP server exposes semantic models to agents with delegated sign-in (R5) | Not used | **Opportunity.** A reference agent on this server gives exact tool-call evidence and separates model readiness from Copilot routing |
| Method | Report uncertainty with scores; measure reliability across repeats; validate a judge against human labels (R21) | None of these yet | **Add.** |

## 4. What to keep

- Three independent signals per answer: the value, the citations and the engine query log.
- Verdicts decided by code. The judge adds context and does not decide.
- Honest statuses. Missing evidence is inconclusive, a failed call is an error, and neither counts as a pass.
- A simulated tenant that runs the whole pipeline with no sign-in.
- One schema definition that generates the database script and the app contract, with a drift check in CI.
- A local record of every run, whatever happens to the remote store.

## 5. Findings that change verdicts today

Reproduced by calling the repository's scoring functions directly. The plan's Appendix A has the full register and a script that reproduces these.

| Finding | Example | Effect |
|---|---|---|
| The value check takes the first number in the answer | "Compared with $12.2M last year, gross revenue rose to $12.84M in FY2025." is graded against $12.2M | Correct answers fail |
| Ratio and percent are not reconciled | "Gross margin was 0.416" for an expected 41.6 percent | Correct answers fail |
| Display rounding is tolerated up to 5% | "About $13M." passes for an expected 12,840,000 | Vague answers pass |
| The three gate checks are fixed | Without workspace monitoring, an offline run passes nothing: every correct answer is inconclusive | Tenants without monitoring cannot get a pass |
| Names match by word containment | "Sales Sandbox" matches an expected "Sales" | A look-alike item can count as the right one |

## 6. Microsoft Ignite 2026 sessions to watch

Only titles and abstracts were available at review time (17–20 Nov 2026, San Francisco; R22).

| Session | Title | Why it matters here |
|---|---|---|
| BRK310 | The evaluation loop for Microsoft IQ | Closest to this accelerator's purpose. It may introduce an official loop, vocabulary or tool |
| BRK356 | Microsoft IQ roadmap: The operating system for enterprise AI agents | Planned quality controls |
| BRK306, BRK305, BRK301 | Fabric IQ and Microsoft IQ sessions | Changes to how Copilot reaches semantic models and other sources |
| BRK304 | What's new in Work IQ | Programmatic endpoints that could become a better-supported way to drive Copilot |
| LTG1214 | Observability for AI with Fabric Data Agent, Foundry, and Agent 365 | Telemetry that could replace time-window matching |
| BRK249, BRK251 | Foundry improvement loop and production evaluation | Evaluation API changes |

## 7. What was and was not verified

**Verified**

- Every repository fact, at commit `a9b0d39`: the code was read in full and the offline paths were run.
- The scoring findings, by calling the functions with the examples above.
- Every product fact, against the linked public page on 13 Nov 2026.

**Not verified**

- Any live behaviour. No tenant was used. In particular: whether the Chat API returns answers grounded in Fabric IQ with Power BI citations, how well queries are attributed in a real tenant, the Foundry scoring path, and deployment of the Fabric app.
- Whether the v2 preview of the Evaluations CLI is published to npm.
- The contents of the architecture SVG.

## 8. Sources

- Microsoft 365 Copilot Chat API: [overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview), [chat operation](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat) (R1, R2)
- [Fabric IQ in Microsoft 365 Copilot Chat](https://learn.microsoft.com/en-us/fabric/iq/connectors/microsoft-365-copilot-overview) (R3)
- [Ask Copilot for data from semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-ask-data-question) (R4)
- [Fabric IQ MCP server](https://learn.microsoft.com/en-us/fabric/iq/connectors/fabric-iq-mcp) (R5)
- Microsoft 365 Copilot Evaluations CLI: [repository](https://github.com/microsoft/m365-copilot-eval), [overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview), [evaluators](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-evaluators), [upgrade to v2](https://raw.githubusercontent.com/microsoft/m365-copilot-eval/main/docs/upgrade-to-v2.md) (R6)
- [Agent evaluation overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluation-overview) (R7)
- [Semantic model operation logs](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/semantic-model-operations) (R8) and [workspace monitoring](https://learn.microsoft.com/en-us/fabric/fundamentals/workspace-monitoring-overview) (R9)
- Foundry: [custom evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/custom-evaluators) (R11), [cloud evaluation](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation) (R12), [agent evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators) (R13), [October 2026 update](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-october-2026/) (R14), [azure-ai-projects on PyPI](https://pypi.org/project/azure-ai-projects/) (R15)
- [Evaluate a Fabric data agent](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent) (R16)
- Chris Webb's BI Blog, unofficial: [queries run when the Copilot index is built](https://blog.crossjoin.co.uk/2025/11/02/monitoring-the-dax-queries-generated-when-the-power-bi-copilot-index-is-built/) (R18)
- Method: [Adding Error Bars to Evals](https://arxiv.org/abs/2411.00640), [pass^k](https://arxiv.org/abs/2406.12045), [validating an LLM judge](https://hamel.dev/blog/posts/llm-judge/) (R21)
- Microsoft Ignite 2026 session catalog, for example [BRK310](https://ignite.microsoft.com/en-US/sessions/BRK310) (R22)
