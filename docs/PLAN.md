# Copilot × IQ evaluation accelerator — public-readiness plan

| | |
|---|---|
| Repository | `bgbailey/copilot_iq_eval` (baseline: commit `a9b0d39`, 6 Nov 2026 UTC) |
| Plan version | 1.0 — 13 Nov 2026 |
| Goal | Take the repository from a lean personal demo to a professional public accelerator that customers and technical teams can adopt to evaluate Microsoft 365 Copilot answers over Microsoft IQ sources, starting with Fabric IQ |
| Builder | GitHub Copilot (cloud agent on issues, or agent mode in the IDE). One work item per pull request |
| Reviewer | Repository maintainer |
| Source of facts | The repository at the baseline commit, an offline run of its quickstart and CI steps, and public documentation checked on 13 Nov 2026 (section 12). Nothing here depends on private tenant data |

---

## 1. How to use this plan with GitHub Copilot

1. Commit this file as `docs/PLAN.md`.
2. Do work item **M0-00** first. It gives the Copilot cloud agent a working environment and replaces the current instructions, which forbid tests.
3. Create one GitHub issue per work item in section 7. Title: `<ID> · <title>`. Body: the item text, unchanged. Labels: `milestone:M0` to `milestone:M4`, `type:agent` or `type:manual`, and one `area:*` label.
4. Assign issues to Copilot in dependency order. One issue produces one pull request. If a pull request would exceed about 600 changed lines, split the item and say so in the pull request.
5. Items labelled `type:manual` need a person with repository-admin or tenant access. Copilot must not attempt them.
6. Ground rules for every agent session (repeated in `AGENTS.md`, section 8.2):
   - **Offline only.** No call to Microsoft Graph, Fabric, Power BI or Microsoft Foundry from CI or an agent session. Use the simulated tenant, fakes and recorded fixtures.
   - **Do not invent service contracts.** If a field, endpoint or permission is not in the repository or in a document cited in section 12, add `TODO(verify-live)` plus a skipped live test, and state the assumption in the pull request.
   - **Synthetic data only.** Contoso names. No tenant IDs, user names, secrets or real answers.
   - **Evidence integrity.** `ERROR` and `INCONCLUSIVE` never become `PASS`. A missing remote score is never replaced by a local one.

---

## 2. Baseline: what the repository is today

Verified at commit `a9b0d39`.

| Area | State |
|---|---|
| Purpose | Asks Microsoft 365 Copilot Chat a golden set of business questions through the Microsoft Graph Copilot Chat API, reads citations, captures the DAX that ran from Fabric workspace monitoring, scores value, cited artifact and queried semantic model, and writes telemetry to a Fabric Eventhouse. A Fabric app shows the results |
| Code | 28 Python files, about 4,800 lines, 288 functions, no type hints, docstrings on 19% of functions. Scorecard app: about 1,460 lines of TypeScript |
| Works today | `python -m cfeval run --mock --option both` completes offline. The three CI checks (offline smoke, generated-file drift, app typecheck and build) pass, and CI is green on the baseline commit |
| Tests | None. `CONTRIBUTING.md` and `.github/copilot-instructions.md` forbid adding a test framework |
| History | 2 commits, no tags, no releases |
| Repository settings | Public, MIT license. No description or topics. Issues are disabled. No issue templates, `CODEOWNERS`, `CHANGELOG.md` or Dependabot configuration |

### 2.1 What to keep

These are the strengths of the design. No work item may weaken them.

- **Evidence triangulation.** Three independent signals per answer: the value against a reference DAX result, the citations, and the engine query log.
- **Deterministic gates.** Code decides the verdict. The judge model adds context and does not gate by default.
- **Honest status semantics.** Missing or unsettled evidence is `INCONCLUSIVE`; a failed call is `ERROR`; neither is ever counted as a pass.
- **Offline simulation.** A seeded simulated tenant with a simulated clock exercises the whole pipeline with no sign-in.
- **One schema source.** `src/cfeval/schema.py` generates the KQL setup script, the TypeScript contract and the connector entities, and CI fails on drift.
- **Identity checks.** Acquired tokens are checked for tenant, audience, user and scopes before use.
- **A local record of every run.** JSONL files are always written, whatever happens to the remote sink.
- **Append-only results with latest-row views.** Rescoring appends rows; the KQL functions and the app read the latest result for each ask and scoring backend.

### 2.2 What must change

Appendix A lists 25 findings with evidence. The five that matter most:

1. No automated tests, by policy (F-01).
2. The value check misgrades common answer shapes in both directions (F-02, F-03).
3. Without workspace monitoring, no answer can pass (F-04).
4. One way to reach Copilot, through a preview API (F-05).
5. Single-shot runs on eight questions, with an uncalibrated judge (F-06, F-07).

---

## 3. Target state

**Positioning.** An open, evidence-based harness that tests whether Microsoft 365 Copilot, and other agents, answer business-data questions from the right governed source with the right result. It complements Microsoft's own evaluation tools. As documented on 13 Nov 2026, those tools do not offer three things for analytics questions asked of Microsoft 365 Copilot: ground truth read live from the semantic model, numeric scoring with tolerances, and engine-level evidence of which semantic model was queried (section 12, R6, R12 and R16).

### 3.1 Release criteria for v1.0.0

| # | Criterion | Measured by |
|---|---|---|
| 1 | A newcomer gets a scored offline run and a readable report in under five minutes on Windows, macOS and Linux | Quickstart test in CI on Python 3.10 to 3.13 |
| 2 | A practitioner completes a live run in a demo tenant from the docs alone, with or without workspace monitoring | M4-02 validation record |
| 3 | Every verdict is explainable: evidence, extraction method, tolerance applied, judge version | Fields present in `EvalResult` and the report |
| 4 | Results carry statistics: repeats, pass^k, confidence intervals, comparison with a baseline, a CI gate | `cfeval compare`, JUnit output, documented exit codes |
| 5 | Scoring is tested: at least 85% line coverage on scoring, evidence and statistics modules; the grader corpus shows no false pass and at most 5% false fail | Coverage report, `tests/data/value_cases.jsonl` |
| 6 | Supply chain baseline: code scanning clean, dependency updates on, actions pinned, release artifacts with SBOM and provenance | Workflows in `.github/workflows/` |
| 7 | Documentation covers quickstart, concepts, how-to, reference and responsible use, with no demo-specific wording and no broken links | Wording check and link check in CI |
| 8 | Interoperability: import and export with the Microsoft 365 Copilot Evaluations CLI document format, and at least two targets beyond the Graph Chat API | Contract tests |
| 9 | Governance: issues on, templates, `CODEOWNERS`, `CHANGELOG.md`, semantic versioning, named maintainers | Repository settings and files |

### 3.2 Non-goals

- A hosted or production test platform.
- UI automation of Copilot.
- Replacing Microsoft's evaluators. The accelerator interoperates with them.
- Storing customer data, tenant identifiers or real answers in the repository.

---

## 4. Design changes

### 4.1 Layers and interfaces

```
golden cases ─▶ Target (system under test) ─▶ ask record: answer, citations, timings
                   │
                   ├─▶ Evidence sources: engine query log · tool trace · self-report
                   ▼
              Scorers (deterministic) + Judge (calibrated, optional)
                   ▼
              Gate policy ─▶ verdict per attempt ─▶ statistics per case and per run
                   ▼
              Sinks: JSONL (always) · Eventhouse · HTML and JUnit · OpenTelemetry (optional)
```

Introduce these protocols in `src/cfeval/interfaces.py` and move existing code behind them without changing behaviour:

```python
class Target(Protocol):
    name: str                                   # for example "m365-copilot-chat-graph"
    def ask(self, case: Case, persona: Persona) -> AskRecord: ...

class EvidenceSource(Protocol):
    kind: str                                   # "engine_query" | "tool_call" | "self_report"
    def collect(self, asks: Sequence[AskRecord]) -> Mapping[str, Evidence]: ...

class Scorer(Protocol):
    check: str                                  # "value" | "artifact" | "model" | ...
    def score(self, case: Case, ask: AskRecord, evidence: Evidence | None) -> CheckResult: ...
```

### 4.2 Targets

| Target id | What it drives | In this plan | Notes |
|---|---|---|---|
| `m365-copilot-chat-graph` | Microsoft 365 Copilot Chat through the Microsoft Graph Copilot Chat API | Exists; refactor behind `Target` | The API is in preview under `/beta`, delegated only. Microsoft documents enterprise-search and web grounding for it. Treat Fabric IQ answering through it as observed behaviour that each tenant must confirm |
| `simulated` | The built-in simulated tenant | Exists | Offline demos and tests |
| `import` | A transcript you already have: question, answer, citations, user, timestamps | New, M3-01 | Scores answers collected by hand in the Copilot UI or by another tool |
| Evaluations CLI interop | Runs executed by Microsoft's `runevals` CLI | New, M3-02 | File-based: export cases, import results. No runtime dependency |
| `fabric-iq-mcp-reference` | A minimal reference agent that calls the Fabric IQ MCP server | New, M3-03 | Control arm: separates semantic-model readiness from Copilot routing |
| `fabric-data-agent` | A published Fabric data agent | Optional, M3-04 | Separate extra and environment |

### 4.3 Golden set schema v2

CSV stays supported for simple numeric sets. YAML becomes the full format. The `intent` block mirrors Microsoft's advice for testing Copilot over a semantic model: define the expected measure, grouping, date context, filters and result for each question (section 12, R4).

```yaml
schema: cfeval.golden/v2
defaults:
  repeats: 3
cases:
  - id: SALES-001
    question: What was gross revenue in FY2025?
    paraphrases:
      - How much gross revenue did we make in fiscal 2025?
    category: routing
    criticality: critical            # critical | standard
    persona: analyst                 # key in personas.yaml; optional
    intent:
      measure: Gross Revenue
      grouping: none
      date_context: fiscal year FY2025
      filters: []
    expectation:
      type: numeric                  # numeric | categorical | set | table | text | refusal | clarification
      value: 12840000
      unit: currency
      rel_tol: 0.005
      display_tol: 0.01
      reference_dax: EVALUATE ROW("v", CALCULATE([Gross Revenue], 'Date'[Fiscal Year] = "FY2025"))
      reference_answer: Gross revenue in FY2025 was about $12.84M.
    routing:
      expected_model: {name: Sales Analytics, id: null}
      expected_artifacts: [{name: Sales Analytics, id: null}]
      decoys: [{name: Sales Sandbox}, {name: "FY2025 revenue - DRAFT"}]
```

### 4.4 Gate policy

Today the three gate checks are fixed, so a tenant without workspace monitoring gets `INCONCLUSIVE` for every correct answer. Make the policy explicit in `config/gates.yaml`:

```yaml
required_checks:
  with_engine_evidence: [value, artifact, model]
  without_engine_evidence: [value, artifact]   # verdicts carry routing_evidence=citations-only
release:
  critical: {min_pass_pow_k: 1.0}
  standard: {min_pass_rate: 0.85, min_wilson_low: 0.75}
  regression: {max_new_failures: 0, alpha: 0.05}
sample_size:
  warn_below_cases: 20
```

### 4.5 Statistics

| Metric | Definition |
|---|---|
| pass@1 | Mean pass rate over all attempts |
| pass^k | Share of cases where all k attempts pass |
| Consistency | Share of cases whose attempts return the same extracted value |
| Interval | Wilson 95% interval on the pass rate |
| Regression | Exact McNemar test on paired per-case outcomes of two runs, plus the list of cases that changed |

Implement with the standard library only, in `src/cfeval/stats.py`.

### 4.6 Value extraction

Keep the rule that the expected value is never used to choose a candidate. Add methods, tried in this order, and record which one produced the verdict:

1. `first`: today's deterministic parser.
2. `explicit`: a value Copilot states in the structured follow-up turn, accepted only if the same number appears in the answer text.
3. `llm_extract`: the judge model returns the span that answers the question, given only the question and the answer. Code confirms the span exists in the answer and parses it deterministically.

Record `ExtractionMethod` and `MatchKind` (`exact`, `tolerance`, `display_rounding`, `extracted`). A pass that needed methods 2 or 3, or display rounding, stays visible as such in every report.

### 4.7 Engine evidence

- Read `OperationId`, `ApplicationContext` and `CpuTimeMs` as well as the fields already captured.
- Add `cfeval trace probe`: list the distinct `ApplicationName` values and `ApplicationContext` keys seen for the test user in a time window, so each tenant can characterise Copilot-originated queries. Do not hard-code an undocumented marker.
- Exclude known noise: the watermark query and the text-index build pattern (`SELECTCOLUMNS` over `VALUES` with a `LEN` filter and a `"valueColumn"` alias).
- Flag ambiguity: a query that fits two ask windows, or windows closer together than the configured pause, sets `CorrelationConfidence = low`.
- Document the simpler setup now available: workspace monitoring can send several workspaces to one monitoring item.

### 4.8 Telemetry additions

Additive only. The repository's troubleshooting guide notes that a column type cannot be changed once OneLake availability is on for a table.

| Table | Add | Purpose |
|---|---|---|
| `EvalRun` | `Target`, `K`, `PassPowK`, `WilsonLow`, `WilsonHigh`, `JudgePromptHash`, `JudgeCalibrationId`, `GatePolicyHash`, `SchemaVersion` | Statistics and reproducibility |
| `EvalQuestion` | `CaseType`, `Persona`, `Tags`, `Intent`, `Gates` | Slicing |
| `EvalAsk` | `Persona`, `Paraphrase`, `Target` | Multi-target and paraphrase analysis |
| `EvalResult` | `MatchKind`, `ExtractionMethod`, `RoutingEvidence`, `CorrelationConfidence`, `Persona` | Explainability |
| `FabricIqQuery` | `OperationId`, `ApplicationContext`, `CpuTimeMs` | Stronger correlation |

