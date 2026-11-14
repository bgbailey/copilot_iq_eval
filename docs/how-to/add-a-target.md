# Add a Custom Target

`cfeval` decouples prompt execution from telemetry collection and deterministic scoring via the runtime-checkable `Target` protocol in `src/cfeval/interfaces.py`. You can evaluate any custom REST agent, Microsoft Foundry orchestrator, Copilot Studio bot, or internal analytics API without forking `cfeval`.

## 1. Implement the `Target` Protocol

Create a class exposing `name`, `surface`, `supports_engine_trace`, and `ask(...) -> TargetTurn`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cfeval.interfaces import TargetTurn


class CustomAnalyticsAgentTarget:
    """Evaluate an internal analytics endpoint with cfeval's deterministic gates."""

    name = "custom-analytics-agent"
    surface = "custom-agent"
    supports_engine_trace = True  # Set False if Workspace Monitoring does not apply
    experimental = False

    def __init__(self, endpoint_url: str = "", **kwargs: Any) -> None:
        self.endpoint_url = endpoint_url

    def ask(
        self,
        question: Any,
        *,
        attempt: int = 1,
        explain_mode: str = "followup",
        persona: str = "",
    ) -> TargetTurn:
        prompt = question["question"] if isinstance(question, dict) else getattr(question, "question", str(question))
        started = datetime.now(timezone.utc)

        # Invoke your agent or deterministic test fake here.
        # Keep unit/contract tests 100% offline; never invent undocumented upstream fields.
        answer_text = "Contoso total gross revenue in FY2025 was $12.84M."
        citations = [
            {
                "title": "Core Sales",
                "url": "https://app.powerbi.com/groups/me/reports/00000000-0000-0000-0000-000000000010",
            }
        ]
        tool_calls = [
            {
                "name": "query_semantic_model",
                "arguments": {"model_name": "Core Sales"},
            }
        ]

        ended = datetime.now(timezone.utc)
        latency_ms = (ended - started).total_seconds() * 1000.0

        return TargetTurn(
            question=prompt,
            answer_text=answer_text,
            attributions=citations,
            artifacts=citations,
            conversation_id=f"conv-{attempt}",
            started=started,
            ended=ended,
            latency_ms=latency_ms,
            http_status=200,
            tool_calls=tool_calls,
            routing_evidence="tool_call",
        )
```

### Key `TargetTurn` Contract Rules

* **Timestamps (`started`, `ended`)**: Always record timezone-aware UTC timestamps (`datetime.now(timezone.utc)`) immediately before sending and after receiving the turn so `SemanticModelLogs` time-window correlation aligns accurately.
* **Isolated conversations**: Start a fresh session/thread per `ask()` call so earlier golden questions cannot leak hints or numbers into later turns.
* **Honest failure reporting**: On transport errors or HTTP `5xx` responses, populate `error="<reason>"` and `http_status` rather than raising unhandled exceptions or returning fake prose; the pipeline records `Verdict = ERROR`.
* **`routing_evidence` hint**: Leave `""` to let `cfeval` infer `engine+citations` / `citations-only` / `unverified`, or set `"tool_call"` when your agent emits structured tool invocations (`tool_calls`).

## 2. Register via `cfeval.targets` Entry Points

Package your target in your own Python project and declare an entry point under the `cfeval.targets` group in `pyproject.toml` (`src/cfeval/targets/__init__.py` discovers all installed `cfeval.targets` plugins automatically):

```toml
[project.entry-points."cfeval.targets"]
custom-analytics-agent = "my_eval_plugins.targets:CustomAnalyticsAgentTarget"
```

For in-process scripts or unit tests, you can also register directly at runtime:

```python
from cfeval.targets import register_target

register_target("custom-analytics-agent", CustomAnalyticsAgentTarget)
```

## 3. Verify Discovery and Run

Confirm `cfeval` discovers your plugin and inspect its declared capabilities:

```bash
cfeval targets
```

Then run any golden suite against your target:

```bash
cfeval run --target custom-analytics-agent --golden data/golden/contoso-smoke.yaml --no-publish
```

## Testing Checklist for New Targets

* Add offline contract tests using recorded synthetic fixtures (`@contoso.com`) covering HTTP `200`, empty citations, rate-limit `429` (`Retry-After`), and timeout `ERROR` propagation.
* Verify `isinstance(CustomAnalyticsAgentTarget(), Target)` passes against `cfeval.interfaces.Target`.

## Related Pages

* [How It Works](../concepts/how-it-works.md)
* [Evidence Tiers and Verdicts](../concepts/evidence-and-verdicts.md)
* [CLI Reference](../reference/cli.md)
