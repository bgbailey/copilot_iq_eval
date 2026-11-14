# Offline Quickstart (Zero Cloud Credentials)

Run an end-to-end `cfeval` evaluation, generate an HTML scorecard, and compare two simulated model configurations (`untuned` vs `tuned`) in under 60 seconds with no Microsoft 365, Azure, or Fabric credentials.

## Prerequisites

- Python `3.11+` (`3.10+` supported)
- A local clone of `copilot_iq_eval`

## 1. Install the Package

```powershell
python -m pip install -e ".[dev]"
```

## 2. Run `untuned` vs `tuned` Offline Profiles

The simulated tenant (`--mock`) models realistic answer formatting, semantic-model routing, decoy-model confusion (`untuned`), and Workspace Monitoring DAX traces:

```powershell
python -m cfeval run --mock --profile untuned --golden data/golden/contoso-smoke.yaml --run-id quickstart-untuned --no-publish
python -m cfeval run --mock --profile tuned   --golden data/golden/contoso-smoke.yaml --run-id quickstart-tuned   --no-publish
```

Each run writes structured JSONL artifacts (`EvalRun.jsonl`, `EvalQuestion.jsonl`, `EvalAsk.jsonl`, `FabricIqQuery.jsonl`, `EvalScore.jsonl`, `EvalResult.jsonl`, `EvalEvent.jsonl`) under `runs/<run-id>/`.

## 3. Generate a Self-Contained HTML Scorecard

```powershell
python -m cfeval report --run-dir runs/quickstart-tuned --out runs/quickstart-tuned/report.html
```

Open `runs/quickstart-tuned/report.html` in any browser to inspect pass rates, Wilson 95% confidence intervals, routing evidence tiers, and per-question DAX traces.

## 4. Run a Paired Regression Comparison

```powershell
python -m cfeval compare --baseline runs/quickstart-untuned --candidate runs/quickstart-tuned
```

`compare` highlights question-level flips (`FAIL → PASS` and `PASS → FAIL`), latency deltas, and the paired McNemar `p`-value.

## 5. Run the Full 42-Question Contoso Benchmark or Work IQ Suite

```powershell
# 42-question Fabric IQ suite across scalar, ranked_list, set, table, record, direction, citation_only, abstention
python -m cfeval run --mock --golden data/golden/contoso.yaml --no-publish

# 22-question M365 Work IQ workplace document suite
python -m cfeval run --mock --golden data/golden/contoso-work.yaml --no-publish
```

## Next Steps

- Explore interactive notebooks starting with [`notebooks/00_offline_quickstart.ipynb`](../../notebooks/00_offline_quickstart.ipynb).
- Score pre-captured answers without mock synthesis in [Transcript Import Quickstart](quickstart-transcript-import.md).
- Connect a live demo tenant in [Live Copilot Chat Quickstart](quickstart-live-copilot-chat.md).