---

## 5. Decisions for the maintainer

Copilot assumes the default until the maintainer says otherwise.

| # | Decision | Default the agent assumes | Maintainer action |
|---|---|---|---|
| D1 | Public name | Keep the import package `cfeval`. Use the title "Copilot × IQ evaluation accelerator". Do not rename the repository in code | Choose the final repository and distribution name before v1.0 |
| D2 | Publishing home | Stay in the current repository | If it moves to an organization, complete that organization's open-source release review and adopt its templates first |
| D3 | PyPI | Build wheels in CI and attach them to GitHub Releases only | Decide on a PyPI name and Trusted Publishing |
| D4 | Scope of v1.0 | Fabric IQ pack complete; Work IQ starter pack; other sources documented as roadmap | Confirm |
| D5 | Dashboards | A static HTML report is the default. The Fabric app stays optional because it depends on a preview | Decide whether to add a Power BI template |
| D6 | Display-rounding tolerance | 1% (`display_tol: 0.01`), overridable per case | Confirm; today it is 5% |
| D7 | Repeats | 1 for smoke runs; 3 for `critical` cases | Confirm the cost trade-off |

---

## 6. Milestones

| Milestone | Outcome | Items | Exit check |
|---|---|---|---|
| **M0 Safe to share** | Nothing misleading or internal in the public repository; the agent environment works | M0-00 to M0-06 | Wording check, sample check and code scanning pass |
| **M1 Credible** | Verdicts you can defend: tests, extraction, gates, statistics, calibration | M1-01 to M1-14 | Coverage and grader-corpus thresholds met |
| **M2 Adoptable** | A stranger can install, understand, run and report | M2-01 to M2-09 | A first-time user completes the docs walkthrough |
| **M3 Extensible** | More than one way in; interoperates with Microsoft's tools; scales | M3-01 to M3-09 | Two extra targets pass offline contract tests |
| **M4 Aligned and released** | Alignment after Microsoft Ignite, live validation, v1.0.0 | M4-01 to M4-04 | Release checklist complete |

Order: M0 now. M1 next. M2 can start once M1-01 and M1-11 merge. Do M4-01 in the week after 20 Nov 2026, before starting M3, because Ignite sessions may change what M3 should build.

Sizes: XS under 1 hour of agent work, S half a day, M one to two days, L more than two days (split it).

Suggested first ten issues, in this order: M0-00, M0-01, M0-04, M0-03, M0-02, M0-05, M0-06, M1-01, M1-02, M1-03.

---

## 7. Work items

Each item is written to be pasted into one GitHub issue. "Findings" refer to Appendix A.

### M0 — Safe to share

#### M0-00 · Prepare the repository for the Copilot cloud agent
`type:agent` · size S · depends on: none · findings: F-01

**Change**
- Add `.github/workflows/copilot-setup-steps.yml` from Appendix B.1. It must contain a single job named `copilot-setup-steps` and be on the default branch.
- Replace `.github/copilot-instructions.md` with the text in section 8.1. Add `AGENTS.md` at the repository root with the text in section 8.2.
- Add path-scoped instructions with `applyTo` globs: `.github/instructions/python.instructions.md` (`src/**`, `tests/**`, `tools/**`), `app.instructions.md` (`app/**`), `docs.instructions.md` (`**/*.md`, `notebooks/**`).
- Commit this plan as `docs/PLAN.md`.

**Done when**
- [ ] The setup workflow succeeds when started manually from the Actions tab.
- [ ] No instruction file tells contributors not to add tests.
- [ ] `AGENTS.md` lists the commands that verify a change offline.

#### M0-01 · Remove demo-specific and tool-specific wording
`type:agent` · size S · depends on: M0-00 · findings: F-12

**Change**
- `src/cfeval/auth.py`: the sign-in context label starts with the literal `Scout |`. Replace the prefix with `cfeval |`.
- Remove references to one particular demo from `README.md`, `docs/SETUP.md`, `docs/DEMO.md`, `docs/METRICS.md`, `docs/TROUBLESHOOTING.md`, `CONTRIBUTING.md`, `app/README.md`, `data/golden/README.md` and all four notebooks. Examples to remove or rewrite: "Friday", "during the meeting", "NO-GO", "approved allowance", "separately approved", "paid calls", "the owner explicitly approves".
- Keep the technical safeguards those sentences describe (attempt limits, no blind retries, read-only verification). Rewrite them as neutral product behaviour, for example "The strict run sends each question once and never retries automatically."
- Rename every "Evidence gaps / still thin" heading to "Limitations".
- Add `tools/check_public_wording.py`: fails when a file under version control contains a term from `config/wording-denylist.txt`. It skips the denylist file itself and `docs/PLAN.md`, because this plan quotes the terms it asks to remove. It also reads extra terms from the environment variable `CFEVAL_PRIVATE_DENYLIST` (comma-separated), so private terms can be checked through a repository secret without being committed.

**Done when**
- [ ] `python tools/check_public_wording.py` exits 0 and runs in CI.
- [ ] `grep -rn "Scout\|Friday\|during the meeting\|NO-GO\|approved allowance" .` returns nothing outside the denylist file and `docs/PLAN.md`.
- [ ] No safeguard in code changed behaviour; the offline smoke still passes.

#### M0-02 · Repository settings and community files
`type:manual` for settings, `type:agent` for files · size S · depends on: none · findings: F-13

**Manual (repository admin; the full checklist is in section 11.1)**
- Add a description and topics (`microsoft-365-copilot`, `microsoft-fabric`, `fabric-iq`, `power-bi`, `evaluation`, `llm-evaluation`, `semantic-model`).
- Enable Issues. `SUPPORT.md` tells users to open an issue, and Issues are currently disabled. Optionally enable Discussions for questions.
- Enable private vulnerability reporting (referenced by `SECURITY.md`), secret scanning with push protection, and Dependabot alerts.
- Protect `main`: pull request required, status checks required, no force push.
- Create the labels in Appendix B.5.

**Agent**
- Add issue forms in `.github/ISSUE_TEMPLATE/`: `bug.yml` (sample in Appendix B.2; asks for `cfeval doctor` output, command, expected and actual result, and a confirmation that no tenant data is included), `feature.yml`, and `config.yml` linking to Discussions and the security policy.
- Add `.github/CODEOWNERS`, `.github/dependabot.yml` (ecosystems: `pip`, `npm` in `app/standalone`, `github-actions`; weekly; grouped minor and patch updates; sample in Appendix B.3).
- Update `SUPPORT.md`, `SECURITY.md` (supported versions, what to expect after a report) and `CODE_OF_CONDUCT.md` (a working private contact route). Replace `.github/PULL_REQUEST_TEMPLATE.md` with the text in section 8.4.

**Done when**
- [ ] The GitHub community profile shows every item complete.
- [ ] A test issue can be opened from each form.

#### M0-03 · Reproducible sample data and lighter assets
`type:agent` · size S · depends on: none · findings: F-14

**Change**
- `app/overlay/public/sample-data/evals.json` holds 8 simulated runs but 16 `EvalRun`, 128 `EvalQuestion` and 160 `EvalResult` rows: two copies of each. The two `EvalResult` copies share a `ScoredUtc` and differ only in `JudgeNotes` and, in 34 of 80 pairs, `Reasons`, so the "latest row wins" logic in the app and the KQL functions cannot choose between them. Regenerate the file once, cleanly.
- Make generation reproducible: add `--as-of <ISO datetime>` to `cfeval demo-data` so `simulate_runs` no longer depends on the current time. Document the exact command in `app/README.md`.
- Extend `app/scripts/dedupe-sample.mjs --check` to all five tables and run it in CI. Today it looks for exact duplicates in `FabricIqQuery` and `EvalEvent` only. Add a key check: one row per `RunId` in `EvalRun`; per `RunId` and `QuestionId` in `EvalQuestion`; per `RunId`, `AskId`, `Backend` and `ScoredUtc` in `EvalResult`.
- Reduce `docs/architecture/simplified-architecture.png` (1.1 MB) to under 300 KB at a width that stays readable on GitHub. Replace the 0.98 MB SVG with a lean vector file, or remove it and keep the editable source outside the repository.

**Done when**
- [ ] Running the documented command twice gives byte-identical `evals.json`, and CI checks it.
- [ ] The sample has one `EvalRun` row per run, one `EvalQuestion` row per run and question, and one `EvalResult` row per ask and scoring backend. For the current mix of runs that is 8, 64 and 80 rows.
- [ ] No tracked file is larger than 500 KB (add this check to CI).

#### M0-04 · Resolve contradictions between docs and code
`type:agent` · size XS · depends on: none · findings: F-15, F-16

**Change**
- `src/cfeval/kql/functions.kql`: `LatencyBreakdown` computes `NonDaxMs = LatencyMs - DaxTotalMs`, while `docs/METRICS.md` states that captured DAX time and answer latency are not additive. Remove `NonDaxMs`, or rename the function output and state the caveat in the docstring. Regenerate `kql/setup.kql`.
- `app/overlay/src/eval/metrics.ts`: the header says the file is unit-tested with `node --test`. Remove the claim here; M1-12 makes it true again.

**Done when**
- [ ] `python -m cfeval kql --out kql/setup.kql && git diff --exit-code` passes.
- [ ] `docs/METRICS.md` and the KQL functions describe latency the same way.

#### M0-05 · Security baseline in CI
`type:agent` · size S · depends on: M0-00 · findings: F-22

**Change**
- Add `.github/workflows/codeql.yml` for `python`, `javascript-typescript` and `actions`, on push, pull request and a weekly schedule.
- Pin every action in every workflow to a full commit SHA with the version in a trailing comment. Keep `permissions: contents: read` as the default and widen per job only where needed.
- Add a secret-scan step (for example gitleaks) and a "largest tracked file" check to `ci.yml`.

**Done when**
- [ ] Code scanning reports no open alert of high or critical severity.
- [ ] No workflow references an action by tag only.

#### M0-06 · State preview dependencies plainly
`type:agent` · size XS · depends on: M0-01 · findings: F-05

**Change**
- Add a "Platform status" table to `README.md` and a fuller `docs/reference/platform-status.md` with a "last verified" date and links from section 12: Copilot Chat API (preview; Microsoft states that production use of `/beta` APIs is not supported; documented for enterprise-search and web grounding), Fabric IQ in Microsoft 365 Copilot Chat (generally available; requires a Microsoft 365 Copilot Premium licence and Power BI access), workspace monitoring (uses Fabric capacity; 30-day default retention), Foundry custom evaluators (preview), Fabric Apps (described as a preview in `app/README.md`; section 12 has no source for it, so a maintainer adds the Microsoft link).
- Add a short "How this relates to Microsoft's evaluation tools" table to `README.md`: Microsoft 365 Copilot Evaluations CLI, Foundry Evaluations, Fabric data agent evaluation, and what this accelerator adds to each.

**Done when**
- [ ] Each row links to a Microsoft source and carries the verification date.

---

### M1 — Credible

#### M1-01 · Reverse the no-tests policy and add the test toolchain
`type:agent` · size S · depends on: M0-00 · findings: F-01

