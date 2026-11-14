# How to Evaluate Custom Targets and MCP Servers

`cfeval` is not restricted to Microsoft 365 Copilot Chat. You can evaluate any Model Context Protocol (MCP) server, Fabric Data Agent, or custom internal assistant using the exact same golden suites and statistical reports.

## 1. Evaluate an MCP Server (`--target mcp-agent`)

The `mcp-agent` target runs an OpenAI-compatible tool-calling loop against any stdio or HTTP/SSE MCP server and records structured `tool_call` evidence:

```powershell
python -m pip install -e ".[mcp]"

$env:CFEVAL_MCP_COMMAND = "python -m my_bi_mcp_server"
$env:CFEVAL_JUDGE_ENDPOINT = "https://my-aoai.openai.azure.com"
$env:CFEVAL_JUDGE_DEPLOYMENT = "gpt-4o"

python -m cfeval run `
  --target mcp-agent `
  --golden data/golden/contoso-smoke.yaml `
  --run-id mcp-eval-01 `
  --no-publish
```

Every MCP tool invocation is captured into the turn's `artifacts` / `tool_calls` list with `routing_evidence_tier = "tool_call"`, allowing `artifact` gates to verify that the agent called the expected tool and dataset.

## 2. Evaluate a Fabric Data Agent (`--target fabric-data-agent`)

Test a Fabric Data Agent endpoint directly before exposing it through M365 Copilot Chat:

```powershell
python -m cfeval run `
  --target fabric-data-agent `
  --golden data/golden/contoso.yaml `
  --collector kql `
  --run-id data-agent-01
```

## 3. Implement a Custom Python `EvalTarget`

To wrap an internal REST assistant, LangGraph/Semantic Kernel workflow, or custom SDK, implement the 20-line `EvalTarget` protocol from `src/cfeval/interfaces.py`:

```python
from cfeval.interfaces import EvalTarget, GoldenQuestion, TargetTurn


class InternalAssistantTarget:
    name = "internal-assistant"
    evidence_tier = "citations-only"

    def ask_turn(
        self,
        question: GoldenQuestion,
        *,
        ask_why: bool = False,
        why_prompt: str | None = None,
    ) -> TargetTurn:
        # Call your internal endpoint here
        payload = call_my_assistant(prompt=question.question)
        return TargetTurn(
            question=question.question,
            answer_text=payload["answer"],
            attributions=[{"name": src["title"], "url": src["url"]} for src in payload.get("sources", [])],
            conversation_id=payload["session_id"],
            latency_ms=payload["elapsed_ms"],
            raw=payload,
        )
```

Pass your `EvalTarget` instance directly to `EvalHarness` in Python or register it in `src/cfeval/targets/`.
