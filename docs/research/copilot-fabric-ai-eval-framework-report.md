# Automated Evaluation of M365 Copilot → Fabric IQ Routing and Answer Accuracy: State of the Art (3 Nov 2026)

## Executive Summary

No single Microsoft product today proves, end-to-end and headlessly, that an M365 Copilot prompt was routed to a *specific* semantic model / Fabric data agent and returned a *specific* number. The pieces exist: (a) the **Fabric data agent SDK** evaluates the data agent layer directly (preview); (b) the **M365 Copilot Agent Evaluations CLI** (preview) drives deployed declarative agents through M365 Copilot and scores answers with ExactMatch/PartialMatch plus Foundry LLM judges, but exposes no documented tool-routing evaluator; (c) **Copilot Studio evaluation** has a "Tool use" grader and a REST API for CI; (d) **Foundry** evaluators/graders give deterministic + LLM scoring and CI with statistics, but Foundry's own tool evaluators flag the Fabric Data Agent tool as "limited support". Recommended: a Python harness (pytest + promptfoo or Foundry `evaluate`-style scorers) with deterministic numeric scorers, routing assertions from whichever surface exposes tool traces, repeated runs (pass^k), and a live DAX reference query as dynamic ground truth. **Overall confidence: MODERATE** (most components preview; routing-evidence surface in M365 Copilot unverified).

---

## 1. Microsoft Foundry evaluation