**Change**
- Add a `dev` extra in `pyproject.toml`: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`. Add `[tool.pytest.ini_options]`, `[tool.ruff]` (line length 120 to match the code) and `[tool.coverage.*]`. Register a `live` pytest marker, and skip tests that carry it unless `CFEVAL_LIVE=1` (section 9).
- Create `tests/` with `unit/`, `contract/`, `e2e_offline/` and `data/`. Add one real test per folder so the layout is exercised.
- Update `CONTRIBUTING.md`: tests are required for behaviour changes. Remove the sentences that forbid a test framework.
- Update the setup workflow from M0-00 to install `.[dev]`.

**Done when**
- [ ] `python -m pytest -q` passes locally and in CI.
- [ ] `ruff check .` passes, with existing violations either fixed or listed in a short, justified ignore list.

#### M1-02 · Grader corpus for the value check
`type:agent` · size M · depends on: M1-01 · findings: F-02, F-03

**Change**
- Add `tests/data/value_cases.jsonl` with at least 150 labelled rows: `answer`, `expected`, `unit`, `rel_tol`, `abs_tol`, `should_pass`, `expected_extracted`, `category`, `note`.
- Cover: plain and scaled numbers; currency symbols and suffixes; percent and ratio forms; comparison sentences; change-then-value sentences; a small count before the answer; Markdown tables; ranges; number formats that use `.` for thousands and `,` for decimals; negatives; dates, years and fiscal labels; ordinals; refusals; clarifying questions; lists of values.
- Include these cases found in review. All use the Contoso sample values.

| Answer | Expected | Unit | Today | Should be |
|---|---|---|---|---|
| Compared with $12.2M last year, gross revenue rose to $12.84M in FY2025. | 12840000 | currency | FAIL | PASS |
| Revenue grew by $640K to $12.84M. | 12840000 | currency | FAIL | PASS |
| Across 3 regions we sold 48,210 units in Q2 FY2025. | 48210 | count | FAIL | PASS |
| Gross margin was 0.416 in FY2025. | 41.6 | percent | FAIL | PASS |
| Der Umsatz betrug 12.840.000 € im GJ2025. | 12840000 | currency | FAIL | PASS with a locale setting |
| Gross margin was 41,6 %. | 41.6 | percent | FAIL | PASS with a locale setting |
| About $13M. | 12840000 | currency | PASS | FAIL at `rel_tol` 0.005 unless `display_tol` allows it |

- Add `tests/unit/test_value_corpus.py`. It reports false-pass and false-fail rates by category and writes a Markdown summary.

**Done when**
- [ ] The corpus test runs and fails on the rows above, proving it detects the current behaviour. Mark those rows `xfail` with a link to M1-03.
- [ ] The false-pass count on rows with `should_pass: false` is asserted to be zero from M1-03 onwards.

#### M1-03 · Value extraction v2
`type:agent` · size M · depends on: M1-02 · findings: F-02, F-03

**Change**
- `src/cfeval/scorers.py`: implement section 4.6. Keep the module standard-library only.
- Add options: `number_locale` (`en`, `eu`, `auto`), `percent_accepts_ratio` (default true: 0.416 matches 41.6%), and `display_tol` (default from D6; per-case override). Return `match_kind` and `extraction_method` in every result.
- `src/cfeval/chat.py`: extend the follow-up JSON shape with `"answer": {"value": "", "unit": ""}`. Accept it only when the same number is present in the answer text.
- `src/cfeval/judge.py`: add `extract_value(question, answer)` returning a literal span. The prompt never contains the expected value.
- `src/cfeval/schema.py`: add `MatchKind` and `ExtractionMethod` to `EvalResult`. Regenerate the KQL script, the app contract and the reference entities.
- Remove the `xfail` marks added in M1-02.

**Done when**
- [ ] Corpus: zero false passes; at most 5% false fails.
- [ ] Existing offline smoke results for the bundled sample are unchanged, or each change is explained in the pull request.
- [ ] The code bundle registered with Foundry stays under 256 KB (assert in a test).

#### M1-04 · Golden set schema v2, validation and lint
`type:agent` · size M · depends on: M1-01 · findings: F-19

**Change**
- Add `schemas/golden.schema.json` and `src/cfeval/golden_v2.py` implementing section 4.3. Load `.yaml`, `.yml`, `.json` and the existing `.csv`.
- Add commands: `cfeval golden validate <file>`, `cfeval golden convert <csv> --out <yaml>`, `cfeval golden lint <file>`.
- Lint rules (warnings): no reference DAX; name-only routing expectation without an item ID; time-relative wording such as "latest" or "this year" with no as-of date; duplicate or near-duplicate questions; fewer than 20 cases; a `critical` case with `repeats` below 3.
- Convert `data/golden/golden_questions.csv` to `data/golden/contoso.yaml` and keep the CSV as a fixture for backward compatibility.

**Done when**
- [ ] Round trip CSV to YAML to internal model gives identical cases for the bundled sample.
- [ ] Invalid files fail with a message naming the case ID and field.

#### M1-05 · More expectation types
`type:agent` · size L (split per type) · depends on: M1-04 · findings: F-19

**Change**
- Add scorers with tests: `categorical` (exact or alias match of a named value), `set` (unordered or ordered list, with a minimum-overlap option), `refusal` (the assistant must decline or say it has no access), `clarification` (the assistant must ask a clarifying question).
- `refusal` and `clarification`: deterministic patterns first, judge second, result `INCONCLUSIVE` when they disagree.
- `table` (compare a Markdown table in the answer with the reference DAX row set, order-insensitive, numeric tolerance per cell) is a stretch goal behind a feature flag.
- Extend `src/cfeval/mock.py` so the simulated tenant can produce each new shape, and add 12 or more sample cases to `data/golden/contoso.yaml`.

**Done when**
- [ ] Each type has at least 15 unit cases and one offline end-to-end case.
- [ ] `docs/reference/golden-schema.md` documents every type with an example.

#### M1-06 · Configurable gate policy and CI outputs
`type:agent` · size M · depends on: M1-04 · findings: F-04

**Change**
- Implement section 4.4. `src/cfeval/scoring.py` reads required checks from the policy instead of the constant `GATE_CHECKS`. A case may override its gates.
- When engine evidence is not configured, use `without_engine_evidence` and set `RoutingEvidence = citations-only` on every result. Reports must show this label next to the pass rate.
- Add `cfeval gate <run-folder>`: applies the `release` section and returns documented exit codes. Write `junit.xml` and a Markdown summary suitable for a GitHub job summary.

**Done when**
- [ ] `python -m cfeval run --mock --no-trace --profile tuned` reports passes (today: 0 pass, 7 inconclusive).
- [ ] With engine evidence configured, behaviour is unchanged.
- [ ] Exit codes are listed in `docs/reference/exit-codes.md` and covered by tests.

#### M1-07 · Repeats and statistics
`type:agent` · size M · depends on: M1-06 · findings: F-06

**Change**
- Add `src/cfeval/stats.py` implementing section 4.5 with tests against published reference values for the Wilson interval and the exact McNemar test.
- `pipeline.run_metrics`: aggregate per case before aggregating per run. Add `K`, `PassPowK`, `WilsonLow`, `WilsonHigh` to `EvalRun`.
- Repeats per criticality (D7). Paraphrases count as separate attempts of the same case and are reported separately.
- Add `cfeval compare --baseline <run> --candidate <run>`: per-case changes, the paired test, and a verdict against `release.regression`.
- Warn in the run summary when the set has fewer cases than `sample_size.warn_below_cases`.

**Done when**
- [ ] A simulated run with `repeats: 3` shows pass@1, pass^k, consistency and an interval in `summary.md`.
- [ ] `cfeval compare` detects the difference between the `baseline` and `tuned` simulation profiles and reports no regression for identical runs.

#### M1-08 · Judge calibration
`type:agent` · size M · depends on: M1-01 · findings: F-07

**Change**
- Add `data/judge_calibration/answers.jsonl`: at least 120 synthetic answer pairs with a human `should_pass` label, at least 40% negatives. Cover rounding and format, ratio versus percent, unit normalisation, list order, group-by completeness, and refusing versus fabricating.
- Add `cfeval judge calibrate`: grades each pair three times, takes the majority, and reports raw agreement, Cohen's kappa, recall on the fail class and precision on the pass class. Thresholds are configurable; suggested defaults 0.90, 0.70 and 0.85.
- Make the answer judge binary with a one-sentence critique and an explicit "cannot tell" outcome. Keep 1 to 5 scores as diagnostics only.
- Keep the judge behind one interface, so that another source of verdicts can be tried later. The Foundry Decisions API returns typed answers with a confidence value and is a candidate (section 12, R14). Do not add it in this item.
- Record `JudgeModel`, `JudgePromptHash` and `JudgeCalibrationId` in `EvalRun`. `cfeval doctor` warns when the judge has no calibration record for the current prompt hash.

**Done when**
- [ ] Calibration runs offline against a fake judge in tests, including a judge that always passes (must fail the thresholds).
- [ ] `docs/how-to/calibrate-the-judge.md` explains how to add local labelled pairs without committing tenant data.

#### M1-09 · Stronger engine-evidence correlation
`type:agent` · size M · depends on: M1-01 · findings: F-09

**Change**
- Implement section 4.7 in `src/cfeval/trace.py` and `src/cfeval/schema.py`.
- Unit tests with synthetic logs: overlapping windows, late arrival, another user's queries, the watermark, text-index build queries, a decoy model queried in a why-turn window.
- `docs/how-to/capture-dax.md`: one monitoring item for several workspaces, retention, capacity use, and how to read `cfeval trace probe`.

**Done when**
- [ ] New fields are present in `FabricIqQuery` and in generated artifacts.
- [ ] Ambiguous attributions are flagged, never silently assigned.

#### M1-10 · Stricter artifact and model matching
`type:agent` · size S · depends on: M1-04 · findings: F-08

**Change**
- `scorers.name_matches` treats "Sales" as matching "Sales Sandbox". Make exact normalised match the default. Allow containment only through explicit aliases or `match_mode: contains` on a case.
- Prefer item IDs wherever both sides have one. Lint (M1-04) warns on name-only expectations.

**Done when**
- [ ] Tests cover look-alike names, renamed items matched by ID, and aliases.

#### M1-11 · Configuration and HTTP robustness
`type:agent` · size M · depends on: M1-01 · findings: F-10, F-18

**Change**
- `src/cfeval/config.py`: read `CFEVAL_<NAME>` first, then the old unprefixed name with a deprecation warning. Unprefixed names such as `OUTPUT_DIR`, `CLIENT_ID` and `REPEATS` collide with variables that already exist on developer machines and CI runners.
- `.env` parsing: treat `#` as a comment only at line start or after whitespace outside quotes; today a value containing ` #` is truncated.
- Add `cfeval doctor --strict`: validates types, URLs and GUIDs and exits non-zero on the first error, without network calls.
- HTTP clients in `chat.py`, `powerbi.py` and `fabric_rest.py`: accept the HTTP-date form of `Retry-After` (today `float()` raises), add jitter, retry connection errors within a bounded budget, and keep the strict mode that disables retries.
- Update `.env.example`, the notebooks and all docs to the prefixed names.

**Done when**
- [ ] Tests prove precedence, the deprecation warning, and that an unrelated ambient `OUTPUT_DIR` no longer changes behaviour when `CFEVAL_OUTPUT_DIR` is set.
- [ ] Retry behaviour is covered with a fake transport.

#### M1-12 · Tests for the scorecard logic
`type:agent` · size S · depends on: M0-04 · findings: F-16

**Change**
- Add `node --test` suites for `metrics.ts`, `normalize.ts`, `format.ts` and `loadState.ts` under `app/standalone/tests/`, with an `npm test` script.
- Add a parity fixture: the same JSON rows scored by `pipeline.run_metrics` in Python and by the TypeScript metrics must give the same pass rate, accuracy and latency percentiles.

**Done when**
- [ ] `npm test` runs in the `app` CI job.
- [ ] The parity test fails if either implementation changes a definition alone.

#### M1-13 · Pipeline and contract tests
`type:agent` · size M · depends on: M1-01 · findings: F-01

**Change**
- Offline end-to-end tests for each simulation profile, asserting verdicts and row counts per table.
- `foundry.parse_output_items`: tests from recorded sample payloads, including missing, duplicate and conflicting criteria.
- `runtime.inspect_acquired_token`: tests with synthetic unsigned tokens for wrong tenant, audience, user, scope and expiry.
- `kqlgen`: snapshot test. `sinks.coerce_row`: unknown column and type coercion tests. CLI: `--help` for every command and exit-code tests.
- Execute `notebooks/00_quickstart_offline.ipynb` in CI.

**Done when**
- [ ] Coverage is at least 85% on `scorers`, `scoring`, `stats`, `golden*`, `trace`, `artifacts`, `sinks`, `kqlgen`, and at least 70% overall.

#### M1-14 · CI upgrade
`type:agent` · size S · depends on: M1-01, M1-12 · findings: F-01, F-22

**Change**
- `ci.yml` matrix: Ubuntu and Windows, Python 3.10 to 3.13. Steps: `ruff check`, `ruff format --check`, `mypy` (strict on `scorers`, `scoring`, `stats`, `golden*`; permissive elsewhere), `pytest` with coverage, generated-file drift, wording check, sample check, Markdown lint and link check.
- Cache dependencies. Cancel superseded runs. Upload `junit.xml` and coverage as artifacts.

**Done when**
- [ ] All jobs are required status checks on `main`.
- [ ] A full CI run takes under 10 minutes.

---

### M2 — Adoptable

#### M2-01 · One command-line surface
`type:agent` · size M · depends on: M1-06, M1-11 · findings: F-17

**Change**
- Move `tools/setup_demo.py` into `cfeval setup` (preview by default, `--apply` to write). Move `tools/rehearse_demo.py` into `cfeval run --strict` (single attempt, no retries, explicit ceilings) and `cfeval verify <run>` (read-only comparison of JSONL, Eventhouse and SQL row counts). Keep `tools/gen_app_contract.py` as a developer script.
- Split the 121-line `main` in `tools/rehearse_demo.py` into functions with unit tests. Keep the old scripts for one release as thin wrappers that print a deprecation notice.
- Use user-facing names "Local scoring" and "Foundry Evaluations scoring" in help text and docs. Keep the stored `Backend` values (`fabric-native`, `foundry`) so existing telemetry still filters correctly.

**Done when**
- [ ] `cfeval --help` lists every command with a one-line description, and `docs/reference/cli.md` is generated from it.
- [ ] The CI smoke uses `cfeval run --strict --mock`.

#### M2-02 · Internal structure, types and logging
`type:agent` · size L (split by module) · depends on: M1-13 · findings: F-17

**Change**
- Introduce the protocols in section 4.1. Replace the 30-parameter `EvalHarness.__init__` and the 19-parameter `build_harness` with a `RunConfig` dataclass plus injected collaborators.
- Add type hints to the public API of every module, ship `py.typed`, and raise the `mypy` level module by module.
- Replace `print` and `log=print` with the `logging` module. Add `--log-level` and `--log-format plain|json`. Keep user-facing output on stdout and diagnostics on stderr.
- Narrow the 10 broad `except Exception` handlers to named exceptions, or re-raise after recording.
- No behaviour change: the M1 test suite must pass unchanged.

**Done when**
- [ ] `mypy --strict` passes on `scorers`, `scoring`, `stats`, `golden*`, `interfaces`, `config`.
- [ ] No `print(` remains in `src/cfeval` outside the CLI output layer.

#### M2-03 · Packaging and releases
`type:agent` · size M · depends on: M1-14 · findings: F-20

**Change**
- `pyproject.toml`: SPDX licence expression and `license-files`; `project.urls` (repository, docs, issues, changelog); classifiers for supported Python versions and development status; a single version source read by `cfeval.__version__`.
- Remove `requirements.txt` or generate it from the lock file. Adopt a lock file for development (`uv.lock`).
- Add `CHANGELOG.md` (Keep a Changelog format) and state the versioning policy in `CONTRIBUTING.md`.
- Add `.github/workflows/release.yml`: on a version tag, build the wheel and source distribution, generate an SBOM, attach build provenance, create a GitHub Release with notes from the changelog. Publishing to PyPI stays off until decision D3.
- Notebooks: install from a tagged release, not from the default branch.

