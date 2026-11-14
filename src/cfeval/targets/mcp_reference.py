"""Pluggable target evaluating a semantic-model MCP tool loop (`tools/call` -> `execute_dax`)."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from ..chat import AskResult, ChatTurn
from ..clock import SystemClock
from ..trace import FabricQuery, InMemoryMonitoringSource


def _stable_guid(seed: str) -> str:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:12]}-5{h[13:16]}-a{h[17:20]}-{h[20:32]}"


def _norm_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _format_mock_answer(q: Any | None, prompt_text: str, artifact_name: str) -> tuple[str, Any]:
    if q is None:
        return f"According to {artifact_name}, the requested metric is 1.0.", 1.0

    ct = str(getattr(q, "case_type", None) or "scalar").strip().lower()
    spec = getattr(q, "expect", None)
    spec_map = spec if isinstance(spec, Mapping) else {}
    exp_val = getattr(q, "expected_value", None)
    exp_ans = str(getattr(q, "expected_answer", "") or "").strip()
    unit = str(getattr(q, "unit", "") or "").strip().lower()
    currency = str(getattr(q, "currency", "") or "").strip().upper()

    if ct in ("abstention", "negative", "refusal"):
        return "That information is not available in the semantic model; I cannot answer from available data.", None

    if exp_ans and ct not in ("scalar", "numeric", "number"):
        return exp_ans, exp_val

    if ct in ("scalar", "numeric", "number") and exp_val is not None:
        val = float(exp_val)
        if unit in ("currency", "usd") or currency == "USD":
            val_str = f"${val:,.2f}" if val % 1 else f"${val:,.0f}"
        elif unit in ("percent", "percentage", "pct", "%"):
            pct = val * 100.0 if abs(val) <= 1.0 else val
            val_str = f"{pct:.2f}%".rstrip("0").rstrip(".") + "%" if "." in f"{pct:.2f}" else f"{pct:.0f}%"
            val_str = val_str.replace("%%", "%")
        elif unit in ("integer", "count"):
            val_str = f"{int(round(val)):,}"
        else:
            val_str = f"{val:g}"
        return f"According to {artifact_name}, the result is {val_str}.", val

    if ct in ("ranked_list", "set"):
        items = spec_map.get("items") or []
        labels: list[str] = []
        for idx, item in enumerate(items, start=1):
            name = str(item.get("name") if isinstance(item, Mapping) else item).strip()
            val_part = item.get("value") if isinstance(item, Mapping) else None
            labels.append(f"{idx}. {name}" + (f" ({val_part})" if val_part is not None else ""))
        return f"From {artifact_name}:\n" + "\n".join(labels), labels

    if ct == "table":
        rows = spec_map.get("rows") or []
        if rows and isinstance(rows[0], Mapping):
            cols = list(rows[0].keys())
            header = "| " + " | ".join(cols) + " |"
            sep = "| " + " | ".join("---" for _ in cols) + " |"
            body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows if isinstance(r, Mapping)]
            return "\n".join([header, sep, *body]), rows

    if ct == "record":
        fields = spec_map.get("fields")
        if isinstance(fields, Mapping):
            lines = [f"- {k}: {v}" for k, v in fields.items()]
            return f"From {artifact_name}:\n" + "\n".join(lines), dict(fields)

    if ct == "direction":
        direction = str(spec_map.get("direction") or "up").strip().lower()
        verb = {"up": "increased", "down": "decreased", "flat": "remained flat"}.get(direction, direction)
        mag = spec_map.get("value")
        suffix = f" by {mag}" if mag is not None else ""
        return f"According to {artifact_name}, the metric {verb}{suffix}.", direction

    if ct == "categorical":
        cat_val = str(spec_map.get("value") or exp_ans or "").strip()
        return f"According to {artifact_name}, the category is {cat_val}.", cat_val

    if ct in ("facts", "text"):
        facts = [str(f) for f in (spec_map.get("facts") or spec_map.get("items") or []) if str(f).strip()]
        if facts:
            return f"According to {artifact_name}: " + "; ".join(facts) + ".", facts

    return exp_ans or f"Grounded response from {artifact_name} for: {prompt_text}", exp_val


class McpReferenceTarget:
    """Evaluates a semantic-model MCP tool loop (`tools/call` -> `execute_dax`)."""

    name: str = "mcp-agent"
    surface: str = "mcp-agent"
    supports_engine_trace: bool = True
    experimental: bool = False

    def __init__(
        self,
        *,
        tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        questions: Sequence[Any] = (),
        mock: bool = False,
        clock: Any = None,
        test_user: str = "eval.tester@contoso.com",
        mcp_server_command: Sequence[str] | str = (),
        mcp_tool_name: str = "execute_dax",
        default_model: str = "Semantic Model",
        workspace_id: str = "00000000-0000-0000-0000-000000000001",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.tool_executor = tool_executor
        self.mock = mock
        self.clock = clock or SystemClock()
        self.test_user = test_user
        self.mcp_tool_name = mcp_tool_name
        self.default_model = default_model
        self.workspace_id = workspace_id
        self.timeout_seconds = timeout_seconds
        if isinstance(mcp_server_command, str):
            self.mcp_server_command: list[str] = shlex.split(mcp_server_command) if mcp_server_command.strip() else []
        else:
            self.mcp_server_command = [str(x) for x in mcp_server_command if str(x).strip()]

        self.monitoring = InMemoryMonitoringSource(clock=self.clock, routing_evidence_preset="tool_call")
        self._recorded: list[FabricQuery] = []
        self._by_id: dict[str, Any] = {}
        self._by_text: dict[str, Any] = {}
        self._counter = 0
        if questions:
            self.register_questions(questions)

    def register_questions(self, questions: Iterable[Any]) -> None:
        for q in questions:
            qid = str(getattr(q, "id", "") or "").strip()
            qtext = str(getattr(q, "question", "") or "").strip()
            if qid:
                self._by_id[qid] = q
            if qtext:
                self._by_text[_norm_text(qtext)] = q
            for p in getattr(q, "paraphrases", ()) or ():
                if str(p).strip():
                    self._by_text[_norm_text(str(p))] = q

    def _resolve_question(self, question: str | Any) -> tuple[str, Any | None]:
        if not isinstance(question, str):
            qtext = str(getattr(question, "question", "") or "")
            return qtext, question
        hit = self._by_text.get(_norm_text(question)) or self._by_id.get(question.strip())
        return question, hit

    def _call_stdio_mcp(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        requests_payload = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cfeval", "version": "0.1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        ]
        stdin_text = "\n".join(json.dumps(msg) for msg in requests_payload) + "\n"
        proc = subprocess.Popen(
            self.mcp_server_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            stdout_data, stderr_data = proc.communicate(input=stdin_text, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.communicate()
            raise TimeoutError(f"MCP server timed out after {self.timeout_seconds}s") from exc

        for raw_line in stdout_data.splitlines():
            line = raw_line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2:
                if "error" in msg and msg["error"]:
                    err = msg["error"]
                    detail = err.get("message") if isinstance(err, Mapping) else str(err)
                    raise RuntimeError(f"MCP tool error: {detail}")
                result = msg.get("result")
                return dict(result) if isinstance(result, Mapping) else {"content": result}

        raise RuntimeError(
            f"MCP server exited ({proc.returncode}) without a tools/call response: {stderr_data.strip()[:300]}"
        )

    def _default_mock_executor(
        self,
        q: Any | None,
        prompt_text: str,
        dax_query: str,
        model_name: str,
        artifact_name: str,
        artifact_id: str,
    ) -> dict[str, Any]:
        answer_text, val = _format_mock_answer(q, prompt_text, artifact_name)
        return {
            "answer": answer_text,
            "value": val,
            "dax": dax_query,
            "model": model_name,
            "artifact": artifact_name,
            "artifact_id": artifact_id,
            "duration_ms": 42.0,
        }

    def ask(
        self,
        question: str | Any,
        explain_mode: str = "followup",
        *,
        attempt: int = 1,
        persona: str = "",
    ) -> AskResult:
        self._counter += 1
        prompt_text, q = self._resolve_question(question)
        started = self.clock.now()

        conv_id = f"mcp-conv-{self._counter:04d}"

        if self.mock:
            ct = str(getattr(q, "case_type", "") or "scalar").strip().lower() if q is not None else "scalar"
            is_abstention = (
                ct in ("abstention", "negative", "refusal")
                and not str(getattr(q, "expected_artifact", "") or "").strip()
            )
            model_name = (
                str(getattr(q, "model", "") or getattr(q, "expected_model", "") or "").strip() if q is not None else ""
            ) or self.default_model
            artifact_name = (
                str(getattr(q, "expected_artifact", "") or "").strip() if q is not None else ""
            ) or model_name
            artifact_id = (
                str(getattr(q, "expected_artifact_id", "") or "").strip() if q is not None else ""
            ) or _stable_guid("artifact:" + artifact_name)
            model_id = _stable_guid("model:" + model_name)
            ref_dax = str(getattr(q, "reference_dax", "") or "").strip() if q is not None else ""
            exp_val = getattr(q, "expected_value", None) if q is not None else None
            dax_query = ref_dax or (
                f'EVALUATE ROW("Result", {exp_val!r})' if exp_val is not None else 'EVALUATE ROW("Result", 1)'
            )
            tool_args: dict[str, Any] = {"query": dax_query, "dataset": model_name, "question": prompt_text}
        else:
            is_abstention = False
            model_name = ""
            artifact_name = ""
            artifact_id = ""
            model_id = ""
            dax_query = ""
            tool_args = {"question": prompt_text}

        try:
            if not self.mock:
                if self.tool_executor is not None:
                    tool_res = self.tool_executor(self.mcp_tool_name, tool_args)
                elif self.mcp_server_command:
                    tool_res = self._call_stdio_mcp(self.mcp_tool_name, tool_args)
                else:
                    raise RuntimeError("Live MCP target requires tool_executor or MCP_SERVER_COMMAND.")
            else:
                tool_res = self._default_mock_executor(
                    q, prompt_text, dax_query, model_name, artifact_name, artifact_id
                )
        except Exception as exc:
            ended = self.clock.now()
            return AskResult(
                question=prompt_text,
                conversation_id=conv_id,
                http_status=500,
                error=str(exc),
                started=started,
                ended=ended,
            )

        if hasattr(self.clock, "advance"):
            self.clock.sleep(0.05)
            ended = self.clock.now()
        else:
            ended = max(self.clock.now(), started + timedelta(milliseconds=10))

        executed_dax = str(tool_res.get("dax") or (dax_query if self.mock else "")).strip()
        resolved_model = str(tool_res.get("model") or (model_name if self.mock else "")).strip()
        resolved_artifact = str(tool_res.get("artifact") or (artifact_name if self.mock else "")).strip()
        default_art_id = (
            artifact_id if self.mock else (_stable_guid("artifact:" + resolved_artifact) if resolved_artifact else "")
        )
        resolved_art_id = str(tool_res.get("artifact_id") or default_art_id).strip()
        resolved_model_id = str(
            tool_res.get("model_id")
            or (model_id if self.mock else (_stable_guid("model:" + resolved_model) if resolved_model else ""))
        ).strip()
        dur_ms = float(tool_res.get("duration_ms") or 42.0)

        answer_text = str(tool_res.get("answer") or "").strip()
        if not answer_text:
            content = tool_res.get("content")
            if isinstance(content, list):
                chunks = [
                    str(c.get("text") or "") for c in content if isinstance(c, Mapping) and c.get("text") is not None
                ]
                answer_text = "\n".join(c for c in chunks if c).strip()
            elif content is not None:
                answer_text = str(content).strip()
        if not answer_text and self.mock:
            answer_text, _ = _format_mock_answer(q, prompt_text, resolved_artifact)

        attributions: list[dict[str, Any]] = []
        tool_calls_out: list[dict[str, Any]] = []
        if not is_abstention:
            if resolved_artifact:
                attributions.append(
                    {
                        "attributionType": "citation",
                        "providerDisplayName": resolved_artifact,
                        "seeMoreWebUrl": f"https://app.powerbi.com/groups/{self.workspace_id}/reports/{resolved_art_id}",
                        "id": resolved_art_id,
                    }
                )
            if resolved_model or executed_dax:
                query_time = started + (ended - started) / 2
                app_ctx = json.dumps(
                    {
                        "DatasetId": resolved_model_id,
                        "Sources": [{"ReportId": resolved_art_id}] if resolved_art_id else [],
                    },
                    sort_keys=True,
                )
                fq = FabricQuery(
                    query_time=query_time,
                    workspace_id=self.workspace_id,
                    item_id=resolved_model_id,
                    item_name=resolved_model,
                    application_name="MCP-PowerBI",
                    operation_name="QueryEnd",
                    duration_ms=dur_ms,
                    dax=executed_dax,
                    correlation_id=f"{conv_id}-q1",
                    operation_id="mcp-tool-call",
                    application_context=app_ctx,
                    executing_user=self.test_user,
                )
                self._recorded.append(fq)
                self.monitoring.record(fq)
                tool_calls_out.append(
                    {
                        "tool": self.mcp_tool_name,
                        "dax": executed_dax,
                        "model": resolved_model,
                        "workspace_id": self.workspace_id,
                        "item_id": resolved_model_id,
                        "duration_ms": dur_ms,
                        "correlation_id": f"{conv_id}-q1",
                        "operation_id": "mcp-tool-call",
                        "application_context": app_ctx,
                    }
                )

        lat_ms = round((ended - started).total_seconds() * 1000.0, 1)
        answer_turn = ChatTurn(
            text=answer_text,
            attributions=attributions,
            started=started,
            ended=ended,
            latency_ms=lat_ms,
            raw={"source": "mcp-agent", "tool": self.mcp_tool_name, "dax": executed_dax},
        )

        explain_turn: ChatTurn | None = None
        why_text = ""
        why_payload: dict[str, Any] | None = None
        if explain_mode != "off":
            why_payload = {
                "answer": tool_res.get("value"),
                "artifact": "" if is_abstention else resolved_artifact,
                "model": "" if is_abstention else resolved_model,
                "dax": "" if is_abstention else executed_dax,
            }
            why_text = "```json\n" + json.dumps(why_payload, ensure_ascii=False) + "\n```"
            explain_turn = ChatTurn(
                text=why_text,
                attributions=[],
                started=ended,
                ended=ended,
                latency_ms=0.0,
                raw={"source": "mcp-agent-why"},
            )

        result = AskResult(
            question=prompt_text,
            conversation_id=conv_id,
            answer=answer_turn,
            why_text=why_text,
            http_status=200,
            started=started,
            ended=ended,
        )
        if explain_turn is not None:
            result.explain = explain_turn
        if why_payload is not None:
            result.why_json = why_payload
        result.tool_calls = tool_calls_out  # type: ignore[attr-defined]
        result.routing_evidence = "tool_call"  # type: ignore[attr-defined]
        return result

    def recorded_queries(self) -> list[FabricQuery]:
        return list(self._recorded)


FabricIqMcpReferenceTarget = McpReferenceTarget
