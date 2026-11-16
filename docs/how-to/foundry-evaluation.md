# How to Run Azure AI Foundry Evaluations (Option 2)

`cfeval` supports two complementary scoring backends over the exact same captured turns and golden set:

- **Option 1 (`--option fabric-native`, default):** Deterministic local v2 scorers (`value`, `artifact`, `model`) plus optional LLM explanation judge. Zero Foundry project required.
- **Option 2 (`--option foundry` or `--option both`):** Uploads the captured run dataset to your **Azure AI Foundry** project, executes custom code evaluators alongside built-in Foundry quality evaluators (`Coherence`, `Fluency`, `Relevance`, `Groundedness`), and writes normalized rows back to `EvalScore` and `EvalResult`.

## Prerequisites

1. An Azure AI Foundry project endpoint (`https://<resource>.services.ai.azure.com/api/projects/<project>`) and deployed chat judge model (for example `gpt-4o`).
2. `azure-ai-evaluation` and `azure-ai-projects` extras installed:

   ```powershell
   python -m pip install -e ".[foundry,judge]"
   ```

3. Azure credentials signed in to the target tenant (`az login --tenant <tenant-id>`) with `Azure AI Developer` role on the Foundry project.

## Configure `.env`

```ini
CFEVAL_FOUNDRY_PROJECT_ENDPOINT=https://contoso-foundry.services.ai.azure.com/api/projects/copilot-eval
CFEVAL_JUDGE_ENDPOINT=https://contoso-foundry.openai.azure.com
CFEVAL_JUDGE_DEPLOYMENT=gpt-4o
```

## Run Option 2 or Side-by-Side Comparison

Score a fresh mock or live run through Foundry:

```powershell
python -m cfeval run `
  --mock `
  --option both `
  --golden data/golden/contoso-smoke.yaml `
  --run-id foundry-compare-01 `
  --no-publish
```

Or re-score an already captured `runs/<run-id>/` directory without re-asking Copilot Chat:

```powershell
python -m cfeval rescore runs/live-fabric-iq-01 --option foundry
```

## Calibrate LLM Judges Before Using Judge Verdicts as Gates

Built-in and prompt-based LLM judges are **diagnostic by default** (`CFEVAL_JUDGE_GATES_VERDICT=false`). Before promoting a judge rubric to a blocking CI threshold:

1. Label 25–50 representative turns (`PASS` / `FAIL`) in a JSONL calibration set.
2. Run:

   ```powershell
   python -m cfeval calibrate-judge --dataset data/judge_calibration/answers.jsonl
   ```

3. Confirm **Cohen's kappa `κ >= 0.70`** before setting `CFEVAL_JUDGE_GATES_VERDICT=true`. See [ADR 0002: Deterministic-First Scoring](../decisions/0002-deterministic-first-scoring.md).