**Done when**
- [ ] `python -m build` output installs cleanly in a fresh environment and `cfeval run --mock` works from the wheel.
- [ ] A dry-run tag on a fork produces a draft release with artifacts.

#### M2-04 · Documentation restructure
`type:agent` · size L (split by section) · depends on: M0-01, M2-01 · findings: F-21, F-24

**Change**
- Rewrite `README.md` to at most 150 lines: what it is and who it is for; the offline quickstart; one screenshot of the report; how it relates to Microsoft's tools; platform status; limitations; links.
- Restructure `docs/` as in section 10. Move the scripted-demo material to `docs/how-to/run-a-live-demo.md`. Generate `docs/reference/telemetry-schema.md` from `schema.py` and `docs/reference/configuration.md` from the settings class, with drift checks in CI.
- Add architecture decision records in `docs/decisions/`: evidence triangulation; deterministic gates; choice of targets; telemetry store.
- Add `docs/concepts/limitations.md` gathering every limitation in one place.
- Style: plain sentences, product names as Microsoft Learn writes them, "demo tenant" and "demo Azure subscription" for environments, one term per concept (glossary in `docs/reference/glossary.md`, using the vocabulary in section 10.4).

**Done when**
- [ ] A reader can go from `README.md` to a scored offline run without opening another file.
- [ ] Markdown lint and link check pass in CI.

#### M2-05 · Responsible use, security and cost
`type:agent` · size M · depends on: M2-04 · findings: F-21

**Change**
- Add `TRANSPARENCY_FAQ.md`: what the accelerator does and does not do, intended uses, limits of each evidence type, the role of human review, what is stored and where.
- Add `docs/responsible-use/threat-model.md`. Cover at least: the test user's delegated token carries broad read scopes (mail, chats, files, sites), so use a dedicated account that holds no sensitive content; protection of the token cache locally and in Key Vault; telemetry stores Copilot's answers, so restrict access to the telemetry workspace as you would the source models; why the harness never switches accounts or prompts silently.
- Add `docs/get-started/cost-and-limits.md`: licences needed, capacity used by query execution and workspace monitoring, judge-model tokens, Eventhouse storage, expected duration for a given set size and pause.

**Done when**
- [ ] `SECURITY.md` and `README.md` link to these pages.

#### M2-06 · A report that needs no Fabric app
`type:agent` · size M · depends on: M1-07 · findings: F-25

**Change**
- Add `cfeval report <run-folder> [--baseline <run-folder>] --out report.html`: one self-contained HTML file with no external requests. Sections: summary with intervals, gate result, per-case table with evidence, routing matrix, latency, changes against the baseline.
- Reuse the metric definitions; add the report to the parity fixture from M1-12.
- The Fabric app remains an optional viewer for trends over many runs.

**Done when**
- [ ] The offline quickstart ends by opening the HTML report.
- [ ] The report passes an automated accessibility check for headings, table headers and contrast.

#### M2-07 · Development environment
`type:agent` · size S · depends on: M1-01

**Change**
- Add `.devcontainer/devcontainer.json` (Python 3.12, Node 24, the `dev` extra, `npm ci` in `app/standalone`).
- Add a `Makefile` (or `noxfile.py`) with `check` running everything CI runs, plus `fmt`, `test`, `docs`.
- Add `.pre-commit-config.yaml`: ruff, Markdown lint, YAML check, secret scan, notebook output stripping.

**Done when**
- [ ] `make check` passes in a fresh dev container.

#### M2-08 · Golden-set authoring kit
`type:agent` · size M · depends on: M1-05 · findings: F-06, F-19

**Change**
- Grow `data/golden/contoso.yaml` to at least 40 cases across the three sample models: named-source and unqualified routing, paraphrases, time intelligence, disambiguation between similar measures, one decoy model and one decoy document, ambiguous questions that should trigger a clarifying question, out-of-scope questions that should be refused.
- Add `docs/how-to/author-a-golden-set.md`: how to pick questions, write reference DAX that returns one cell, set tolerances, choose decoys, and version the set. Align sizing advice with Microsoft's published guidance (section 12, R7).
- Add `cfeval golden scaffold --measures <file>`: from an exported list of measures and descriptions, write a starter YAML with one stub case per measure. Offline only.

**Done when**
- [ ] The simulated tenant answers every bundled case, and each simulation profile gives a distinct, documented pass rate.

#### M2-09 · Optional deployable sample models
`type:manual` for deployment, `type:agent` for files · size M · depends on: M2-08

**Change**
- Add `samples/contoso/` with small synthetic CSV data and model definitions for the three sample models and the decoy, so a newcomer can try the live path in a demo tenant without bringing their own models.
- Document the deployment steps and the expected values. The agent writes files and docs; a person deploys and confirms the numbers.

**Done when**
- [ ] Reference DAX in `contoso.yaml` returns the expected values on the deployed sample (recorded by the person who deployed it).

---

### M3 — Extensible

#### M3-01 · Target registry and the `import` target
`type:agent` · size M · depends on: M2-02 · findings: F-05

**Change**
- Create `src/cfeval/targets/` with a registry and an entry-point group `cfeval.targets`. Move the Graph Chat API client behind `Target` as `m365-copilot-chat-graph`.
- Add `import`: reads CSV or JSONL with `case_id` or `question`, `answer`, optional `citations`, `user`, `started_utc`, `ended_utc`. Engine evidence is collected only when timestamps and user are present.
- Add `docs/how-to/add-a-target.md`.

**Done when**
- [ ] A transcript exported from the simulated target and re-imported gives identical verdicts.

#### M3-02 · Interoperate with the Microsoft 365 Copilot Evaluations CLI
`type:agent` · size M · depends on: M3-01 · findings: F-05

**Context**
- Microsoft's `@microsoft/m365-copilot-eval` (`runevals`) evaluates deployed agents today. Its v2 upgrade guide describes a preview in which a run with no agent ID targets Microsoft 365 Copilot itself, and an `--evaluate-only` mode that re-scores saved responses. Its evaluators cover relevance, coherence, groundedness, similarity, citations, retrieval and string matching. None checks a numeric value against live ground truth or which semantic model was queried.
- Its licence is not MIT. Do not copy its code or schema files into this repository. Write an independent reader and writer and link to its documentation.
- For deployed declarative agents, Microsoft's overview recommends starting with Work IQ Dev Tools (preview), which runs the same CLI (section 12, R6). Say so in the how-to page, so that a reader who is testing an agent is sent to the first-party route.

**Change**
- `cfeval golden export --format m365-copilot-eval --out evals.json`: write an eval document with `schemaVersion`, `default_evaluators` and one item per case (`prompt`, `expected_response`).
- `cfeval run --target import --from-m365-copilot-eval results.json`: map each item to an ask and score it with this accelerator's checks.
- `docs/how-to/use-with-the-evaluations-cli.md`: when to use which tool, and how to combine them.

**Done when**
- [ ] Round-trip tests use hand-written fixtures that follow the public examples in the CLI's README.
- [ ] The doc states the CLI version the fixtures were written against.

#### M3-03 · Fabric IQ MCP reference target
`type:agent` with fakes, `type:manual` for live validation · size L · depends on: M3-01 · findings: F-05, F-09

**Change**
- Add `fabric-iq-mcp-reference`: a minimal tool-calling loop that discovers artifacts, reads a semantic model schema, writes one DAX query with a Foundry-hosted model, executes it through the server, and answers. Discover the tool list at run time; do not hard-code beyond what the server returns.
- Record every tool call as evidence of kind `tool_call`, including the model ID and DAX. This gives exact routing evidence with no time-window correlation.
- Authentication is delegated only; the server does not accept service principals. Reuse the existing delegated sign-in with the Power BI permissions the server requires.
- Label results clearly: they show whether the semantic model can be answered by an agent using Fabric IQ tools. They are not Copilot results.

**Done when**
- [ ] Offline tests run against a fake MCP server.
- [ ] A live validation note is recorded under M4-02.

#### M3-04 · Fabric data agent target (optional)
`type:agent` · size M · depends on: M3-01

**Change**
- Add `fabric-data-agent` in its own extra. Capture the steps and queries the agent returns where available.
- Note the dependency split: the current `fabric-data-agent-sdk` requires `openai<3`, while current `azure-ai-projects` requires `openai>=3`. The two extras cannot share one environment. Document separate environments and fail early with a clear message.

**Done when**
- [ ] Installing both extras together produces a clear error from `cfeval doctor`.

#### M3-05 · Bring the Foundry scoring backend up to date
`type:agent` · size M · depends on: M1-13 · findings: F-11

**Change**
- Today `openai>=2,<3` forces `azure-ai-projects` to 2.4.x or older. Current releases are 2.11.0, which requires `openai>=3` and Python 3.10 or later. Move the `judge` and `foundry` extras to the current lines and read both SDK changelogs for breaking changes.
- Keep every Foundry call inside `src/cfeval/backends/foundry.py`. Keep the existing fallback between `project_client.evaluators` and `project_client.beta.evaluators`, and test both paths with fakes.
- Treat built-in 1 to 5 evaluators as diagnostics. Document preview status and the code-evaluator limits (under 256 KB, two minutes per call, no network).
- Mark the backend "experimental" in help text until M4-02 records a successful live run.

**Done when**
- [ ] Contract tests pass with the new SDK versions installed.
- [ ] A test asserts the code bundle size.

#### M3-06 · Personas and row-level security
`type:agent` · size L · depends on: M3-01, M1-04 · findings: F-19

**Change**
- Add `personas.yaml`: alias, sign-in name (from an environment variable), token cache location, optional notes. A case names a persona; expectations can differ per persona.
- Ground truth per persona: run reference DAX with that persona's delegated token.
- Run personas in parallel, each strictly sequential with its own pause. Engine evidence stays separable because it is filtered by executing user.
- Add `Persona` to telemetry and to the report filters.

**Done when**
- [ ] Simulated personas return different values for the same case, and a no-access persona is scored with the `refusal` type.
- [ ] Wall-clock time for a simulated 40-case run falls roughly in proportion to the number of personas.

#### M3-07 · Scale controls and safe re-publishing
`type:agent` · size M · depends on: M2-02 · findings: F-09, F-23

**Change**
- Add `cfeval plan`: number of attempts, estimated duration, and which checks will run, before anything is sent.
- Add `--resume` (continue an interrupted run without repeating completed attempts), `--shard i/n`, and a maximum wall time.
- Make publishing idempotent. Today the KQL functions and the app keep the latest `EvalResult` and `EvalRun` rows, but the other five tables are appended again, and functions such as `StageDurations` and `AskTimeline` count them twice. Add a deterministic `RowId` per row and de-duplicate every table in the KQL functions and the app, so that re-publishing a run folder cannot double-count.

**Done when**
- [ ] Publishing the same simulated run twice leaves every metric unchanged.

#### M3-08 · OpenTelemetry sink (optional)
`type:agent` · size M · depends on: M2-02

**Change**
- Add an optional sink that emits runs, attempts and scores as OpenTelemetry spans and events using the GenAI semantic conventions, so results can also flow to Azure Monitor or another collector.

**Done when**
- [ ] A test collector receives the expected spans for a simulated run.

#### M3-09 · Work IQ starter pack
`type:agent` for files, `type:manual` for tenant setup · size L · depends on: M1-05, M3-06

**Why**
The Graph Chat API is documented for enterprise-search grounding. Document-grounded questions are therefore the best-documented use of the existing target, and they make the "Copilot and IQ" scope real beyond Fabric IQ.

**Change**
- Generalise the artifact check: `expected_kind` on a case (default: Power BI items) so a document, site or message can be the expected source.
- Add a `facts` check: every required fact appears in the answer (normalised string or regular expression first, judge second).
- Add `data/golden/contoso-work.yaml` with at least 20 cases: the right document cited, a stale draft as decoy, a persona without access that must be refused, a question that needs two sources.
- Add synthetic documents under `samples/work-iq/` and a setup note for a demo tenant.

**Done when**
- [ ] The simulated tenant covers the pack offline.
- [ ] `docs/concepts/how-it-works.md` shows one table: source type, evidence available, checks used.

---

### M4 — Aligned and released

#### M4-01 · Alignment review after Microsoft Ignite (17–20 Nov 2026)
`type:manual` for the review, `type:agent` for the doc update · size S · depends on: M0-06

**Review these sessions and the product posts published that week**

| Session | Title | What to look for |
|---|---|---|
| BRK310 | The evaluation loop for Microsoft IQ | The official loop and vocabulary. Adopt its terms; integrate with anything it ships rather than duplicating it |
| BRK356 | Microsoft IQ roadmap: The operating system for enterprise AI agents | Planned quality controls for agents |
| BRK306, BRK305, BRK301 | Fabric IQ and Microsoft IQ sessions | Changes to how Copilot reaches semantic models, ontologies and data agents |
| BRK304 | What's new in Work IQ | Programmatic endpoints that could become a better-supported way to drive Copilot |
| LTG1214 | Observability for AI with Fabric Data Agent, Foundry, and Agent 365 | Telemetry that could replace time-window correlation |
| BRK249, BRK251 | Foundry improvement loop sessions | Evaluation API changes that affect M3-05 |

**Output**
- Update `docs/reference/platform-status.md` with the new verification date.
- Open issues for anything that changes sections 4 or 7, and re-rank M3.

#### M4-02 · Live validation in a demo tenant
`type:manual` · size M · depends on: M1 complete

