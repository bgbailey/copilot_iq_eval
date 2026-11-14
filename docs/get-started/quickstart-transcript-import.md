# Transcript Import Quickstart

Score answers you already captured—from manual pilot testing, exported M365 Copilot transcripts, or another BI/chat assistant—using `cfeval`'s deterministic scorers and HTML reports with zero live API calls.

## Input Format (`JSONL` or `CSV`)

Each row supplies a question identifier (`id`, `question_id`, or `case_id`) matching your golden YAML/CSV, the `answer` text, and optional `citations`:

```json
{
  "id": "Q01",
  "question": "What was gross revenue in FY2025 in the Sales Analytics report?",
  "answer": "Gross revenue in FY2025 was $12.84M ($12,840,000) per Sales Analytics.",
  "citations": [{"name": "Sales Analytics", "kind": "powerbi_report", "url": "https://app.powerbi.example/reports/sales-analytics"}],
  "user": "eval.tester@contoso.com",
  "latency_ms": 4100.0
}
```

## 1. Score the Bundled Contoso Fabric IQ Transcript

```powershell
python -m cfeval run `
  --target transcript-import `
  --transcript samples/contoso/transcript_sample.jsonl `
  --golden data/golden/contoso-smoke.yaml `
  --run-id contoso-transcript-01 `
  --no-publish
```

## 2. Score the Bundled Work IQ Transcript

```powershell
python -m cfeval run `
  --target transcript-import `
  --transcript samples/work-iq/transcript_sample.jsonl `
  --golden data/golden/contoso-work.yaml `
  --run-id workiq-transcript-01 `
  --no-publish
```

## 3. Render HTML & JUnit Outputs

```powershell
python -m cfeval report --run-dir runs/contoso-transcript-01
```

## Routing Evidence Tier Behavior

Because imported transcripts do not include engine-side `SemanticModelLogs` telemetry, `cfeval` stamps every turn with `routing_evidence_tier = "citations-only"` (when citations are present) or `"none"` (when absent). See [Surfaces and Evidence Tiers](../concepts/surfaces-and-evidence.md) for details on how `model` gates treat `citations-only` evidence.
