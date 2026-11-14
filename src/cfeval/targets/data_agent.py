"""[Experimental] Pluggable REST adapter for Microsoft Fabric Data Agent threads/runs."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Any

import requests

from ..chat import AskResult, ChatTurn
from ..clock import SystemClock
from ..config import request_with_retry
from ..trace import FabricQuery, InMemoryMonitoringSource
from .mcp_reference import _format_mock_answer, _norm_text, _stable_guid


class FabricDataAgentTarget:
    """[Experimental] Evaluates a Fabric Data Agent endpoint via the Assistants-style Threads/Runs REST API."""

    name: str = "fabric-data-agent"
    surface: str = "fabric-data-agent"
    supports_engine_trace: bool = True
    experimental: bool = True

    def __init__(
        self,
        endpoint: str = "",
        *,
        token_provider: Callable[[], str] | None = None,
        session: Any = None,
        assistant_id: str = "fabric-data-agent",
        questions: Sequence[Any] = (),
        mock: bool = False,
        clock: Any = None,
        test_user: str = "eval.tester@contoso.com",
        default_model: str = "Semantic Model",
        workspace_id: str = "00000000-0000-0000-0000-000000000001",
        poll_seconds: float = 1.0,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token_provider = token_provider
        self._session = session
        self.assistant_id = assistant_id
        self.mock = mock
        self.clock = clock or SystemClock()
        self.test_user = test_user
        self.default_model = default_model
        self.workspace_id = workspace_id
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

        self.monitoring = InMemoryMonitoringSource(clock=self.clock)
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
            return str(getattr(question, "question", "") or ""), question
        hit = self._by_text.get(_norm_text(question)) or self._by_id.get(question.strip())
        return question, hit

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token_provider is not None:
            token = self.token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _extract_assistant_reply(self, payload: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
        raw_data = payload.get("data")
        data: list[Any] = raw_data if isinstance(raw_data, list) else []
        attributions: list[dict[str, Any]] = []
        dax_queries: list[str] = []
        texts: list[str] = []

        for msg in data:
            if not isinstance(msg, Mapping) or str(msg.get("role") or "") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                texts.append(content.strip())
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, Mapping):
                        continue
                    txt_obj = block.get("text")
                    if isinstance(txt_obj, Mapping):
                        val = str(txt_obj.get("value") or "").strip()
                        if val:
                            texts.append(val)
                        for ann in txt_obj.get("annotations") or []:
                            if isinstance(ann, Mapping):
                                url = str(ann.get("url") or ann.get("seeMoreWebUrl") or "").strip()
                                name = str(ann.get("title") or ann.get("name") or "").strip()
                                if url or name:
                                    attributions.append(
                                        {
                                            "attributionType": "citation",
                                            "providerDisplayName": name or url,
                                            "seeMoreWebUrl": url
                                            or f"https://app.powerbi.com/groups/{self.workspace_id}/reports/{_stable_guid(name)}",
                                        }
                                    )
                    elif isinstance(txt_obj, str) and txt_obj.strip():
                        texts.append(txt_obj.strip())
            for cite in msg.get("citations") or []:
                if isinstance(cite, Mapping):
                    c_name = str(cite.get("name") or cite.get("title") or "").strip()
                    c_url = str(cite.get("url") or cite.get("seeMoreWebUrl") or "").strip()
                    if c_name or c_url:
                        attributions.append(
                            {
                                "attributionType": "citation",
                                "providerDisplayName": c_name or c_url,
                                "seeMoreWebUrl": c_url
                                or f"https://app.powerbi.com/groups/{self.workspace_id}/reports/{_stable_guid(c_name)}",
                            }
                        )
            meta = msg.get("metadata")
            if isinstance(meta, Mapping) and str(meta.get("dax") or "").strip():
                dax_queries.append(str(meta["dax"]).strip())
            if texts:
                break

        return "\n".join(texts).strip(), attributions, dax_queries

    def _ask_mock(self, prompt_text: str, q: Any | None, explain_mode: str) -> AskResult:
        self._counter += 1
        started = self.clock.now()
        if hasattr(self.clock, "advance"):
            self.clock.sleep(0.05)
            ended = self.clock.now()
        else:
            ended = started + timedelta(milliseconds=25)

        ct = str(getattr(q, "case_type", "") or "scalar").strip().lower() if q is not None else "scalar"
        is_abstention = (
            ct in ("abstention", "negative", "refusal") and not str(getattr(q, "expected_artifact", "") or "").strip()
        )

        model_name = (
            str(getattr(q, "model", "") or getattr(q, "expected_model", "") or "").strip() if q is not None else ""
        ) or self.default_model
        artifact_name = (str(getattr(q, "expected_artifact", "") or "").strip() if q is not None else "") or model_name
        artifact_id = (
            str(getattr(q, "expected_artifact_id", "") or "").strip() if q is not None else ""
        ) or _stable_guid("da-art:" + artifact_name)
        answer_text, val = _format_mock_answer(q, prompt_text, artifact_name)
        ref_dax = str(getattr(q, "reference_dax", "") or "").strip() if q is not None else ""
        dax_query = ref_dax or 'EVALUATE ROW("Result", 1)'

        thread_id = f"da-thread-{self._counter:04d}"
        attributions: list[dict[str, Any]] = []
        if not is_abstention:
            attributions.append(
                {
                    "attributionType": "citation",
                    "providerDisplayName": artifact_name,
                    "seeMoreWebUrl": f"https://app.powerbi.com/groups/{self.workspace_id}/datasets/{artifact_id}",
                    "id": artifact_id,
                }
            )
            fq = FabricQuery(
                query_time=started + (ended - started) / 2,
                workspace_id=self.workspace_id,
                item_id=_stable_guid("da-model:" + model_name),
                item_name=model_name,
                application_name="FabricDataAgent",
                operation_name="QueryEnd",
                duration_ms=55.0,
                dax=dax_query,
                correlation_id=f"{thread_id}-run",
                operation_id="data-agent-run",
                executing_user=self.test_user,
            )
            self._recorded.append(fq)
            self.monitoring.record(fq)

        lat_ms = round((ended - started).total_seconds() * 1000.0, 1)
        answer_turn = ChatTurn(
            text=answer_text,
            attributions=attributions,
            started=started,
            ended=ended,
            latency_ms=lat_ms,
            raw={"source": "fabric-data-agent", "experimental": True, "mock": True},
        )
        explain_turn: ChatTurn | None = None
        why_text = ""
        why_obj: dict[str, Any] | None = None
        if explain_mode != "off":
            why_obj = {
                "answer": val,
                "model": "" if is_abstention else model_name,
                "dax": "" if is_abstention else dax_query,
            }
            why_text = "```json\n" + json.dumps(why_obj, ensure_ascii=False) + "\n```"
            explain_turn = ChatTurn(
                text=why_text,
                attributions=[],
                started=ended,
                ended=ended,
                latency_ms=0.0,
                raw={"source": "fabric-data-agent-why"},
            )
        result = AskResult(
            question=prompt_text,
            conversation_id=thread_id,
            answer=answer_turn,
            why_text=why_text,
            http_status=200,
            started=started,
            ended=ended,
        )
        if explain_turn is not None:
            result.explain = explain_turn
        if why_obj is not None:
            result.why_json = why_obj
        return result

    def ask(
        self,
        question: str | Any,
        explain_mode: str = "followup",
        *,
        attempt: int = 1,
        persona: str = "",
    ) -> AskResult:
        prompt_text, q = self._resolve_question(question)
        if self.mock:
            return self._ask_mock(prompt_text, q, explain_mode)

        if not self.endpoint:
            raise ValueError("FabricDataAgentTarget requires a non-empty endpoint (or mock=True).")

        sess = self._session if self._session is not None else requests.Session()
        started = self.clock.now()
        headers = self._headers()

        try:
            t_resp = request_with_retry(
                sess,
                "POST",
                f"{self.endpoint}/threads",
                sleep_fn=self.clock.sleep,
                headers=headers,
                json={},
            )
            thread_data = t_resp.json()
            thread_id = str(thread_data.get("id") or "")
            if not thread_id:
                raise RuntimeError("Data Agent /threads response did not include a thread id")

            request_with_retry(
                sess,
                "POST",
                f"{self.endpoint}/threads/{thread_id}/messages",
                sleep_fn=self.clock.sleep,
                headers=headers,
                json={"role": "user", "content": prompt_text},
            )

            run_resp = request_with_retry(
                sess,
                "POST",
                f"{self.endpoint}/threads/{thread_id}/runs",
                sleep_fn=self.clock.sleep,
                headers=headers,
                json={"assistant_id": self.assistant_id},
            )
            run_data = run_resp.json()
            run_id = str(run_data.get("id") or "")
            status = str(run_data.get("status") or "completed")

            deadline = self.clock.monotonic() + self.timeout_seconds
            while status in ("queued", "in_progress", "cancelling"):
                if self.clock.monotonic() >= deadline:
                    raise TimeoutError(f"Data Agent run {run_id} timed out in status {status!r}")
                self.clock.sleep(self.poll_seconds)
                poll_resp = request_with_retry(
                    sess,
                    "GET",
                    f"{self.endpoint}/threads/{thread_id}/runs/{run_id}",
                    sleep_fn=self.clock.sleep,
                    headers=headers,
                )
                run_data = poll_resp.json()
                status = str(run_data.get("status") or "")

            if status != "completed":
                ended = self.clock.now()
                return AskResult(
                    question=prompt_text,
                    conversation_id=thread_id,
                    http_status=502,
                    error=f"Data Agent run finished with status {status!r}",
                    started=started,
                    ended=ended,
                )

            msg_resp = request_with_retry(
                sess,
                "GET",
                f"{self.endpoint}/threads/{thread_id}/messages",
                sleep_fn=self.clock.sleep,
                headers=headers,
            )
            msg_payload = msg_resp.json()
            answer_text, attributions, dax_queries = self._extract_assistant_reply(
                msg_payload if isinstance(msg_payload, Mapping) else {}
            )

            run_dax = str(run_data.get("dax") or "").strip() if isinstance(run_data, Mapping) else ""
            if run_dax and run_dax not in dax_queries:
                dax_queries.append(run_dax)

            ended = self.clock.now()
            model_name = (
                str(run_data.get("model") or "").strip() if isinstance(run_data, Mapping) else ""
            ) or self.default_model
            for idx, dax_stmt in enumerate(dax_queries):
                fq = FabricQuery(
                    query_time=started + (ended - started) / 2 + timedelta(milliseconds=idx),
                    workspace_id=self.workspace_id,
                    item_id=_stable_guid("da-live:" + model_name),
                    item_name=model_name,
                    application_name="FabricDataAgent",
                    operation_name="QueryEnd",
                    duration_ms=50.0,
                    dax=dax_stmt,
                    correlation_id=f"{thread_id}-{run_id}-{idx}",
                    operation_id="data-agent-run",
                    executing_user=self.test_user,
                )
                self._recorded.append(fq)
                self.monitoring.record(fq)

            lat_ms = round((ended - started).total_seconds() * 1000.0, 1)
            answer_turn = ChatTurn(
                text=answer_text,
                attributions=attributions,
                started=started,
                ended=ended,
                latency_ms=lat_ms,
                raw={"source": "fabric-data-agent", "experimental": True, "run_id": run_id},
            )
            return AskResult(
                question=prompt_text,
                conversation_id=thread_id,
                answer=answer_turn,
                http_status=200,
                started=started,
                ended=ended,
            )
        except Exception as exc:
            ended = self.clock.now()
            http_status = int(getattr(exc, "status_code", 0) or getattr(exc, "status", 0) or 500)
            return AskResult(
                question=prompt_text,
                conversation_id="",
                http_status=http_status,
                error=str(exc),
                started=started,
                ended=ended,
            )

    def recorded_queries(self) -> list[FabricQuery]:
        return list(self._recorded)