Record sanitised results in `docs/validation/<date>.md`. No tenant identifiers, user names or real values.

| Scenario | Confirms |
|---|---|
| First check on day one: the Graph Chat API returns answers grounded in Power BI content for named-source questions | The primary target works in that tenant |
| Models in a workspace without workspace monitoring | Citations-only gates and labels |
| Models on a capacity with workspace monitoring, one monitoring item for several workspaces | Full gates, `cfeval trace probe`, correlation confidence |
| Two personas with different row-level security | Per-persona ground truth and refusal |
| 40 cases, 3 repeats | Duration, throttling behaviour, pass^k and intervals |
| Follow-up turn on and off | Whether the follow-up adds queries or changes routing |
| Foundry Evaluations scoring | Whether the backend can leave "experimental" |

#### M4-03 · Apply naming and home decisions
`type:manual` then `type:agent` · size S · depends on: D1, D2

- Apply the chosen repository and distribution names across code, docs, notebooks and badges in one pull request.
- If the repository moves to an organization, complete that organization's open-source release review and adopt its required files before promoting the accelerator.

#### M4-04 · Release v1.0.0
`type:manual` with agent support · size S · depends on: all release criteria in section 3.1

**Checklist**
- [ ] Every criterion in section 3.1 is met and linked to evidence.
- [ ] `CHANGELOG.md` is complete; version tagged; release workflow produced artifacts, SBOM and provenance.
- [ ] `docs/reference/platform-status.md` verified within the previous seven days.
- [ ] No open code-scanning alert of high or critical severity; no secret-scanning alert.
- [ ] Wording check passes, including the private denylist.
- [ ] Maintainers and response expectations are stated in `SUPPORT.md`.

---

## 8. Conventions for GitHub Copilot

### 8.1 Replacement for `.github/copilot-instructions.md`

Keep this file short. It is read on every agent session.

````markdown
# Instructions for GitHub Copilot in this repository

## What this repository is
An open accelerator that evaluates answers from Microsoft 365 Copilot, and other agents, to business-data questions. A Python harness (`src/cfeval`) asks a golden set of questions through a target, collects evidence (citations, engine query logs, tool traces), scores each answer with deterministic checks and an optional calibrated judge, and writes telemetry. `app/` is an optional scorecard for Microsoft Fabric.

## Layout
- `src/cfeval/` — the harness. `scorers.py` and `stats.py` are standard-library only.
- `src/cfeval/schema.py` — the only place table schemas are defined.
- `tests/` — `unit/`, `contract/`, `e2e_offline/`, `data/`.
- `data/golden/` — Contoso sample cases. `config/` — gate policy and wording denylist.
- `app/overlay/` — scorecard source. `app/standalone/` — local preview and app tests.
- `docs/` — get-started, concepts, how-to, reference, decisions. `docs/PLAN.md` — the work plan.

If a path above does not exist yet, `docs/PLAN.md` names the work item that creates it.

## Rules
1. Offline only. Never call Microsoft Graph, Fabric, Power BI or Microsoft Foundry from tests, CI or an agent session. Use the simulated tenant, fakes and fixtures.
2. Do not invent service contracts. If a field, endpoint or permission is not in the repository or in a source listed in `docs/PLAN.md` section 12, add `TODO(verify-live)`, add a skipped live test, and state the assumption in the pull request.
3. Evidence integrity. `ERROR` and `INCONCLUSIVE` never become `PASS`. Never replace a missing remote score with a local one. Never use the expected value to choose which number to extract from an answer.
4. Every behaviour change comes with tests. Scoring changes also add rows to `tests/data/value_cases.jsonl`.
5. `src/cfeval/scorers.py` stays standard-library only and small. It is bundled into Foundry code evaluators.
6. Import optional SDKs (msal, azure-kusto, openai, azure-identity, azure-ai-projects) lazily inside functions.
7. After a schema change, regenerate the KQL script, the app contract and the reference entities, and commit the result.
8. Telemetry changes are additive. Do not rename or retype an existing column.
9. Synthetic data only: Contoso names; no tenant IDs, user names, secrets or real answers. Describe environments as "demo tenant" and "demo Azure subscription".
10. One work item per pull request. Keep changes small.

## Before you open a pull request
Run the commands in `AGENTS.md` and paste the summary lines into the pull request. State what you could not verify offline.
````

### 8.2 `AGENTS.md`

Create this file at the repository root in M0-00. Coding agents, including GitHub Copilot's cloud agent, read it for set-up and verification commands (section 12, R20). Update it in the same pull request as any change to those commands.

````markdown
# AGENTS.md

Guidance for coding agents working in this repository. The work plan is `docs/PLAN.md`. The repository rules are in `.github/copilot-instructions.md`.

## Set up

```bash
python -m pip install -e ".[dev]"   # use plain `-e .` until work item M1-01 adds the dev extra
(cd app/standalone && npm ci --no-audit --no-fund)
```

## Verify

Everything below runs offline with no sign-in. Run it from the repository root before you open a pull request.

```bash
python -m pytest -q                                       # from M1-01
ruff check . && ruff format --check .                     # from M1-01
python tools/check_public_wording.py                      # from M0-01
python -m cfeval run --mock --option both --no-publish    # offline end-to-end run
python tools/gen_app_contract.py                          # regenerate the app contract
python -m cfeval kql --out kql/setup.kql                  # regenerate the KQL script
node app/scripts/generate-entities.mjs --metadata app/connectors/evals/metadata.example.json --out app/connectors/evals
git diff --exit-code                                      # generated files must not change
(cd app/standalone && npm run typecheck && npm run build && npm test)   # `npm test` from M1-12
```

A command marked "from Mx-yy" does not exist until that work item is merged. Skip it until then and say so in the pull request.

## Boundaries

- No network calls and no sign-in. Do not call Microsoft Graph, Fabric, Power BI or Microsoft Foundry. Use `--mock`, the fakes and the fixtures.
- Do not edit generated files by hand: `kql/setup.kql`, `app/overlay/src/eval/generated/` and the generated entity files under `app/connectors/evals/`. Change the source (`src/cfeval/schema.py` or the generator) and regenerate.
- Do not change repository settings, secrets, branch protection or releases.
- Do not start a work item labelled `type:manual`. Those need a person.
- Never weaken, skip or delete a test, a gate or a check to make a build pass. If a check is wrong, fix it in its own pull request and explain why.
- Do not add tenant IDs, user names, real answers or screenshots from a real tenant.

## Behaviour you cannot verify offline

1. Mark the code with `TODO(verify-live): <what to check>`.
2. Add a test marked `@pytest.mark.live`. Live tests are skipped unless `CFEVAL_LIVE=1`, and CI never sets it.
3. List each assumption in the pull request under "Unverified live behaviour".

## Definition of done

- Every "Done when" box in the work item is true.
- All verification commands pass, and the pull request shows their summary lines.
- New behaviour has tests. Scoring changes add rows to `tests/data/value_cases.jsonl`.
- Documentation and `CHANGELOG.md` are updated when behaviour, commands or schemas change.
- The pull request closes exactly one work item.
````

### 8.3 Path-scoped instructions

Create these three files in M0-00 under `.github/instructions/`. The `applyTo` front matter limits each file to matching paths (section 12, R20).

`.github/instructions/python.instructions.md`

````markdown
---
applyTo: "src/**/*.py,tests/**/*.py,tools/**/*.py"
---
# Python

- Target Python 3.10 and later. Line length is 120.
- Add type hints to every function you add or change.
- Use `logging`, not `print`, in library code. Command output for the user goes through the CLI layer.
- Catch specific exceptions. Do not add `except Exception` unless the handler records the failure as `ERROR` evidence or re-raises.
- Tests use pytest, the simulated clock and the fakes. No network, no sleeping and no dependence on the current time.
- Keep `scorers.py` and `stats.py` standard-library only.
- Import optional SDKs inside the function that needs them.
- Do not add parameters to `EvalHarness.__init__` or `build_harness`. Extend `RunConfig` once work item M2-01 has introduced it.
````

`.github/instructions/app.instructions.md`

````markdown
---
applyTo: "app/**"
---
# Scorecard app

- Node 24 and strict TypeScript.
- `metrics.ts`, `normalize.ts` and `format.ts` use type-only imports, so they can run under `node --test` without the app framework.
- Metric definitions must match `pipeline.run_metrics` in Python. Change both sides together and update the parity fixture.
- Do not edit files under `app/overlay/src/eval/generated/` or the generated entity files. Regenerate them.
- Sample data comes from `python -m cfeval demo-data` with a fixed seed and `--as-of`. Do not edit `evals.json` by hand.
- The app makes no analytics or other third-party network calls.
````

`.github/instructions/docs.instructions.md`

````markdown
---
applyTo: "**/*.md,notebooks/**"
---
# Documentation and notebooks

- Write plain, complete sentences. Use one term per concept and follow `docs/reference/glossary.md`.
- Use product names as Microsoft Learn writes them. Label preview features as preview and give a "last verified" date.
- Use relative links inside the repository. Link to official documentation for product behaviour instead of restating it.
- No wording tied to one demo, meeting, date or person. `tools/check_public_wording.py` enforces the denylist.
- Do not claim support, certification or endorsement. Say what was tested and what was not.
- Commit notebooks without outputs. Notebooks install a tagged release, not the default branch.
- Change `docs/PLAN.md` only to tick a finished item or correct a fact, and say which in the pull request.
````

### 8.4 Pull request template

Replace `.github/PULL_REQUEST_TEMPLATE.md` with this text in M0-02.

````markdown
## Work item

Closes #

## What changed

-

## How it was verified

- [ ] `python -m pytest -q`
- [ ] `ruff check .` and `ruff format --check .`
- [ ] `python -m cfeval run --mock --option both --no-publish`
- [ ] Generated files regenerated, and `git diff --exit-code` is clean
- [ ] App: `npm run typecheck`, `npm run build`, `npm test` (only if `app/` changed)
- [ ] Documentation and `CHANGELOG.md` updated, or not needed (say why)

Summary lines from the commands above:

```text

```

## Unverified live behaviour

List each assumption this change makes about a live service, with the location of its `TODO(verify-live)`. Write "None" if there are none.

## Checklist

- [ ] No tenant IDs, user names, secrets or real answers
- [ ] Evidence integrity unchanged: `ERROR` and `INCONCLUSIVE` cannot become `PASS`
- [ ] No test, gate or check was weakened
- [ ] One work item only
````

## 9. Test strategy

The repository has no tests today, and its contribution rules forbid adding them (Appendix A, F-01). A tool that grades answers has to be graded itself, so the test toolchain (M1-01) comes before every other M1 change. Every layer except the last runs offline.

| Layer | What it proves | Location | When it runs | Work items |
|---|---|---|---|---|
| Unit | Scorers, statistics, name matching, configuration parsing and retry handling behave as specified | `tests/unit/` | Every push | M1-01, M1-03, M1-07, M1-10, M1-11 |
| Property-based | A number written in any supported format is extracted back to the same value | `tests/unit/`, using Hypothesis | Every push | M1-03 |
| Grader corpus: value check | False-pass and false-fail rates by category | `tests/data/value_cases.jsonl` | Every push | M1-02, M1-03 |
| Grader corpus: judge | Agreement of the judge with human labels | `data/judge_calibration/` | Offline against a fake judge on every push; against a real model when a person runs `cfeval judge calibrate` | M1-08 |
| Contract | Parsers and generators against recorded sample payloads and snapshots | `tests/contract/` | Every push | M1-13 |
| Offline end to end | Each simulation profile gives the expected verdicts and row counts | `tests/e2e_offline/` | Every push | M1-13 |
| Generated-file drift | The KQL script, app contract and reference entities match the schema | CI step | Every push | M1-14 |
| App | Scorecard metrics, normalisation and formatting, and parity with the Python metrics | `app/standalone/tests/` | Every push | M1-12 |
| Documentation | Markdown lint, links, wording denylist, and the quickstart notebook executes | CI steps | Every push | M0-01, M1-13, M1-14 |
| Live | Behaviour of the real services | `tests/live/`, marked `live` | Run by a person in a demo tenant. Never in CI | M4-02 |

**Fixture rules**

- Synthetic data only. Use Contoso names. Derive identifiers with `uuid5` from those names so they are stable and never resemble real tenant values.
- Use the simulated clock. A test must not sleep or read the current time.
- One fake per external client: chat, engine logs, Power BI query, judge, Foundry and the telemetry sink. Fakes live in `tests/` and implement the protocols in section 4.1.
- Recorded payloads are written by hand or reduced from public documentation samples. Do not record them from a real tenant.
- Each `TODO(verify-live)` in the code has a matching test in `tests/live/` that is skipped unless `CFEVAL_LIVE=1`. Register the `live` marker in M1-01.

**Coverage targets**

- At least 85% line coverage on the scoring, evidence and statistics modules (`scorers`, `scoring`, `stats`, `golden*`, `trace`, `artifacts`, `sinks`, `kqlgen`), and at least 70% overall (M1-13).
- The value corpus is the stronger measure: zero false passes and at most 5% false fails (release criterion 5 in section 3.1).

**What tests cannot show**

Offline tests prove that the harness is correct against its own simulation. They do not prove that a live service returns what the simulation assumes. That is the purpose of M4-02, and the reason every unverified assumption is tracked with `TODO(verify-live)`.

## 10. Documentation structure

Today the documentation is five long pages written around one scripted demonstration (Appendix A, F-21). The target structure separates learning, doing and looking up, so a customer architect, a field engineer and a contributor each find their page quickly. M2-04 implements it.

### 10.1 Target layout

