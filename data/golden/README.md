# Golden Evaluation Suites (Schema v2)

This directory holds the synthetic Contoso golden suites used by `cfeval` for offline simulation, transcript validation, and demo-tenant calibration. All figures and documents are 100% fictional (`@contoso.com`) and contain no real tenant identifiers.

## Bundled Suites

| File | Cases | Surface | Purpose |
|---|---|---|---|
| `contoso.yaml` | 42 (`Q01`–`Q42`) | `copilot-chat` / Fabric IQ | Full v2 benchmark covering scalar KPIs, YoY/QoQ growth, margins (`%` and `bps`), rankings, sets, tables, records, directional trends, citations, and policy abstentions across Contoso Sales, Finance & Quota, and Ops & Supply Chain models. `Q01`–`Q08` match the original 8-case baseline verbatim. Synchronized identically with `src/cfeval/sample/contoso.yaml`. |
| `contoso-smoke.yaml` | 8 (`Q01`–`Q08`) | `copilot-chat` / Fabric IQ | Fast 8-question smoke suite preserving the original `Q01`–`Q08` baseline contract for sub-10-second CI checks and quickstarts. |
| `contoso-work.yaml` | 22 (`W01`–`W22`) | `work-iq` | Synthetic Microsoft 365 Work IQ grounding suite over Contoso SharePoint strategy notes, OneDrive board presentations, Teams meeting recaps, and Outlook escalation threads (`samples/work-iq/`). |
| `golden_questions.csv` | 8 (`Q01`–`Q08`) | `copilot-chat` | Legacy v1 CSV fixture retained for backward-compatibility tests. |
| `demo_questions.template.csv` | 8 (`DEMO01`–`DEMO08`) | `copilot-chat` | Starter template for calibrating a custom CSV against your own semantic models. |

## Schema v2 Overview

Each v2 YAML suite declares `version: 2`, optional suite-level `defaults` (`surface`, `gates`, `rel_tol`), and a `questions` list validated by `schemas/golden.schema.json`:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Stable case identifier (`Q01`–`Q42`, `W01`–`W22`). Never reuse an existing ID when changing a prompt's meaning. |
| `question` | Yes | Exact prompt sent to the target surface. |
| `case_type` | No | `scalar` (default), `ranked_list`, `set`, `table`, `record`, `direction`, `citation_only`, or `abstention`. |
| `category` | No | Slicing label (`named-source`, `routing`, `time-intelligence`, `margins`, `quota`, `supply-chain`, `governance`, etc.). |
| `persona` | No | Role context (`finance-analyst`, `sales-leader`, `ops-manager`, `executive`). |
| `intent` | No | Structured analytical intent block (`{measure, grouping, date_context, filters}`). |
| `tags` | No | List of free-form tags for cohort reporting. |
| `expected` | Conditional | Expected numeric scalar (or `null` when `expect` is structured or `case_type` is `abstention` / `citation_only`). |
| `expect` | Conditional | Structured expectation payload for `ranked_list` (`{items, top_n, ordered}`), `set` (`{items}`), `table` (`{key, rows}`), `record` (`{fields}`), or `direction` (`{direction: up|down|flat}`). |
| `unit` | No | `currency`, `percent`, `bps`, `count`, `days`, `hours`, or `number`. |
| `rel_tol`, `abs_tol` | No | Relative and absolute numeric tolerances. |
| `expected_artifact` | Recommended | Certified report, semantic model, or workplace document expected in citations. |
| `artifact_aliases` | No | Additional acceptable artifact titles or file names. |
| `expected_model` | No | Semantic model expected in engine DAX logs (Fabric IQ surfaces). |
| `decoys` | No | Stale sandboxes or draft files that fail routing gates if cited or queried. |
| `reference_dax` | No | Single-table or `EVALUATE ROW(...)` DAX query computing live ground truth from the semantic model. |
| `gates` | No | Per-case gate override (for example `[value]` on `abstention`, `[value, artifact]` on `citation_only`). |
| `criticality` | No | `"standard"` (default), `"critical"`, or `"advisory"`; critical failures can block CI regression gates (`max_critical_failures: 0`). |
| `paraphrases` | No | Alternate phrasings of the same analytical intent for robustness testing. |

## Authoring Guidance

- **Mix named-source and unqualified prompts**: named-source cases verify reachability and measure definitions; unqualified cases test cross-workspace discovery and decoy avoidance.
- **Pair positive lookups with abstentions**: include out-of-model prompts (competitor compensation, uncollected PII, unannounced M&A) so overly eager fabrication fails deterministically.
- **Keep packaged samples synchronized**: whenever `data/golden/contoso.yaml` changes, copy it byte-for-byte to `src/cfeval/sample/contoso.yaml`.
- **Calibrate live suites in a separate file**: copy a template rather than editing `Q01`–`Q08` in place so baseline comparisons remain valid. See [`../../docs/how-to/author-golden-sets.md`](../../docs/how-to/author-golden-sets.md) for full authoring instructions.

## Limitations

Bundled Contoso numbers are deterministic synthetic fixtures verified by `samples/contoso/seed_contoso.py --verify`. Passing offline mock runs validates harness scoring and gate logic, not live tenant permissions, row-level security, or Copilot routing behavior.
