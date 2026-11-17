# Notes for AI coding agents

This is a teaching accelerator. Keep it simple: a reader should understand the whole method in an afternoon.

## Layout

| Path | What it is |
|---|---|
| `eval/run_eval.py` | Entry point: ask, collect evidence, score, store |
| `eval/scoring.py` | The three checks and the verdict. No network calls |
| `eval/copilot.py` | Sign-in as the test user and the Copilot Chat API |
| `eval/fabric.py` | Reference DAX, workspace monitoring KQL, Eventhouse ingestion |
| `questions.yaml` | Golden questions |
| `eventhouse.kql` | Results tables and helper functions; column order must match `run_eval.py` |
| `sample/` | Saved answers and the synthetic Contoso CSVs |
| `app/` | Scorecard pages applied on top of a Rayfin project |
| `docs/` | Deployment guide and diagrams |

## Rules

- Prefer plain functions and the standard library. Don't add frameworks, plugin systems, test suites or CI pipelines.
- Keep the Python under about 500 lines in total. If a change needs more, it probably belongs in a separate project.
- Keep `README.md`, `docs/deployment-guide.md` and `app/README.md` accurate whenever you change commands, settings, file names or table columns.
- Run `python eval/run_eval.py --answers sample/answers-before.jsonl --no-publish` after changing the scoring; it should pass 2 of 8 questions.
- Never commit secrets, tenant IDs, real user names or customer data. Use Contoso placeholders.
- For Microsoft Fabric work (Eventhouse, Lakehouse, shortcuts, semantic models, KQL), use the current Microsoft Fabric skills from https://github.com/microsoft/skills-for-fabric.