**Versions / status**
- `azure-ai-evaluation` latest **1.18.10 (2026-10-23)**; 1.18.9 (2026-10-14), 1.18.8 (2026-10-09) — [piwheels](https://www.piwheels.org/project/azure-ai-evaluation/), [PyPI RSS](https://pypi.org/rss/project/azure-ai-evaluation/releases.xml). 1.18.8 fixed "multi-turn evaluations failing during Azure OpenAI result conversion" — [Azure SDK Oct 2026](https://azure.github.io/azure-sdk/releases/2026-10/python.html). Oct 10 2026 commit: "Export result status and pass state to App Insights" — [GitHub history](https://github.com/Azure/azure-sdk-for-python/commits/main/sdk/evaluation).
- `azure-ai-projects` 2.8.0 (Oct 2026): "Agent Optimization APIs are now GA… Data generation job APIs are now GA" — [Azure SDK Oct 2026](https://azure.github.io/azure-sdk/releases/2026-10/python.html).

**Agent evaluators** ([Learn, updated 2026-09-30](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators))
- System: Task Completion (preview), Customer Satisfaction (preview), Task Adherence (preview), **Task Navigation Efficiency**, Intent Resolution (preview). Process: **Tool Call Accuracy, Tool Selection, Tool Input Accuracy, Tool Output Utilization, Tool Call Success**. Composites (preview): `builtin.output_quality`, `builtin.tool_use_quality` (one judge call each). Quality Grader "is deprecated and can no longer be run".
- Task Navigation Efficiency is deterministic against ground-truth tool sequences with `matching_mode` `exact_match | in_order_match | any_order_match`; returns pass/fail plus precision/recall/F1. **Best built-in fit for "routed to tool X".**
- **Critical caveat:** "Avoid using tool_call_accuracy, tool input accuracy, tool_output_utilization, tool_call_success, or groundedness evaluators if your agent conversation includes calls to these tools: … **Fabric Data Agent**…" (same page). Confidence HIGH.
- Judge: "Use a model from the GPT-5.6 family as the LLM judge for composite evaluators… use gpt-5.6-luna" for lowest cost (same page).

**Similarity / exact-match** ([Learn](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/textual-similarity-evaluators)): `builtin.similarity` (1–5, default 3), `f1_score`, `bleu_score`, `gleu_score`, `rouge_score`, `meteor_score`; "All six evaluators are generally available (GA)."

**OpenAI-Evals-compatible graders** ([Learn, 2026-04-07](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/azure-openai-graders)): `label_model`, `score_model` (`pass_threshold`, `range`), `string_check` (`eq | ne | like | ilike`), `text_similarity` (`fuzzy_match, bleu, gleu, meteor, cosine, rouge_1…5, rouge_l`). "Azure OpenAI graders use the OpenAI Evals API and are configured differently from built-in evaluators."

**Custom evaluators** (preview) ([Learn](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/custom-evaluators)): code-based (Python `grade()`), prompt-based, endpoint-based. Sandbox: "<256 KB", "2 minutes per grading call", "**No network access**", 2 GB RAM; numpy/pandas/rapidfuzz/deepdiff/pydantic available. Exceptions score 0.0. Implication: numeric-tolerance scorer can run in-cloud; a *live DAX reference query* cannot (no network) — compute ground truth before upload or use an endpoint-based evaluator.

**Input format / APIs**
- Cloud: OpenAI-style `openai_client.evals.create(... testing_criteria ...)` + `evals.runs.create(data_source=...)`; data mapping via `{{item.field}}`, `{{sample.output_text}}`, `{{sample.output_items}}` — [agent evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators), [targets](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-targets). Targets: deployed model, prompt agent, or hosted agent; "A JSONL or CSV dataset of input queries."
- Local `evaluate()` with dataset or target callable is documented only on the **classic** page ([Foundry classic](https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/develop/evaluate-sdk)) — WEAK for "current" guidance; I could not fetch the new-portal equivalent. **[unverified: whether local `evaluate(target=…, evaluator_config column_mapping)` remains the recommended path vs. cloud Evals API]**.
- Bring-your-own traces/responses: evaluate by response ID or OTel traces in App Insights (preview) — [Learn](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-deployed-interactions).

**Continuous eval / tracing**: Agent Monitoring Dashboard with "Recurring evaluations (preview)", red-team scans, alerts; data in App Insights — [Learn](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard). Tracing "generally available for prompt and hosted agents. Workflow and external agents are in preview"; OTel GenAI semantic conventions; stored in Application Insights — [Learn](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept).

**CI**: `microsoft/ai-agent-evals` GitHub Action (preview) — inputs `azure-ai-project-endpoint`, `deployment-name`, `data-path`, `agent-ids` (`name:version`), `baseline-agent-id`; JSON data file with `evaluators`, `data`, `openai_graders`, `evaluator_parameters`, `data_mapping`; "results include confidence intervals and test for statistical significance" — [Learn](https://learn.microsoft.com/en-us/azure/foundry/how-to/evaluation-github-action), [repo](https://github.com/microsoft/ai-agent-evals). **Limitation:** it invokes *Foundry agents*, not M365 Copilot or Fabric data agents.

**Cost/limits**: LLM-judge token cost per row; composites exist "to reduce the cost and latency" (agent evaluators page). No published per-run quota found **[gap]**.

## 2. Copilot Studio Agent Evaluation and Copilot Studio Kit

**Built-in evaluation** ([single response, 2026-10-06](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-create); [conversational](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-multi-turn))
- Test methods: General quality (0–100%), Content safety, **Compare meaning** (pass score), **Tool use** ("Whether the test case used all or any the expected resources", pass/fail, "Expected capabilities"), Keyword match, Text similarity, **Exact match**, Custom (labels).
- Limits: single-response set "up to 100 test cases"; conversational "up to 20"; each question ≤1,000 chars; results retained "89 days" — export to CSV.
- CSV import: headings "Question", "Expected response" (.csv or .txt).
- Auth: "Automated testing uses the authentication of the currently signed-in user"; to test another persona "sign out, sign in by using that user's account". New experience: "only support agents set to use No authentication or Authenticate with Microsoft" ([Learn, 2026-10-21](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-intro)) — production-ready preview; consumes credits.
- **Programmatic API**: Power Platform REST `…/api/makerevaluation/testsets/{id}/run?api-version=2024-10-01`, `testruns`, `testruns/{id}`; optional `mcsConnectionId` for authenticated runs; per-test `metricsResults` — [Learn, 2026-10-11](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api). Requires **delegated** user token (`CopilotStudio.MakerOperations.Read/ReadWrite`); connection "requires interactive OAuth and cannot be created programmatically" — [EvalGateADO sample](https://microsoft.github.io/CopilotStudioSamples/testing/evaluation/EvalGateADO/). Test sets must be authored in Copilot Studio first.

**Copilot Studio Kit / "Copilot Agent Kit"** ([Learn, 2026-07-16](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-configure-tests))
- Types: Response Match (equals/contains/…), Attachments (incl. "AI Validation"), Topic Match, Generative Answers (LLM; needs AI Builder enrichment), Multi-turn (ordered, critical/non-critical children), **Plan Validation** ("validate that the dynamic plan… includes the expected tools"; comma-separated expected tools + Pass Threshold %; "a deterministic test"; "Extra tools in the dynamic plan don't affect the test result").
- Pipelines: Power Platform Pipelines-based automated testing — [AUTOMATED_TESTING.md](https://github.com/microsoft/Power-CAT-Copilot-Studio-Kit/blob/main/AUTOMATED_TESTING.md); Agent Review Pipeline GitHub Action — [Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-agent-review-pipeline).
- Fit: strongest native **routing assertion** (Plan Validation) — but only for Copilot Studio agents, not M365 Copilot orchestration.

## 3. Fabric data agent SDK evaluation

([Learn, updated 2026-09-01](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent); [blog](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/secure-data-streaming-custom-ca-and-mtls-in-fabric-eventstream-connectors-previe/5172047); [sample notebook](https://github.com/microsoft/fabric-samples/blob/main/docs-samples/data-science/data-agent-sdk/Fabric-DataAgent-Evaluation-sample.ipynb))
- Package `fabric-data-agent-sdk` **0.1.34a0, pre-release** — [PyPI](https://pypi.org/project/fabric-data-agent-sdk/). Feature is **preview**; needs F2+ or P1+.
- `evaluate_data_agent(df, data_agent_name, workspace_name=None, table_name="evaluation_output", data_agent_stage="production"|"sandbox", critic_prompt=None)` → `evaluation_id`. Input DataFrame columns `question`, `expected_answer`.
- Output tables: `<table_name>` (summary) and `<table_name>_steps` ("detailed reasoning and step-by-step execution").
- `get_evaluation_summary(table_name)` → counts "correct, incorrect, or unclear"; `get_evaluation_details(evaluation_id, table_name, get_all_rows=False, verbose=True)` → actual answers, match flag, thread link (`message_url`) "visible only to the user who ran the evaluation".
- `critic_prompt` must contain `{query}`, `{expected_answer}`, `{actual_answer}`; judge answers "yes" if equivalent. Numeric tolerance is **not a parameter** — encode it in the critic prompt (e.g., "treat values equal if |a−e|/|e| ≤ 0.5% after removing currency/thousand separators") **[recommendation]**.
- Headless: "FabricOpenAIResponses and FabricOpenAI accept an explicit Azure TokenCredential and workspace for ordinary Python processes" (PyPI) — enables GitHub Actions; SDK moved from Assistants API to Responses API / MCP endpoint `https://api.fabric.microsoft.com/v1/mcp/workspaces/{WorkspaceId}/dataagents/{DataAgentId}/agent` — [Learn](https://learn.microsoft.com/en-us/fabric/data-science/fabric-data-agent-sdk). **[unverified: whether `evaluate_data_agent` itself runs outside a Fabric notebook]** — PyPI says "SemPy and the notebook plugin remain installed for existing management, datasource and evaluation functionality".

**Prep data for AI guidance** ([Learn](https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices))
- "the DAX generation tool used by data agent relies solely on the semantic model's metadata and Prep for AI configurations. The DAX generation tool **ignores any instructions you add at the data agent level**".
- Components: AI data schema, verified answers (stored at model level; matched "exact or semantically similar" before generation), AI instructions. Q&A retiring Dec 2026 affects instance-value indexing.
- Checklist: "Select the same tables in Data Agent that are defined in Prep for AI > AI Data Schema"; "Add routing instructions for multiple semantic models" — [fabric-toolbox](https://github.com/microsoft/fabric-toolbox/blob/main/samples/data_agent_checklist_notebooks/Semantic%20Model%20Data%20Agent%20Checklist.md).

## 4. Open-source frameworks

Facts:
- **promptfoo**: Python provider `call_api(prompt, options, context)` (any REST/Graph call); `options.repeat` per test, "add --no-cache when every run must call the provider"; Python assertions returning `GradingResult` with `named_scores`; CSV/XLSX tests — [docs](https://www.promptfoo.dev/docs/configuration/test-cases/), [python provider](https://www.promptfoo.dev/docs/providers/python/). Node runtime required **[note]**.
- **DeepEval** v4.0.3 (2026-05-21, per third-party snapshot — WEAK) — pytest-native; `ToolCorrectnessMetric` with `expected_tools`, `should_exact_match`, `should_consider_ordering` — [docs](https://deepeval.com/docs/metrics-tool-correctness).
- **MLflow GenAI**: `mlflow.genai.evaluate(data, predict_fn, scorers)`, records "traces and feedback" — [Azure Databricks Learn](https://learn.microsoft.com/en-us/azure/databricks/mlflow3/genai/eval-monitor/concepts/eval-harness).
- **Inspect AI** 0.3.287 (2026-10-31); scorers `match(numeric=True)`, `pattern`, `exact`, `model_graded_fact`; epochs + reducers — [changelog](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/CHANGELOG.md), [scorer ref](https://vladmesh.github.io/inspect_ai/reference/inspect_ai.scorer.html).
- **Langfuse**: Experiments + "Langfuse Experiments GitHub Action. Gate PRs on regressions" (Apr 2026); Code Evaluators (May 2026) — [Apr](https://langfuse.com/blog/2026-04-30-langfuse-april-update), [May](https://langfuse.com/blog/2026-05-31-langfuse-may-update).
- Ragas, Arize Phoenix, OpenAI Evals: current versions **not verified this session**; Phoenix is OTel/OpenInference-native (secondary source, [QASkills](https://qaskills.sh/blog/langfuse-vs-arize-phoenix)).

**Comparison (1–5; 5 = best fit; scores are analyst judgement [hypothesis] grounded in the facts above)**

| Framework | Numeric exact/tolerance | Tool-routing assertion | Repeated-run stats | Python/MS-stack fit | CI gating | Reporting UI |
|---|---|---|---|---|---|---|
| Foundry evaluators + Evals API / ai-agent-evals | 4 (string_check, code grader) | 3 (Task Nav Efficiency; Fabric Data Agent tool "limited support") | 3 (CI + significance tests) | 5 | 4 (Foundry agents only) | 4 (Foundry portal/App Insights) |
| promptfoo | 5 (python/JS asserts) | 4 (assert on provider metadata) | 4 (`repeat`) | 3 (Node CLI, Python hooks) | 5 | 4 (local web viewer) |
| DeepEval | 4 (custom metric) | 5 (ToolCorrectness) | 3 | 4 (pytest) | 5 | 3 (cloud UI paid) |
| Inspect AI | 5 (`match(numeric)`) | 3 (custom scorer) | 5 (epochs/reducers/stderr) | 4 | 4 | 4 (inspect view) |
| MLflow GenAI | 4 (custom scorer) | 4 (trace-based scorers) | 3 | 4 (Fabric has MLflow) | 3 | 4 |
| Ragas | 2 | 3 | 2 | 4 | 3 | 2 |
| OpenAI Evals (graders) | 4 | 2 | 2 | 3 | 3 | 3 |
| Langfuse / Phoenix (trace + eval) | 3 (code evaluators) | 4 (trace inspection) | 3 | 4 (OTel) | 4 (Langfuse GH Action) | 5 |

## 5. NL-to-query evaluation methodology

- **Execution accuracy over exact match**: "A text-to-SQL eval runs the generated query against a real database and checks the rows it returns, not the query text"; row-set equivalence avoids penalising ORDER BY / column-order differences — [aievals.co](https://www.aievals.co/task-types/text-to-sql) (secondary; consistent with BIRD design). BIRD human EX 92.96% — [same], corroborated by [IoT Digital Twin PLM](https://iotdigitaltwinplm.com/text-to-sql-llm-benchmark-accuracy-latency-2026/). Enterprise drop-off (Spider 2.0 ~21–60%) — [colrows](https://colrows.com/blogs/text-to-sql-benchmark/), [dreaming.press](https://dreaming.press/posts/text-to-sql-accuracy-spider-vs-bird.html). MODERATE.
- **NL2DAX**: Power BI team built "an expanding suite of benchmark datasets… incorporating diverse modeling features, time-intelligence calculations, and complex relationship graphs", graded for "syntactic validity and semantic accuracy"; non-reasoning models showed "unpredictability" — [Jeffrey Wang, pbidax, 2025-05-14](https://pbidax.wordpress.com/2025/05/14/llms-and-dax-where-things-stand-today/). No public Microsoft NL2DAX benchmark dataset found **[gap]**.
- **Applying to this scenario [recommendation]**: you rarely get the generated DAX from M365 Copilot, so grade the *answer value* (execution-style) against a reference DAX result; where the data agent exposes steps (`_steps` table / thread), also compare generated DAX result-sets.
- **Normalization [recommendation]**: parse `$1.2M`, `1,234,567.89`, `12.5%`, `(1,234)` → Decimal with unit scaling (K/M/B), locale separators, sign; compare with `abs_tol` + `rel_tol` chosen per measure; record the rounding the agent applied (a "$1.2M" answer can only be checked to ±0.05M).
- **Extraction [recommendation]**: prefer structured output (ask the agent for a JSON/explicit value line in the eval prompt only if that doesn't distort production behaviour), then regex over the answer, then an LLM extractor (`score_model`/`label_model`) as fallback, logging which path matched.
- **Nondeterminism**: pass^k = probability all k trials succeed; "measures the consistency… across k i.i.d. trials"; gpt-4o retail pass^8 < 25% vs <50% pass^1 — [τ-bench paper](https://arxiv.org/pdf/2406.12045), [BenchLM](https://benchlm.ai/benchmarks/tau-bench). Report pass@1 (mean), pass^k (k=3–5), and consistency rate (identical value across runs). HIGH.
- **Golden set design [recommendation]**: per measure: canonical + 3–5 paraphrases; time-intelligence (YTD, prior period, fiscal vs calendar); disambiguation pairs where two models share similar measures (assert routing to the right model — mirror fabric-toolbox "routing instructions"); ambiguous prompts with expected *clarification* label; out-of-scope/negatives with expected refusal; RLS personas run under separate identities (Copilot Studio requires signing in as that user; Fabric threads are per-identity).
- **Dynamic ground truth [recommendation]**: execute reference DAX (e.g., via `executeQueries` / semantic link) at eval time in the same run, store value + model refresh timestamp; keep a frozen snapshot set for regression, and a dynamic set for freshness. Foundry code graders have no network, so resolve ground truth *before* grading.
- **Gating [hypothesis — standard statistics]**: with n=30 and 27 passes, the 95% Wilson interval is roughly 74–97%, so a single-run 90% gate is noisy; gate on (a) zero failures on a small "critical" set with k≥3 repeats, and (b) non-regression vs baseline using a paired test (McNemar) or the significance output of `ai-agent-evals`.

## 6. Microsoft guidance and samples for M365 Copilot agents

- **Agent evaluation overview** (concepts: test case, assertion, quality signal, graders incl. "Tool verification – Validate API or tool execution") — [Learn](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluation-overview). Start with **Work IQ Dev Tools** `wiqd agent eval` for declarative agents.
- **Agent Evaluations CLI** `@microsoft/m365-copilot-eval` (public preview announced 2026-05-08): "sends prompts to a deployed agent, captures responses, and scores them"; HTML/JSON/CSV reports; for CI/CD — [devblog](https://devblogs.microsoft.com/microsoft365dev/announcing-the-public-preview-of-the-microsoft-365-copilot-agent-evaluations-tool/), [overview, 2026-09-30](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview). Evaluators: Relevance, Coherence, Groundedness, Similarity, RetrievalQuery, RetrievalResult, Citations, **ExactMatch**, **PartialMatch** — [evaluators ref](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-evaluators). Dataset schema 1.6.0 with `testId`, `category` (e.g. "tool-usage"), per-item evaluators, multi-turn — [schema](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-create-tests). Requires M365 Copilot licence, Node 24.12+, admin consent, consumes Copilot credits, Foundry project (default judge `gpt-5-mini`). **No documented evaluator that asserts which Fabric data agent/semantic model was invoked [gap].**
- Samples: `microsoft/CopilotStudioSamples` EvalGateADO; `microsoft/fabric-samples` data agent evaluation notebook; `microsoft/fabric-toolbox` checklist; `microsoft/m365-copilot-eval`; `microsoft/ai-agent-evals` (all cited above). No Azure-Samples reference architecture specifically for evaluating M365 Copilot → Fabric data agent routing was found **[gap]**.

---

## Recommended eval stack for this scenario

**Primary framework**: Python + **pytest** orchestration with **promptfoo** (or Inspect AI if the team prefers pure Python) as the runner; scorers written once as plain Python functions and reused as Foundry code-based graders. Rationale: target is a custom REST surface (not a Foundry agent), needs deterministic numeric checks and repeats — Foundry's GitHub Action and tool evaluators don't natively cover Fabric Data Agent calls.

**Layered targets (run all three)**
1. **L1 – Data agent direct** (Fabric notebook, nightly): `evaluate_data_agent(..., data_agent_stage="sandbox"/"production", critic_prompt=<numeric-tolerance prompt>)`; plus headless `FabricOpenAIResponses` calls from GitHub Actions for deterministic scoring. Validates model + Prep-for-AI quality.
2. **L2 – Declarative agent through M365 Copilot** (CI): `m365-copilot-eval` / `wiqd agent eval` with ExactMatch/PartialMatch + your own post-processor on its JSON report for numeric tolerance.
3. **L3 – Routing**: if a Copilot Studio agent fronts the data agent, use Copilot Studio **Tool use** method via REST API or Kit **Plan Validation**; otherwise derive routing from data agent thread/steps (`_steps` table, `message_url`) and from which agent's thread logged the question in the eval window **[hypothesis]**.

**Scorers to implement**: `numeric_match(abs_tol, rel_tol, unit_scaling)`; `value_extractor` (structured → regex → LLM); `routing_match(expected_agent|model, mode=exact/any)`; `clarification_expected`; `refusal_expected`; `freshness_ok` (ground truth from live reference DAX); `consistency@k` and `pass^k`; optional LLM `score_model` for answer completeness.

**Logging/visualization**: write per-run JSONL (prompt, run_idx, raw answer, extracted value, expected, tolerance, routing evidence, latency, model refresh time) to a **Fabric Lakehouse Delta table** → Power BI report (natural for this customer); mirror summary into Foundry Evals/App Insights for trend + alerts; promptfoo/Inspect viewer for drill-down.

**CI**: GitHub Actions with OIDC → Entra; nightly schedule + PR trigger; gate = 100% on critical set at k=3 and no significant regression vs baseline; publish JUnit for PR annotations. Note Copilot Studio eval API needs a delegated user token (refresh-token pattern in EvalGateADO) and RLS personas need dedicated test identities.

## Conclusion

The reason no turnkey solution exists is structural: M365 Copilot is a closed orchestrator, so routing evidence is only observable at the *downstream* agent (Copilot Studio plan/tool logs or Fabric data agent threads), while numeric correctness is best judged deterministically against a live reference query rather than by an LLM judge. Microsoft's own tools split along these seams (Fabric SDK for data-agent accuracy, M365 CLI for end-to-end answers, Copilot Studio for tool-use), and Foundry's tool evaluators explicitly don't support Fabric Data Agent calls. A thin Python harness that unifies them — deterministic numeric scorers, pass^k repeats, live ground truth, and Lakehouse/Power BI reporting — gives the customer the repeatable proof they want while reusing Microsoft components where they are strongest.

## Limitations & Residual Risks
- Pre-mortem: (1) most components are preview and APIs shifted in 2026 (Fabric Assistants→Responses; Copilot Studio new experience) — pin versions; (2) M365 Copilot may not expose any per-call routing signal, making L2 routing unprovable except by answer value; (3) LLM-judge drift if the critic prompt is the only gate.
- Unverified: local `azure-ai-evaluation.evaluate()` status in new Foundry; Ragas/Phoenix/OpenAI Evals versions; whether a Fabric data agent appears as a selectable "expected capability" in Copilot Studio Tool use; whether `evaluate_data_agent` runs outside Fabric notebooks.

## Open uncertainties
1. Does M365 Copilot (or Copilot APIs) expose which declarative agent / Fabric data agent / semantic model handled a turn? (covered by sibling research; not found here)
2. Can Copilot Studio Tool use / Kit Plan Validation name a Fabric data agent (connected agent or MCP tool) as an expected tool?
3. Cost: Copilot credits per CLI prompt and Copilot Studio eval credits per run — no rate card found.
4. Q&A retirement (Dec 2026) impact on instance-value indexing and therefore answer stability.

## Sources
1. [azure-ai-evaluation piwheels](https://www.piwheels.org/project/azure-ai-evaluation/) - 2026-10-23
2. [Azure SDK for Python Oct 2026](https://azure.github.io/azure-sdk/releases/2026-10/python.html) - Microsoft
3. [azure-sdk-for-python evaluation history](https://github.com/Azure/azure-sdk-for-python/commits/main/sdk/evaluation) - GitHub
4. [Foundry agent evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators) - Learn, 2026-09-30
5. [Foundry Azure OpenAI graders](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/azure-openai-graders) - Learn, 2026-04-07
6. [Foundry custom evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/custom-evaluators) - Learn
7. [Foundry textual similarity evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/textual-similarity-evaluators) - Learn
8. [Foundry GitHub Action](https://learn.microsoft.com/en-us/azure/foundry/how-to/evaluation-github-action) - Learn
9. [microsoft/ai-agent-evals](https://github.com/microsoft/ai-agent-evals) - GitHub
10. [Foundry cloud evaluation targets](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-targets) - Learn
11. [Foundry deployed interactions eval](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-deployed-interactions) - Learn
12. [Foundry agent tracing](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept) - Learn
13. [Foundry monitoring dashboard](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard) - Learn
14. [Foundry classic local evaluate SDK](https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/develop/evaluate-sdk) - Learn
15. [Fabric: Evaluate your data agent](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent) - Learn, 2026-09-01
16. [Fabric blog: evaluate data agents with SDK](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/secure-data-streaming-custom-ca-and-mtls-in-fabric-eventstream-connectors-previe/5172047) - Microsoft
17. [fabric-data-agent-sdk PyPI](https://pypi.org/project/fabric-data-agent-sdk/) - 0.1.34a0
18. [Fabric data agent Python SDK](https://learn.microsoft.com/en-us/fabric/data-science/fabric-data-agent-sdk) - Learn
19. [Semantic model best practices for data agent](https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices) - Learn
20. [fabric-toolbox Semantic Model Data Agent Checklist](https://github.com/microsoft/fabric-toolbox/blob/main/samples/data_agent_checklist_notebooks/Semantic%20Model%20Data%20Agent%20Checklist.md) - GitHub
21. [fabric-samples data agent evaluation notebook](https://github.com/microsoft/fabric-samples/blob/main/docs-samples/data-science/data-agent-sdk/Fabric-DataAgent-Evaluation-sample.ipynb) - GitHub
22. [Copilot Studio single response test set](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-create) - Learn, 2026-10-06
23. [Copilot Studio conversational test set](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-multi-turn) - Learn
24. [Copilot Studio evaluate an agent (new experience)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-intro) - Learn, 2026-10-21
25. [Copilot Studio evaluation REST API](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api) - Learn, 2026-10-11
26. [Copilot Agent Kit configure tests](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-configure-tests) - Learn, 2026-07-16
27. [EvalGateADO sample](https://microsoft.github.io/CopilotStudioSamples/testing/evaluation/EvalGateADO/) - Microsoft
28. [Power CAT Kit AUTOMATED_TESTING](https://github.com/microsoft/Power-CAT-Copilot-Studio-Kit/blob/main/AUTOMATED_TESTING.md) - GitHub
29. [Agent Review Pipeline](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-agent-review-pipeline) - Learn
30. [M365 agent evaluation overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluation-overview) - Learn
31. [Agent Evaluations CLI overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview) - Learn, 2026-09-30
32. [Agent Evaluations CLI evaluators](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-evaluators) - Learn
33. [Agent Evaluations CLI dataset schema](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-create-tests) - Learn
34. [M365 Agent Evaluations public preview](https://devblogs.microsoft.com/microsoft365dev/announcing-the-public-preview-of-the-microsoft-365-copilot-agent-evaluations-tool/) - devblog, 2026-05-08
35. [promptfoo test cases](https://www.promptfoo.dev/docs/configuration/test-cases/) / [python provider](https://www.promptfoo.dev/docs/providers/python/)
36. [DeepEval Tool Correctness](https://deepeval.com/docs/metrics-tool-correctness)
37. [MLflow genai.evaluate](https://learn.microsoft.com/en-us/azure/databricks/mlflow3/genai/eval-monitor/concepts/eval-harness) - Azure Databricks
38. [Inspect AI changelog](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/CHANGELOG.md) / [scorers](https://vladmesh.github.io/inspect_ai/reference/inspect_ai.scorer.html)
39. [Langfuse April 2026](https://langfuse.com/blog/2026-04-30-langfuse-april-update) / [May 2026](https://langfuse.com/blog/2026-05-31-langfuse-may-update)
40. [τ-bench paper](https://arxiv.org/pdf/2406.12045) / [BenchLM τ-bench](https://benchlm.ai/benchmarks/tau-bench)
41. [aievals.co text-to-SQL](https://www.aievals.co/task-types/text-to-sql); [colrows benchmark](https://colrows.com/blogs/text-to-sql-benchmark/)
42. [pbidax: LLMs and DAX](https://pbidax.wordpress.com/2025/05/14/llms-and-dax-where-things-stand-today/) - Jeffrey Wang, 2025-05-14
