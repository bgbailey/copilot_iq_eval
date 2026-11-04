# Tests

| Folder | What it holds | Network |
|---|---|---|
| `unit/` | Fast tests with fakes for every adapter; tests that execute each evaluator file the way the Foundry sandbox does; and tests that the local backend applies the evaluation definition as Foundry does. | Never |
| [`contract/`](contract/README.md) | Adapters parsing recorded, sanitised responses from external services. | Never |
| [`fixtures/`](fixtures/README.md) | Recordings and sample inputs for both. | n/a |

Run everything with `uv run pytest` (add `--cov` for coverage). Tests that need a live tenant are marked `@pytest.mark.live` and never run in CI.