```text
README.md                         what it is, offline quickstart, platform status, limitations
TRANSPARENCY_FAQ.md               intended use, limits, human review, what is stored (M2-05)
docs/
  PLAN.md                         this plan
  get-started/
    quickstart-offline.md         ten minutes, no sign-in, ends with the HTML report
    prerequisites.md              licences, roles, tenant settings, test user
    first-live-run.md             smallest live run in a demo tenant
    cost-and-limits.md            capacity, tokens, storage, duration (M2-05)
  concepts/
    how-it-works.md               targets, evidence, checks, verdicts; one diagram
    evidence-and-verdicts.md      what each evidence type can and cannot prove
    metrics.md                    every metric, its formula and its caveats
    limitations.md                every limitation in one place
  how-to/
    author-a-golden-set.md        (M2-08)
    capture-dax.md                (M1-09)
    calibrate-the-judge.md        (M1-08)
    compare-runs-and-gate-ci.md   (M1-06, M1-07)
    use-with-the-evaluations-cli.md   (M3-02)
    add-a-target.md               (M3-01)
    run-a-live-demo.md            the scripted demonstration, moved out of the main path
    deploy-the-scorecard-app.md   optional Fabric app
    troubleshoot.md
  reference/
    cli.md                        generated from `cfeval --help` (M2-01)
    configuration.md              generated from the settings class
    golden-schema.md              (M1-04, M1-05)
    telemetry-schema.md           generated from `schema.py`
    exit-codes.md                 (M1-06)
    platform-status.md            preview and GA status with a "last verified" date (M0-06)
    glossary.md
  responsible-use/
    threat-model.md               (M2-05)
  decisions/                      architecture decision records, one file each
  validation/                     sanitised live validation records (M4-02)
  architecture/                   one optimised diagram and its source (M0-03)
```

### 10.2 Where the current pages go

| Current page | Lines today | Moves to |
|---|---|---|
| `README.md` | 151 | Rewritten to the outline in 10.3 |
| `docs/ARCHITECTURE.md` | 122 | `docs/concepts/how-it-works.md`, with the reasoning split into `docs/decisions/` |
| `docs/METRICS.md` | 112 | `docs/concepts/metrics.md`, after the contradiction in M0-04 is resolved |
| `docs/SETUP.md` | 253 | `docs/get-started/prerequisites.md` and `docs/get-started/first-live-run.md` |
| `docs/DEMO.md` | 101 | `docs/how-to/run-a-live-demo.md` |
| `docs/TROUBLESHOOTING.md` | 70 | `docs/how-to/troubleshoot.md` |
| `app/README.md` | n/a | Stays; `docs/how-to/deploy-the-scorecard-app.md` links to it |

Leave a one-line pointer at each old path for one release, then delete it.

### 10.3 README outline

Keep it to about 150 lines. A reader should be able to decide in one minute whether the accelerator fits, and reach a scored offline run without opening another file.

1. Name and one-sentence purpose.
2. Status line: community accelerator, not a Microsoft product; preview dependencies (link to platform status).
3. What it answers: is the number right, did Copilot use the intended model, how stable is that across repeats, what changed since the last run.
4. How it works: one small diagram and four sentences.
5. Quickstart, offline: three commands, ending with the HTML report.
6. Run it against a tenant: link to prerequisites and first live run.
7. How it relates to Microsoft's tools: the Microsoft 365 Copilot Evaluations CLI, Foundry evaluations and Fabric data agent evaluation, and when to use each (section 12, R6, R12, R16).
8. Limitations: five bullets, with a link to the full page.
9. Responsible use, security and support links.
10. Contributing and licence.

### 10.4 Vocabulary

Use Microsoft's published evaluation vocabulary (section 12, R7) so readers who know the first-party tools are not asked to learn a second set of words. The glossary records the mapping.

| Term in the repository today | Term to use | Notes |
|---|---|---|
| question, golden question | test case | A test case holds a prompt and its expectations |
| golden set | test set | Keep "golden set" as a synonym in the glossary only |
| question text | prompt | |
| check, gate check | assertion, evaluated by a grader | "Gate" stays for the policy that decides which assertions are required |
| category, tags | quality signal | For example routing, numeric accuracy, refusal |
| reference DAX result | grounding data | The live value the answer is compared with |
| Option 1 fabric-native, Option 2 | Local scoring, Foundry Evaluations scoring | The current names do not say what differs, which is where scoring runs (F-24, M2-01) |

Rename in documentation and command output first. Keep existing table and column names in telemetry; changing them would break stored data (rule 8 in section 8.1).

## 11. Release and governance

### 11.1 Repository settings (manual)

The agent cannot change repository settings. A repository admin does these once, as part of M0-02.

- [ ] Description and topics are set.
- [ ] Issues are enabled. `SUPPORT.md` already sends users there, and today the link leads nowhere.
- [ ] Discussions are enabled, if the maintainers want a place for questions.
- [ ] Private vulnerability reporting is enabled. `SECURITY.md` already relies on it.
- [ ] Secret scanning and push protection are enabled.
- [ ] Dependabot alerts and security updates are enabled.
- [ ] `main` is protected: pull request required, status checks required, one approving review, no force push.
- [ ] Pushing version tags (`v*`) is limited to maintainers.
- [ ] The secret `CFEVAL_PRIVATE_DENYLIST` holds any private terms the wording check must also catch (M0-01).

### 11.2 Versioning and releases

- Follow Semantic Versioning. Stay on `0.x` until M4-04. A `0.x` release may change command names and configuration, and the changelog says when it does.
- From v1.0.0 the public contract is: the CLI commands and exit codes, the golden-set schema, the telemetry tables and columns, the configuration names and the target protocol.
- Telemetry changes are additive. A column is never renamed or retyped. `SchemaVersion` in `EvalRun` records the version that wrote the row.
- Deprecate before removing: warn for one minor release, list the deprecation in the changelog, then remove.
- Every release has a tag, a changelog entry, a wheel and a source distribution, with an SBOM and build provenance attached to the GitHub Release (M2-03). Publishing to PyPI stays off until decision D3.
- Supported runtimes are Python 3.10 to 3.13 (the CI matrix in M1-14) and Node 24 for the app.
- Re-verify `docs/reference/platform-status.md` within seven days before each release (M4-04). Most of the services this accelerator depends on are in preview.

### 11.3 Support stance and disclaimers

`README.md` and `SUPPORT.md` already say that this is a community accelerator, provided as-is under the MIT licence, that it is not a Microsoft product and that Microsoft does not support it. Keep that statement. Revisit it only if decision D2 moves the repository. Add the following, in `README.md`, `SUPPORT.md` and `TRANSPARENCY_FAQ.md`:

- Support is best effort through GitHub Issues. `SUPPORT.md` names the maintainers and says how quickly a first reply can be expected.
- The accelerator depends on preview features that can change or be withdrawn. `docs/reference/platform-status.md` is the one list of them.
- A result is evidence for a decision. It is not a certification, and it does not replace responsible AI review, security testing or user acceptance testing (section 12, R7).
- The harness stores Copilot's answers and query text in a store the user chooses. The user controls and is responsible for access to it.
- Issues and pull requests must not contain tenant identifiers, user names or real answers. The issue forms ask for confirmation.

### 11.4 Naming and branding

- Write product names in plain text, as Microsoft Learn writes them: for example "Microsoft 365 Copilot", "Fabric IQ" and "Microsoft Foundry". Keep the Trademarks section that is already in `README.md`.
- Do not add product logos or icons to the report, the app or the documentation. Check the architecture diagram for them when it is reworked in M0-03.
- Do not give the accelerator a name that suggests it is a feature of a Microsoft product. Decision D1 holds the default title.
- Describe environments as "demo tenant" and "demo Azure subscription".
- Reference other tools by link. Do not copy code, schemas or documentation text from a project whose licence does not allow it. The Microsoft 365 Copilot Evaluations CLI is published under Microsoft Software License Terms, so interoperate through its files and commands and do not vendor it (section 12, R6).

### 11.5 Maintainers and review

- Name at least two maintainers in `.github/CODEOWNERS` before v1.0.0, so that a review never waits on one person.
- Every change goes through a pull request that closes one work item, passes the required checks and has one approving review from a person. This includes pull requests opened by the agent.
- A person, not the agent, merges changes to scoring, gate policy and evidence handling. These decide verdicts, so they get the closest review.
- Use the labels in Appendix B.5 and the issue body in Appendix B.4, so that the backlog reads the same way as this plan.

## 12. Reference facts

Each fact below was read from the linked public page on 13 Nov 2026. Preview features change often. Re-check the page before relying on a fact, and record the new date in `docs/reference/platform-status.md`. Rule 2 in section 8.1 points here: if a service detail is not in this table or in the repository, the agent must not assume it.

### 12.1 Microsoft 365 Copilot and Fabric IQ

