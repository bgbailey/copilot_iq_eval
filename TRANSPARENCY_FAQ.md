# Transparency & Limitations FAQ (`cfeval`)

This Responsible AI–style transparency note explains what `cfeval` measures, what it intentionally does **not** measure, and how to interpret evaluation results across Microsoft 365 Copilot Chat, Fabric IQ, Work IQ, and MCP agent targets.

---

## 1. What does `cfeval` measure?

`cfeval` evaluates **business-data grounding and answer fidelity** against a curated golden question suite (`version: 2`):

- **Value accuracy (`value` gate):** Deterministic numeric, unit-aware (`currency`, `percent`, `bps`, `count`, `hours`, `days`), structured (`ranked_list`, `set`, `table`, `record`), directional (`up` / `down` / `flat`), citation-only, and abstention checks against expected ground truth.
- **Artifact attribution (`artifact` gate):** Whether the surfaced citations (`attributions` / `artifacts` / tool calls) name the expected report, semantic model, or workplace document.
- **Authoritative model routing (`model` gate):** When engine-level telemetry is available, whether the semantic engine executed DAX/SQL against the certified semantic model and avoided known decoy or stale sandbox models.
- **Operational telemetry:** End-to-end turn latency (`p50` / `p95`), trial stability across repeated runs, and structured JSONL / Lakehouse audit logs.

## 2. What does `cfeval` NOT measure?

- **General conversational helpfulness, tone, or writing style** outside business grounding.
- **End-user satisfaction, adoption, or productivity ROI** in production workflows.
- **Row-level security (RLS) penetration testing or Entra permission auditing**—`cfeval` records outcomes under the delegated test identity you supply (`eval.tester@contoso.com`), not across every user role unless you run separate suites per persona.
- **Real-time production SLA monitoring**—`cfeval` is an offline/pre-deployment and scheduled regression harness, not an always-on APM agent.

---

## 3. Why do repeated runs vary, and how should I read `pass@k` vs `pass^k`?

Generative orchestration and tool selection are stochastic. A single `trials=1` pass can mask intermittent routing drift or overstate regressions. When `trials = k` (`k >= 3` recommended for release gates):

| Metric | Formula (conceptual) | Question Answered |
|---|---|---|
| **`pass@k`** | At least 1 of `k` trials passes | *Capability discovery:* Can the target answer and ground this question at all? |
| **`pass^k`** | All `k` of `k` trials pass (`p^k`) | *Operational reliability:* Can business users rely on consistent grounding every time they ask? |
| **Wilson 95% CI** | Exact binomial score interval on pass rate | How wide is statistical uncertainty given the size of the golden set (`N`)? |
| **Paired McNemar `p`-value** | Discordant pair test (`b` vs `c`) between two runs | Did a model/prompt/semantic-model change produce a statistically significant shift on the exact same questions? |

With an 8-question smoke suite (`contoso-smoke.yaml`), 95% confidence intervals are wide; use the 42-question `contoso.yaml` suite (or 40+ domain questions of your own) with `trials >= 3` before drawing release conclusions.

---

## 4. What are Routing Evidence Tiers?

Not every evaluation target exposes engine-side query execution logs. `cfeval` classifies every scored turn into an explicit `routing_evidence_tier` rather than conflating citation text with engine proof:

| Evidence Tier | Typical Target / Collector | What Is Proven |
|---|---|---|
| **`engine+citations`** | `copilot-chat` or `fabric-data-agent` + `kql` Workspace Monitoring | Both user-visible citation AND engine-side `SemanticModelLogs` execution (exact `DatasetId`, DAX query text, `DurationMs`, and decoy avoidance). |
| **`tool_call`** | `mcp-agent` | Structured MCP tool invocation arguments and tool return payloads captured directly in the agent loop, without separate Fabric KQL correlation. |
| **`citations-only`** | `copilot-chat` (`none` collector), `work-iq`, `transcript-import` | User-visible Graph/Copilot attributions (`webUrl` / title) match the expected artifact, **without** independent semantic-engine log verification. |
| **`none`** | Plain text transcripts without citation metadata | Only answer value / abstention can be verified deterministically. |

When `routing_evidence_tier` is `citations-only` or `none`, `model` gates that require engine telemetry report `not_applicable` / degraded confidence rather than claiming verified model routing.

---

## 5. Workspace Monitoring (`kql`) Latency and Correlation Caveats

- **Ingestion lag:** Fabric Workspace Monitoring writes `SemanticModelLogs` asynchronously to Eventhouse; events typically land within 30–180 seconds after a Copilot turn completes, and occasionally longer under cold Eventhouse state. `cfeval` polls within a configurable window (`correlation_lag_s`), after which unmatched turns fall back transparently to `citations-only`.
- **Shared-workspace concurrency:** Correlation matches `[started_utc - skew, ended_utc + lag]` plus user principal and model hints. Running concurrent interactive queries under the **same** test user (`eval.tester@contoso.com`) on the **same** semantic model during an evaluation window can introduce correlation ambiguity. Dedicated evaluation service/test accounts and quiet windows eliminate this risk.

---

## 6. Why are deterministic checks the default gate while LLM-as-judge is opt-in?

1. **Auditability:** Finance, sales, and operations stakeholders need exact reproducibility—`$12.84M` vs `$12.84M ± 0.5%` and exact artifact match—not an opaque rubric score that shifts across judge model versions.
2. **Judge bias & calibration:** LLM judges can reward verbose, confident prose even when a number is subtly wrong or drawn from a decoy model.
3. **Calibrated opt-in:** `cfeval` ships Azure AI Foundry / OpenAI judge evaluators (`Coherence`, `Fluency`, `Relevance`, `Groundedness`) as **advisory diagnostics** by default. Before enabling judge scores as a hard CI gate (`--gate-on-judge`), run `python -m cfeval calibrate-judge` against a human-labeled calibration file and verify **Cohen's kappa (`κ >= 0.70`)**.

---

## 7. Synthetic Data & Public Hygiene

All bundled golden suites (`contoso.yaml`, `contoso-smoke.yaml`, `contoso-work.yaml`), sample star-schema CSVs (`samples/contoso/`), and Work IQ documents (`samples/work-iq/`) depict **fictitious Contoso (`@contoso.com`)** operations. Never commit real customer transcripts, tenant GUIDs, user principal names, or bearer tokens to version control; use `.env` (gitignored) and run `python tools/check_public_wording.py` prior to publishing changes.
