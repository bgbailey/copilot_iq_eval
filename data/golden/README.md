# Golden question set

`golden_questions.csv` preserves the original **Q01–Q08 fictional baseline** and its sample-history contract.
It uses a Contoso estate with three certified semantic models (**Sales Analytics**, **Finance**, **Service
Operations**) and one decoy (**Sales Sandbox**). Its numbers are illustrative, not your tenant's reference values.
Create a separate CSV from `demo_questions.template.csv`; do not rewrite baseline prompts or relabel old runs.

| Column | Required | Meaning |
|---|---|---|
| `id` | Yes | Stable, unique ID (for example `Q01`). Never reuse an ID for a different question. |
| `question` | Yes | Exactly what is sent to Copilot Chat. |
| `category` | No | Free label for slicing results (for example `routing`, `time-intelligence`). |
| `expected_artifact` | Recommended | Report or semantic model Copilot should cite. Matched case-insensitively against citation names; an item GUID also works. |
| `artifact_aliases` | No | Other acceptable names, separated by `;`. |
| `expected_model` | No | Semantic model that Fabric IQ should query (DAX capture). Defaults to `expected_artifact`. |
| `decoys` | No | Reports, models or documents that must **not** be used, separated by `;`. |
| `expected_value` | Recommended | The correct number. Percentages are in percentage points (41.6 for 41.6%). |
| `unit` | No | `currency`, `percent`, `count` or `number` (default). Picks which number in the answer is checked. |
| `rel_tol`, `abs_tol` | No | Relative and absolute tolerance. Answers rounded for display (for example `$12.8M`) also pass. |
| `expected_answer` | No | Reference sentence, used by AI-judged checks. |
| `reference_dax` | No | DAX that returns the expected value as a single cell. `python -m cfeval golden-refresh --write` runs it (as the notebook identity or your Azure CLI account, which needs Build permission on the model) and updates `expected_value`. |
| `criticality` | No | `critical` or `standard`, for reporting. |
| `notes` | No | Why the question is in the set. |

Tips:

- Mix questions that name the source with questions that don't, so you measure routing as well as accuracy.
- Add a decoy (a stale copy or a draft document the test user can see) to prove Copilot avoids unofficial sources.
- Preview reference values with `python tools/setup_demo.py --env .env --refresh-golden`; add `--apply` only after
  configuring a separate CSV. Review `expected_answer` with the numeric golden; refresh does not rewrite prose.
- In a Fabric notebook, upload the CSV to the lakehouse Files area and set `GOLDEN_SET=/lakehouse/default/Files/golden_questions.csv`.
- The package ships a byte-identical baseline copy (`src/cfeval/sample/`) for offline use. Keep it synchronized.
  The live rehearsal refuses the bundled/public baseline and unresolved/uncalibrated templates.

## Positive path versus diagnostic history

The template's eight `DEMO*` IDs are placeholders for a **new** demonstration set. Assign new stable IDs after
finalizing actual prompts; replace every `CALIBRATE` reference, fill single-cell `reference_dax`, and calibrate
against the retained model. Do not copy a private demo's tenant bindings or numeric calibration into the public sample.

Keep named-source Service Operations **Sev1 count** and **MTTR in hours** controls distinct from the original
unqualified Q06/Q07. Named-source success demonstrates reachability, not repaired general discovery.
Keep an unqualified certified-source routing case and the sandbox-decoy check. Do not promise or fabricate
a particular live negative outcome.

Original Q08 (“latest quarterly revenue”) is deliberately retained as an ambiguity diagnostic: gross/net,
source and completed-quarter/as-of rules were not explicit. A plausible Finance/net answer is not automatically
a hallucination. A positive Sales case must name **Sales Analytics, gross revenue, latest completed fiscal quarter
and a fixed as-of cutoff**. Derive the actual fiscal period and reference value from that model, not an unbounded
calendar maximum or today's date, and use a new ID.

## Evidence gaps / still thin

These are prompt/reference templates, not measured results or an asserted Service Operations root cause.
Owner calibration does not verify the actual licensed test user's access, applicable RLS, or Copilot routing.