| # | Source | What it says | What it means for this plan |
|---|---|---|---|
| R1 | [Microsoft 365 Copilot Chat API overview (preview)](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview) | The API is in preview. Its documented capabilities are enterprise search grounding and web search grounding. It returns text only, does not support long-running tasks, and web grounding has to be switched off on every message. It is available to users with a Microsoft 365 Copilot add-on licence | The default target is a preview API whose documentation does not mention Power BI or Fabric IQ grounding. Confirm that behaviour in a demo tenant first (M4-02), keep targets pluggable (section 4.2, M3-01) and state the status plainly (M0-06) |
| R2 | [Chat API: continue a conversation](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat) | The operation is under `/beta`, and the page states: "Use of these APIs in production applications is not supported." Delegated permissions only. All of these are required: `Sites.Read.All`, `Mail.Read`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, `Chat.Read`, `ChannelMessage.Read.All`, `ExternalItem.Read.All` | No unattended app-only runs. The test user's token can read mail, chats and files, so use a dedicated account and document the risk (M2-05) |
| R3 | [Fabric IQ in Microsoft 365 Copilot Chat](https://learn.microsoft.com/en-us/fabric/iq/connectors/microsoft-365-copilot-overview) | The page describes data answering from Power BI content in Copilot Chat as generally available. Users need a Microsoft 365 Copilot Premium licence and Power BI access. Row-level and object-level security apply. Copilot may need to be told to use Power BI data. Attaching an item does not limit the answer to that item | Test named-source and unqualified prompts separately (M2-08). Ground truth has to be computed as the same user (M3-06) |
| R4 | [Ask Copilot for data from semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-ask-data-question) | Verified answers are not used when the question goes through Fabric IQ. The page advises defining, for each test question, the expected measure, grouping, date context, filters and result, and comparing answers with validated results | This is the published basis for the `intent` fields in the golden set (section 4.3) and for using reference DAX as ground truth |
| R5 | [Fabric IQ MCP server](https://learn.microsoft.com/en-us/fabric/iq/connectors/fabric-iq-mcp) | Endpoint `https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq`. Delegated permissions `Item.Read.All` and `Item.Execute.All`. Service principals are not supported. Clients should tolerate added tools and fields | Basis for the reference target in M3-03. Discover tools at run time and do not hard-code the list |
| R8 | [Semantic model operation logs](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/semantic-model-operations) | Columns include `ApplicationContext`, `ApplicationName`, `CorrelationId`, `ExecutingUser` and `OperationId`. The page documents no value that identifies Copilot as the caller | Engine evidence is a correlation, so it carries a confidence level (section 4.7, M1-09). Whether a stable marker exists is an open question (section 13.2) |
| R9 | [Workspace monitoring overview](https://learn.microsoft.com/en-us/fabric/fundamentals/workspace-monitoring-overview) | A workspace can send its data to the Eventhouse of another monitoring item. Data is kept for 30 days by default. Monitoring uses Fabric capacity | One monitoring item can serve several workspaces (M1-09). State the cost (M2-05). Tenants without monitoring need a citations-only gate policy (section 4.4) |
| R10 | [Copilot settings for semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-semantic-models) | Each model has its own Copilot setting. Restricted models are left out of search across models | A routing failure may be a setting, not a model-quality problem. `cfeval doctor` and the troubleshooting page should say so |
| R17 | Fabric updates blog: [advanced DAX generation in data agents](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/advanced-nl2sql-and-advanced-dax-generation-in-fabric-data-agents-generally-avai/5374654) and [retiring the data agent custom tool in Foundry](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/retiring-the-fabric-data-agent-custom-tool-in-microsoft-foundry-move-to-fabric-i/5374418) | Advanced DAX generation is generally available, with a rollout to the standard runtime between 2 and 10 Nov 2026. The custom tool in Foundry is being retired in favour of Fabric IQ, and responses are due to include the query that was used | Query generation is changing under the harness, so record dates with every run and compare against a baseline (M1-07). Returned queries would be stronger evidence than log correlation (M3-04) |
| R18 | Chris Webb's BI Blog (unofficial; a personal blog): [Copilot and DAX user-defined functions](https://blog.crossjoin.co.uk/2026/07/26/power-bi-m365-copilot-and-the-importance-of-dax-udfs/) and [queries run when the Copilot index is built](https://blog.crossjoin.co.uk/2025/11/02/monitoring-the-dax-queries-generated-when-the-power-bi-copilot-index-is-built/) | Copilot usually writes and runs DAX. Vague prompts give inconsistent results; DAX user-defined functions and AI instructions make them more consistent. Index-build queries also appear in the logs, as `SELECTCOLUMNS` over `VALUES` with a `LEN(...) <= 100` filter and the alias `"valueColumn"` | Repeats and paraphrase cases are necessary (M1-07, M2-08). Filter index-build queries out of the evidence (M1-09) |
| R19 | [Semantic model AI readiness guidelines](https://github.com/microsoft/skills-for-fabric/blob/main/skills/semantic-model-authoring/references/semantic-model-ai-readiness.md) (microsoft/skills-for-fabric) | Guidelines for preparing a semantic model for conversational experiences in Fabric | Link to it from failure explanations, so a failed case leads to a model fix |

### 12.2 Evaluation tools from Microsoft

| # | Source | What it says | What it means for this plan |
|---|---|---|---|
| R6 | Microsoft 365 Copilot Evaluations CLI: [repository](https://github.com/microsoft/m365-copilot-eval), [overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview), [evaluators](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-evaluators), [upgrade to v2](https://raw.githubusercontent.com/microsoft/m365-copilot-eval/main/docs/upgrade-to-v2.md) | Package `@microsoft/m365-copilot-eval`, command `runevals`. Version 1 evaluates deployed agents and needs Node 24.12 or later, a Copilot licence and tenant admin approval of a client app. The v2 upgrade guide describes a preview in which a run with no agent ID targets Microsoft 365 Copilot itself (`--target m365-copilot`), and `--evaluate-only` re-scores saved responses. Evaluators: Relevance, Coherence, Groundedness, Similarity, Citations, RetrievalQuery, RetrievalResult, ExactMatch, PartialMatch and custom. Licensed under Microsoft Software License Terms. The overview recommends starting with Work IQ Dev Tools (preview) for declarative agents | A first-party way to drive Copilot is arriving. Interoperate with it instead of competing (M3-02). None of its evaluators compares a number with live ground truth or checks which semantic model was queried, and that is what this accelerator adds. Do not vendor its code or schema. Whether the v2 preview is published to npm was not confirmed |
| R7 | [Agent evaluation overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluation-overview) | Vocabulary: test case, test set, prompt, assertion, quality signal, grader, grounding data. Suggested coverage: 20 to 50 cases for a prototype, 50 to 100 before production, more than 100 in production. Aim for an 80 to 90% pass rate, with core regression cases near 100%. Run several times and average. Evaluation does not replace responsible AI review or security testing | Use this vocabulary (section 10.4). Eight cases is below the lowest tier (F-06, M2-08). Repeats are expected (M1-07) |
| R11 | [Foundry custom evaluators (preview)](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/custom-evaluators) | Code evaluators must be under 256 KB, run for at most two minutes per call, have no network access and get 2 GB of memory. The examples call `project_client.beta.evaluators.create_version` | `scorers.py` stays small and standard-library only (rule 5 in section 8.1). Test the bundle size (M1-03, M3-05) |
| R12 | [Cloud evaluation with the Foundry SDK](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation) | How to run evaluations in the Foundry service from the SDK, and how to choose evaluators | Reference for the Foundry Evaluations scoring backend (M3-05) |
| R13 | [Foundry agent evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators) | Quality Grader is deprecated and can no longer be run in an evaluation | Treat built-in quality scores as diagnostics, not gates, and expect the evaluator list to change |
| R14 | [What's new in Microsoft Foundry, October 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-october-2026/) | Preview APIs were renamed and evaluation commands changed. The Decisions API became generally available on 22 Oct 2026 and returns typed answers for predicates, fixed choices and rubric scores with a confidence value. The "Microsoft Copilot harness" in that post is a managed agent loop inside Foundry; it is not a way to drive Microsoft 365 Copilot | Keep Foundry calls behind one module (M3-05). The Decisions API is a candidate for the binary judge verdict (M1-08). Do not describe the harness as a Copilot driver |
| R15 | PyPI: [azure-ai-projects](https://pypi.org/project/azure-ai-projects/), [azure-ai-evaluation](https://pypi.org/project/azure-ai-evaluation/), [fabric-data-agent-sdk](https://pypi.org/project/fabric-data-agent-sdk/) | Latest versions: `azure-ai-projects` 2.11.0 (2.5.0 and later need `openai>=3` and Python 3.10 or later), `azure-ai-evaluation` 1.18.12, `fabric-data-agent-sdk` 0.1.36a0 (needs `openai<3`) | The repository's pins hold the Foundry SDK at 2.4.x or older (F-11, M3-05). The data agent SDK and the current Foundry SDK cannot share an environment (M3-04) |
| R16 | [Evaluate a Fabric data agent (preview)](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent) | A notebook-based evaluation of a data agent against expected answers. Needs a paid F2 or higher capacity | The first-party route when the thing under test is a data agent. This accelerator covers the same question asked of Microsoft 365 Copilot |

### 12.3 GitHub Copilot

| # | Source | What it says | What it means for this plan |
|---|---|---|---|
| R20 | GitHub Docs: [custom instructions](https://docs.github.com/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot), [customise the agent environment](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-environment), [get the best results](https://docs.github.com/en/copilot/tutorials/cloud-agent/get-the-best-results) | Repository instructions live in `.github/copilot-instructions.md`. Path-specific instructions live in `.github/instructions/NAME.instructions.md` with an `applyTo` glob in the front matter. `AGENTS.md` files are read, and the nearest one applies. The environment is prepared by `.github/workflows/copilot-setup-steps.yml`, which needs a job named `copilot-setup-steps` and must be on the default branch. Issues should be well scoped with clear acceptance criteria | Sections 1 and 8, Appendix B.1, and the format of every work item in section 7 |

### 12.4 Method

| # | Source | What it says | What it means for this plan |
|---|---|---|---|
| R21 | [Adding Error Bars to Evals](https://arxiv.org/abs/2411.00640); [pass^k](https://arxiv.org/abs/2406.12045); [validating an LLM judge against human labels](https://hamel.dev/blog/posts/llm-judge/); [execution accuracy](https://arxiv.org/abs/2305.03111) | Report uncertainty with every score and compare paired results. Measure reliability as the share of cases that pass on all k attempts. Trust a judge only after measuring its agreement with human labels, using binary verdicts. Compare query results, not query text | Section 4.5 and M1-07; M1-08; ground truth from executed reference DAX |

### 12.5 Microsoft Ignite 2026

| # | Source | What it says | What it means for this plan |
|---|---|---|---|
| R22 | Session catalog, 17–20 Nov 2026, San Francisco. Pattern: `https://ignite.microsoft.com/en-US/sessions/<CODE>`, for example [BRK310](https://ignite.microsoft.com/en-US/sessions/BRK310) | Listed sessions: BRK310 "The evaluation loop for Microsoft IQ"; BRK356 "Microsoft IQ roadmap: The operating system for enterprise AI agents"; BRK306 "Fabric IQ: Trusted business context for enterprise AI"; BRK305 "Microsoft IQ: Build trusted AI agents that know your business"; BRK301 "Building context-aware agents with Microsoft IQ"; BRK304 "What's new in Work IQ"; LTG1214 "Observability for AI with Fabric Data Agent, Foundry, and Agent 365"; BRK249 "From traces to better agents: The Foundry improvement loop"; BRK251 "Agents in production: Observe, evaluate, and optimize with Foundry" | Only titles and abstracts were available when this plan was written. BRK310 is the closest to this accelerator's purpose and may introduce an official evaluation loop. M4-01 reviews these sessions before M3 starts |

## 13. Risks and open questions

### 13.1 Risks

| # | Risk | Why it is plausible | Mitigation in this plan |
|---|---|---|---|
| K1 | The Chat API changes, is withdrawn, or does not return answers grounded in Power BI content in a given tenant | It is a preview under `/beta`, and its documentation lists enterprise search and web grounding only (R1, R2) | Pluggable targets and an `import` target that scores answers captured any other way (section 4.2, M3-01). Interoperate with the Evaluations CLI (M3-02). Make this the first live check (M4-02). Show the status plainly (M0-06) |
| K2 | Microsoft ships a first-party evaluation for Copilot over Microsoft IQ | An Ignite session is titled "The evaluation loop for Microsoft IQ" (R22), and the Evaluations CLI is gaining a mode that targets Microsoft 365 Copilot (R6) | Review Ignite before building M3 (M4-01). Position the accelerator as the part first-party tools do not cover: numeric ground truth and routing evidence. Adopt Microsoft's vocabulary and file formats, so the scoring can sit behind another driver |
| K3 | Engine evidence is attributed to the wrong question | Queries are matched by user and time window, and no documented value identifies Copilot as the caller (R8) | Read more fields, exclude known noise, flag ambiguous matches as low confidence and offer a probe command (section 4.7, M1-09). Use a dedicated test user. The Fabric IQ MCP reference target records exact tool calls (M3-03) |
| K4 | The Evaluations CLI v2 file format changes before general availability | It is described as a preview (R6) | An independent reader and writer with versioned fixtures and contract tests. The doc states the CLI version the fixtures follow (M3-02) |
| K5 | SDK changes break the Foundry Evaluations scoring backend | Preview APIs were renamed in October 2026, and the SDK moved to a new major version of its `openai` dependency (R14, R15) | All Foundry calls in one module, contract tests with fakes for both API shapes, an "experimental" label until a live run is recorded (M3-05), and Dependabot (M0-02) |
| K6 | Judge verdicts drift when the judge model or prompt changes | The judge is a model, and nothing records its prompt version today (F-07) | Deterministic checks decide; the judge is secondary. Record the model, prompt hash and calibration ID with every run, and warn when a calibration record is missing (M1-08) |
| K7 | Cost and throttling at larger set sizes | 40 cases with 3 repeats is 120 questions, each followed by reference queries and judge calls | `cfeval plan` shows the size before anything is sent; resume, shards and a wall-time limit (M3-07). Correct handling of `Retry-After` (M1-11). A cost page (M2-05) |
| K8 | Sensitive content ends up in telemetry or in a public issue | The harness stores Copilot's answers and query text, and the test user's token is broad (R2) | A dedicated test user with no sensitive content, restricted access to the telemetry store, a threat model (M2-05), issue forms that require confirmation (M0-02), and synthetic data only in the repository |
| K9 | Readers treat a pass rate from a handful of cases as proof | The bundled set has 8 cases; published guidance starts at 20 to 50 (R7) | Always show the interval beside the rate (M1-07). Grow the bundled set to 40 or more (M2-08). One limitations page and a transparency FAQ (M2-04, M2-05) |
| K10 | The coding agent invents a field, endpoint or permission that looks right | The agent works offline and cannot check a live service | Rule 2 in section 8.1, `TODO(verify-live)` with a skipped live test, human review and merge of evidence and scoring changes (section 11.5), and live validation (M4-02) |
| K11 | Offline tests pass while the live path fails | The simulated tenant encodes assumptions about the services | Section 9 states the limit. Validation records in `docs/validation/` (M4-02). The Foundry backend and new targets stay "experimental" until validated |
| K12 | Licence or branding problems when sharing widely | The Evaluations CLI is not MIT licensed (R6); product names and logos have usage terms | No vendoring; reference by link (section 11.4). Complete an open-source release review if the repository moves to an organisation (D2, M4-03) |
| K13 | Maintainer capacity | Enabling Issues creates a support load for what is today a one-person repository | A best-effort support statement, issue forms, labels and at least two maintainers before v1.0.0 (sections 11.3 and 11.5) |
| K14 | The scorecard depends on a preview | The app is built for Fabric Apps, which `app/README.md` describes as a preview (F-25) | A self-contained HTML report is the default; the app is optional (D5, M2-06) |

### 13.2 Open questions to answer in a demo tenant

None of these can be answered offline, and none was answered during the review behind this plan. M4-02 records the answers in `docs/validation/`. Until then, treat each as unknown, and do not let code depend on a particular answer.

| # | Question | Why it matters | How to find out |
|---|---|---|---|
| Q1 | Does the Chat API return answers grounded in Fabric IQ, with Power BI citations, consistently? | The default target depends on it, and the API's documentation does not promise it (R1) | Ask ten named-source questions, three times each. Record the share of answers with a Power BI citation and with a matching engine query |
| Q2 | Is there a stable value in `ApplicationContext` or `ApplicationName` for queries that Copilot issued? | It would replace time-window matching with exact attribution (K3) | Run `cfeval trace probe` during a run, and compare with the same questions asked in the Copilot Chat interface |
| Q3 | Does the follow-up "why" turn cause extra queries or change routing? | If it does, it contaminates the evidence for the first turn | Run the same set with the follow-up on and off (already a scenario in M4-02) |
| Q4 | Do answers through the API match answers in the Copilot Chat interface for the same user and prompt? | Customers care about what users see, not what an API returns | Compare a sample by hand and record the differences |
| Q5 | Is the v2 preview of the Evaluations CLI published, and does its output include citations or tool traces? | It decides how much evidence the `import` target can score (M3-02) | Check the package's preview tag and run it against Microsoft 365 Copilot in a demo tenant |
| Q6 | Which evaluator API names does the Foundry SDK expose when M3-05 is done? | The code already carries a fallback between two names, and the preview API is still changing (R14) | Read the SDK changelog and run the contract tests against the installed version |
| Q7 | How long does a query take to appear in workspace monitoring? | The defaults today are a 20-second pause between questions, a 40-second settle interval and a 300-second deadline. Values that are too short lose evidence; values that are too long waste time | Measure the delay for 50 questions and set the defaults from the result |
| Q8 | Does row-level security give different, correct answers for two personas? | Ground truth must be computed as the same user (R3) | The two-persona scenario in M4-02 |

## Appendix A. Findings register

Evidence was gathered at commit `a9b0d39` by reading the code, running the offline paths and calling the scoring functions directly. Live paths were not run. Severity: **High** changes or blocks a verdict, or is unsafe to publish; **Medium** weakens trust or adoption; **Low** is polish.

| ID | Severity | Finding | Evidence | Fixed by |
|---|---|---|---|---|
| F-01 | High | No automated tests, and the contribution rules forbid adding them | `CONTRIBUTING.md` line 19 and `.github/copilot-instructions.md` line 16 say not to add a unit-test framework or broad test suites. There is no `tests/` folder. CI runs one offline smoke, a generated-file drift check and the app build | M0-00, M1-01, M1-13, M1-14 |
| F-02 | High | The value check uses the first number it finds, so correct answers fail | `score_value` in `src/cfeval/scorers.py` fails "Compared with $12.2M last year, gross revenue rose to $12.84M in FY2025." (it extracts $12.2M), "Revenue grew by $640K to $12.84M.", "Across 3 regions we sold 48,210 units in Q2 FY2025." and, for an expected 41.6 percent, "Gross margin was 0.416 in FY2025." Numbers written as `12.840.000` or `41,6 %` also fail | M1-02, M1-03 |
| F-03 | High | The display-rounding tolerance lets vague answers pass | "About $13M." passes for an expected 12,840,000 with `rel_tol` 0.005, because `max_display_rel` defaults to 0.05. A range, "between $12.8M and $12.9M", also passes | M1-02, M1-03 |
| F-04 | High | Without engine evidence, no answer can pass | `GATE_CHECKS = ("value", "artifact", "model")` is fixed in `src/cfeval/scoring.py` line 5. An offline run with `--no-trace` passes nothing: the baseline profile gives 5 fail and 3 inconclusive, the tuned profile 1 fail and 7 inconclusive, with the reason "model: required check did not return a score" | M1-06 |
| F-05 | High | One way to reach Copilot, through a preview API | `src/cfeval/chat.py` is the only driver. It calls the Copilot Chat API under Microsoft Graph `/beta`, which Microsoft says is not supported for production use and which is documented for enterprise search and web grounding (section 12, R1 and R2) | M0-06, M3-01, M3-02, M3-03 |
| F-06 | High | Results carry no statistics, and the bundled set is small | A `REPEATS` setting exists, but nothing aggregates per case, and there is no pass^k, interval or comparison between runs. The bundled set has 8 cases; Microsoft's guidance starts at 20 to 50 (R7) | M1-07, M2-08 |
| F-07 | Medium | The judge is not calibrated and its prompt is not versioned | `EvalRun` records `JudgeModel` only. There is no prompt hash, no labelled calibration set and no agreement measure | M1-08 |
| F-08 | Medium | Names are matched by word containment | `name_matches` in `src/cfeval/scorers.py` (line 207) returns true for the candidate "Sales Sandbox" against the target "Sales". An item whose name contains the expected name counts as a match. Item IDs are not compared | M1-10 |
| F-09 | Medium | Engine evidence is matched to a question by user and time window only | The capture filters the query log by `ExecutingUser` and the time window of the question, with a pause between questions (default 20 seconds). `OperationId` and `ApplicationContext` are not read. Questions must run one at a time, and any other activity by the same user would be attributed to the question | M1-09, M3-03, M3-07 |
| F-10 | Medium | Settings use unprefixed environment variable names | Names such as `OUTPUT_DIR`, `CLIENT_ID` and `REPEATS` are read as they are. During this review, an unrelated `OUTPUT_DIR` already set in the shell redirected the harness's output | M1-11 |
| F-11 | Medium | The Foundry and OpenAI pins are behind current releases | `pyproject.toml` pins `openai>=2,<3` and `azure-ai-projects>=2.2,<3`. That resolves to `azure-ai-projects` 2.4.x or older. The current release is 2.11.0 and needs `openai>=3` (R15) | M3-05 |
| F-12 | High | Wording tied to one demonstration and one tool | `src/cfeval/auth.py` line 139 builds a sign-in label that starts with the word `Scout`. `docs/SETUP.md` lines 49 and 165 and notebook 03 refer to "Friday". `docs/DEMO.md` line 5 and `docs/SETUP.md` line 204 say "during the meeting". `docs/DEMO.md` line 84 uses "NO-GO". Run summaries print the heading "Evidence gaps / still thin" | M0-01 |
| F-13 | Medium | Repository settings contradict the support policy, and community files are missing | Issues are disabled while `SUPPORT.md` tells users to open an issue. There is no description, topic, issue template, `CODEOWNERS`, `CHANGELOG.md` or Dependabot configuration | M0-02 |
| F-14 | Low | The bundled sample data holds two copies of most rows and cannot be regenerated identically; two assets are heavy | `app/overlay/public/sample-data/evals.json` (460 KB) holds 8 runs but 16 `EvalRun`, 128 `EvalQuestion` and 160 `EvalResult` rows: two copies of each. The two `EvalResult` copies share a `ScoredUtc` and differ only in `JudgeNotes` (present in one copy) and, in 34 of 80 pairs, in `Reasons`, so "latest row wins" cannot choose between them. `simulate_runs` in `src/cfeval/cli.py` uses the current time. The architecture image is 1.1 MB and its SVG 0.98 MB | M0-03 |
| F-15 | Medium | A KQL function contradicts the metric documentation | `LatencyBreakdown` in `src/cfeval/kql/functions.kql` (line 79) computes `NonDaxMs = LatencyMs - DaxTotalMs`. `docs/METRICS.md` line 78 says captured DAX time is not additive with answer latency | M0-04 |
| F-16 | Low | The app claims tests that do not exist | The header of `app/overlay/src/eval/metrics.ts` says the module is unit-tested with `node --test`. There are no test files, and `app/standalone/package.json` has no `test` script | M0-04, M1-12 |
| F-17 | Medium | The code is hard to maintain and extend | About 4,800 lines of Python with no type hints and docstrings on 19% of functions. `EvalHarness.__init__` takes 30 parameters and `build_harness` 19. Output is written with `print`. There are 10 `except Exception` handlers | M2-01, M2-02 |
| F-18 | Low | Small robustness bugs in HTTP and configuration handling | `float()` is applied to the `Retry-After` header in `chat.py` line 113, `fabric_rest.py` line 52 and `powerbi.py` line 40, which raises when the header is an HTTP date. The `.env` reader in `config.py` line 17 cuts a value at the first ` #` | M1-11 |
| F-19 | Medium | A case can expect only one number | There is no way to expect a list, a table, text, a refusal or a clarifying question, and no way to run as different personas to test row-level security | M1-04, M1-05, M2-08, M3-06 |
| F-20 | Low | Packaging is not ready for release | `license = { text = "MIT" }` is used instead of an SPDX expression. The version is declared in two places. `requirements.txt` repeats the extras. The notebooks install from the default branch with no pin | M2-03 |
| F-21 | Medium | The documentation is a runbook for one demonstration | Five pages, 658 lines in total, organised around a scripted live demo. No page gathers limitations, responsible use or cost, or explains how the accelerator relates to Microsoft's own evaluation tools | M2-04, M2-05 |
| F-22 | Medium | Supply-chain basics are missing | Workflows reference actions by tag (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`). There is no code scanning, no secret-scanning step and no Dependabot configuration | M0-05, M1-14 |
| F-23 | Medium | Publishing a run again is only partly safe | `cfeval publish` appends every table again. The KQL functions and the app keep the latest `EvalResult` and `EvalRun` rows, so pass rates are protected. Rows in `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalEvent` and `EvalScore` are doubled, and KQL functions that read those tables directly, such as `StageDurations` and `AskTimeline`, count them twice | M3-07 |
| F-24 | Low | The names of the two scoring paths do not say what differs | "Option 1 · Fabric-native" and "Option 2" appear in `README.md`, the CLI and the notebook names. What differs is where scoring runs: locally, or in Foundry Evaluations | M2-04 |
| F-25 | Low | The scorecard depends on a preview | The scorecard is built as an overlay for a Fabric app, and `app/README.md` describes Fabric Apps as a preview with availability gates. Outside Fabric, a run gives a Markdown summary and JSONL files, or the app can be previewed locally with Node 24 | M2-06 |

### A.1 How the scoring findings were reproduced

Run this from the repository root at the baseline commit. It needs no sign-in and no network.

```python
import sys
sys.path.insert(0, "src")
from cfeval.scorers import score_value, name_matches

cases = [
    ("Compared with $12.2M last year, gross revenue rose to $12.84M in FY2025.", 12840000, "currency", 0.005, 0.0),
    ("Revenue grew by $640K to $12.84M.", 12840000, "currency", 0.005, 0.0),
    ("Across 3 regions we sold 48,210 units in Q2 FY2025.", 48210, "count", 0.0, 0.0),
    ("Gross margin was 0.416 in FY2025.", 41.6, "percent", 0.0, 0.1),
    ("About $13M.", 12840000, "currency", 0.005, 0.0),
]
for answer, expected, unit, rel_tol, abs_tol in cases:
    result = score_value(answer, expected, unit=unit, rel_tol=rel_tol, abs_tol=abs_tol)
    print(result["outcome"], result.get("extracted"), "|", answer)

print(name_matches("Sales Sandbox", "Sales"))
```

The first four answers are correct and are reported as failures. The fifth is too vague to check at a tolerance of 0.5% and is reported as a pass. The last line prints `True`.

## Appendix B. Sample files

These are starting points. The agent may adjust them, but must keep what the comments mark as required.

### B.1 `.github/workflows/copilot-setup-steps.yml`

Used by M0-00. It mirrors the install steps that already pass in `ci.yml`.

```yaml
name: Copilot Setup Steps

# Runs when this file changes, so a broken setup is caught in review,
# and can be started by hand from the Actions tab.
on:
  workflow_dispatch:
  push:
    paths:
      - .github/workflows/copilot-setup-steps.yml
  pull_request:
    paths:
      - .github/workflows/copilot-setup-steps.yml

jobs:
  # Required: the job must be named copilot-setup-steps.
  copilot-setup-steps:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Check out the repository
        uses: actions/checkout@v4            # pin to a commit SHA in M0-05
      - name: Set up Python
        uses: actions/setup-python@v5        # pin to a commit SHA in M0-05
        with:
          python-version: "3.12"
      - name: Set up Node
        uses: actions/setup-node@v4          # pin to a commit SHA in M0-05
        with:
          node-version: "24"
      - name: Install the harness
        run: python -m pip install -e .      # change to ".[dev]" in M1-01
      - name: Install app dependencies
        working-directory: app/standalone
        run: npm ci --no-audit --no-fund
```

### B.2 `.github/ISSUE_TEMPLATE/bug.yml`

Used by M0-02.

```yaml
name: Bug report
description: Something in the harness, the scorecard or the docs does not work as described
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Do not include tenant IDs, user names, tokens, real answers or customer data. Use placeholders.
        For problems with Microsoft 365 Copilot, Microsoft Fabric or Microsoft Foundry themselves, use those products' support channels.
  - type: input
    id: version
    attributes:
      label: Version
      description: Output of `python -m cfeval --version`, or the commit you are on
    validations:
      required: true
  - type: dropdown
    id: mode
    attributes:
      label: Where it happens
      options:
        - Offline run (--mock)
        - Live run in a tenant
        - Scorecard app
        - Documentation
    validations:
      required: true
  - type: textarea
    id: command
    attributes:
      label: Command and output
      description: The command you ran, the error, and the output of `python -m cfeval doctor` with identifiers removed
      render: text
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: What you expected, and what happened instead
    validations:
      required: true
  - type: checkboxes
    id: confirm
    attributes:
      label: Confirmation
      options:
        - label: This report contains no tenant IDs, user names, secrets or real answers
          required: true
```

### B.3 `.github/dependabot.yml`

Used by M0-02.

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
    groups:
      python-minor-and-patch:
        update-types: ["minor", "patch"]
  - package-ecosystem: npm
    directory: /app/standalone
    schedule:
      interval: weekly
    groups:
      npm-minor-and-patch:
        update-types: ["minor", "patch"]
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    groups:
      actions:
        patterns: ["*"]
```

### B.4 Issue body for a work item

Create one issue per work item in section 7. Use the item's heading as the issue title, for example "M1-03 · Value extraction v2". Copy the item's text; do not rewrite it.

```markdown
## Work item

`M1-03` in `docs/PLAN.md` · type: agent · size: M · depends on: #<issue number for M1-02>

## Context

Two or three sentences from the plan: what is wrong today and why it matters. Name the finding IDs.

## Change

- The "Change" bullets from the plan, unchanged.

## Done when

- [ ] The "Done when" boxes from the plan, unchanged.

## Constraints

- Follow `.github/copilot-instructions.md` and `AGENTS.md`.
- Offline only. Mark anything you cannot verify with `TODO(verify-live)` and list it in the pull request.
- Files likely to change: `src/cfeval/scorers.py`, `tests/unit/`, `tests/data/value_cases.jsonl`.

## Out of scope

Anything that belongs to another work item. Name that item; do not do its work here.
```

### B.5 Labels

| Label | Use |
|---|---|
| `milestone:M0` to `milestone:M4` | Exactly one per issue |
| `type:agent` | Can be assigned to the Copilot cloud agent |
| `type:manual` | Needs a person with repository-admin or tenant access |
| `area:scoring`, `area:evidence`, `area:targets`, `area:telemetry`, `area:app`, `area:docs`, `area:ci`, `area:governance` | One or more per issue |
| `needs-live-validation` | Merged with a `TODO(verify-live)`; closed out in M4-02 |
| `blocked` | Waiting on a decision in section 5, or on another item |

A repository admin can create them with the GitHub CLI:

```bash
for name in milestone:M0 milestone:M1 milestone:M2 milestone:M3 milestone:M4 \
            type:agent type:manual needs-live-validation blocked \
            area:scoring area:evidence area:targets area:telemetry \
            area:app area:docs area:ci area:governance; do
  gh label create "$name" --force
done
```

---

*End of plan. Source of every repository fact: commit `a9b0d39`. Source of every product fact: the public pages in section 12, read on 13 Nov 2026.*
