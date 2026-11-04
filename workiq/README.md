# Work IQ content pack

The Microsoft 365 documents the joint Work IQ + Fabric IQ cases rely on ([PLAN §4.4](../docs/PLAN.md#44-work-iq-content-joint-work-iq--fabric-iq-cases-adr-010), [ADR-010](../docs/decisions/ADR-010-joint-work-iq-fabric-iq-evaluation.md)). Business questions often need a certified figure **and** a document: "Did we hit our FY2025 gross revenue target?" needs the actual from the Sales Analytics model and the target from an approved planning memo. The joint cases check that Copilot takes each from the right source, cites both, and never uses the draft.

All content is synthetic: Contoso is a fictional company.

| Document | Site, folder | Readers | Role | States |
|---|---|---|---|---|
| [`FY2025 Revenue Targets - APPROVED.docx`](documents/FY2025%20Revenue%20Targets%20-%20APPROVED.docx) | Contoso Planning, `Planning/FY2025` | exec, east | source | company target $12,500,000; regional targets |
| [`FY2025 Service Level Objectives.docx`](documents/FY2025%20Service%20Level%20Objectives.docx) | Contoso Planning, `Planning/FY2025` | exec, east | source | Sev1 objective 6 hours; Sev2 16 hours |
| [`FY2025 revenue - DRAFT.docx`](documents/FY2025%20revenue%20-%20DRAFT.docx) | Contoso All Company, `Finance Drafts` | all personas | decoy | "about $13,600,000" (wrong on purpose) |

## How it fits together

| File | What it holds |
|---|---|
| [`content.yaml`](content.yaml) | The sites with their readers, and each document's site, folder and text. `{fact}` placeholders stand for figures. |
| [`../evals/golden/models.yaml`](../evals/golden/models.yaml) `documents` | Each document's title, role, match fragments and **facts**: the single source of every figure. |
| [`documents/`](documents) | The built `.docx` files, committed so seeding needs no extra library. |
| [`../scripts/build_workiq_documents.py`](../scripts/build_workiq_documents.py) | Renders the documents from the two files above (python-docx, a dev dependency). |
| [`../tests/unit/test_workiq_content.py`](../tests/unit/test_workiq_content.py) | Fails if a document, a fact, a title or a site's readers drift, or if a persona without data access could read a source document. |

The calibrated data in nb_01 makes the comparisons real: actual $12.84M against the $12.5M target; Sev1 mean time to resolve 7.2 hours against the 6-hour objective.

## Change the content

1. Edit the text in `content.yaml`, or a figure in `models.yaml` (a figure's case expectations may change with it).
2. Rebuild: `uv run python scripts/build_workiq_documents.py`.
3. Check: `uv run pytest tests/unit/test_workiq_content.py` and `uv run evals validate --strict`.
4. Re-seed: `uv run evals deploy workiq`.

## Seed the documents

Create the two sites with the readers above as members, add their URLs to `[workiq.sites]` in `config/settings.toml`, then:

```bash
uv run evals deploy workiq --dry-run
uv run evals deploy workiq
uv run evals deploy workiq --verify
```

Copilot finds a new document only after the Microsoft 365 semantic index has processed it; allow up to a day. Spike S8 measures the delay ([docs/deployment.md](../docs/deployment.md#5-seed-the-work-iq-content)).
