"""Pluggable target for replaying pre-captured Q&A transcripts (.jsonl, .json, .csv, .md)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..chat import AskResult, ChatTurn, parse_json_block
from ..clock import SystemClock, parse_iso
from ..interop import _normalize_transcript_record, load_transcript_records
from ..trace import FabricQuery, InMemoryMonitoringSource

_PERSONA_PREFIX_RE = re.compile(r"^Context:\s*Respond for persona '[^']*'\.\s*\n\n", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EXAMPLE_HOST_RE = re.compile(
    r"^(https?://(?:[a-z0-9-]+\.)*"
    r"(?:powerbi|fabric\.microsoft|sharepoint|teams\.microsoft|outlook\.office|office))"
    r"\.example(?=/|$)",
    re.IGNORECASE,
)


def _norm_q(text: str) -> str:
    stripped = _PERSONA_PREFIX_RE.sub("", text or "")
    return " ".join(stripped.strip().lower().split())


def _slug(text: str) -> str:
    s = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return s or hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _citation_url(cite: Mapping[str, Any]) -> str:
    raw_url = str(cite.get("url") or "").strip()
    kind = str(cite.get("kind") or "").strip().lower()
    name = str(cite.get("name") or "artifact").strip()
    art_id = str(cite.get("id") or "").strip()

    if raw_url:
        return _EXAMPLE_HOST_RE.sub(r"\1.com", raw_url)

    ident = art_id or _slug(name)
    if "onedrive" in kind:
        return f"https://contoso-my.sharepoint.com/personal/user/{ident}"
    if "sharepoint" in kind or name.lower().endswith((".docx", ".pptx", ".xlsx", ".pdf")):
        return f"https://contoso.sharepoint.com/sites/docs/{ident}"
    if "teams" in kind:
        return f"https://teams.microsoft.com/l/meetup-join/{ident}"
    if "exchange" in kind or "outlook" in kind or "email" in kind:
        return f"https://outlook.office.com/mail/id/{ident}"
    if kind in ("semantic_model", "dataset", "semanticmodel"):
        return f"https://app.powerbi.com/groups/transcript-import/datasets/{ident}"
    return f"https://app.powerbi.com/groups/transcript-import/reports/{ident}"


class TranscriptImportTarget:
    """Replays pre-captured transcript records through the standard AskResult contract."""

    name: str = "transcript-import"
    surface: str = "transcript-import"
    supports_engine_trace: bool = False
    experimental: bool = False

    def __init__(
        self,
        transcript_path: str | Path | None = None,
        *,
        records: Sequence[Mapping[str, Any]] | None = None,
        questions: Sequence[Any] = (),
        clock: Any = None,
        test_user: str = "eval.tester@contoso.com",
    ) -> None:
        self.transcript_path = Path(transcript_path) if transcript_path is not None else None
        self.clock = clock or SystemClock()
        self.test_user = test_user
        self.monitoring = InMemoryMonitoringSource(clock=self.clock)
        self._recorded: list[FabricQuery] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_id_lower: dict[str, dict[str, Any]] = {}
        self._by_question: dict[str, dict[str, Any]] = {}
        self._registered_text_to_id: dict[str, str] = {}

        loaded: list[dict[str, Any]] = []
        if self.transcript_path is not None:
            loaded.extend(load_transcript_records(self.transcript_path))
        if records is not None:
            for r in records:
                loaded.append(_normalize_transcript_record(r))

        for rec in loaded:
            rid = str(rec.get("id") or "").strip()
            if rid:
                self._by_id[rid] = rec
                self._by_id_lower[rid.lower()] = rec
            q_txt = _norm_q(str(rec.get("question") or ""))
            if q_txt:
                self._by_question[q_txt] = rec

        if questions:
            self.register_questions(questions)

    def register_questions(self, questions: Iterable[Any]) -> None:
        """Map golden question prompts (and paraphrases) to question IDs for string-only callers."""
        for q in questions:
            qid = str(q.get("id") if isinstance(q, Mapping) else getattr(q, "id", "") or "").strip()
            qtext = str(q.get("question") if isinstance(q, Mapping) else getattr(q, "question", "") or "").strip()
            paraphrases = q.get("paraphrases", ()) if isinstance(q, Mapping) else getattr(q, "paraphrases", ()) or ()
            if qid and qtext:
                self._registered_text_to_id[_norm_q(qtext)] = qid
            if qid and isinstance(paraphrases, Iterable) and not isinstance(paraphrases, (str, bytes)):
                for p in paraphrases:
                    if str(p).strip():
                        self._registered_text_to_id[_norm_q(str(p))] = qid

    def _match_record(self, question: str | Any) -> dict[str, Any] | None:
        if not isinstance(question, str):
            qid = str(getattr(question, "id", "") or "").strip()
            if qid:
                hit = self._by_id.get(qid) or self._by_id_lower.get(qid.lower())
                if hit is not None:
                    return hit

        q_text = str(getattr(question, "question", question) or "")
        norm = _norm_q(q_text)
        mapped_id = self._registered_text_to_id.get(norm)
        if mapped_id:
            hit = self._by_id.get(mapped_id) or self._by_id_lower.get(mapped_id.lower())
            if hit is not None:
                return hit

        if norm in self._by_question:
            return self._by_question[norm]

        # Allow direct ID lookup if caller passed the question ID string
        raw_clean = q_text.strip()
        return self._by_id.get(raw_clean) or self._by_id_lower.get(raw_clean.lower())

    def _window_times(self, rec: Mapping[str, Any], latency_ms: float) -> tuple[datetime, datetime]:
        s_raw = rec.get("started_utc")
        e_raw = rec.get("ended_utc")
        if s_raw and e_raw:
            start = parse_iso(str(s_raw))
            end = parse_iso(str(e_raw))
            if end >= start:
                return start, end
        start = self.clock.now()
        dur_s = max(0.005, latency_ms / 1000.0) if latency_ms > 0 else 0.05
        if hasattr(self.clock, "advance"):
            self.clock.sleep(dur_s)
            end = self.clock.now()
        else:
            end = start + timedelta(seconds=dur_s)
        return start, end

    def ask(
        self,
        question: str | Any,
        explain_mode: str = "followup",
        *,
        attempt: int = 1,
        persona: str = "",
    ) -> AskResult:
        prompt_text = str(getattr(question, "question", question) or "")
        rec = self._match_record(question)
        if rec is None:
            now = self.clock.now()
            return AskResult(
                question=prompt_text,
                conversation_id="",
                http_status=404,
                error="Question not found in transcript",
                started=now,
                ended=now,
            )

        lat = float(rec["latency_ms"]) if rec.get("latency_ms") is not None else 50.0
        started, ended = self._window_times(rec, lat)
        conv_id = str(rec.get("conversation_id") or f"transcript-{rec.get('id') or _slug(prompt_text)[:12]}")

        attributions: list[dict[str, Any]] = []
        for cite in rec.get("citations") or []:
            if not isinstance(cite, Mapping):
                continue
            name = str(cite.get("name") or cite.get("title") or "").strip()
            attr_url = _citation_url(cite)
            att: dict[str, Any] = {
                "attributionType": "citation",
                "attributionSource": "model",
                "providerDisplayName": name,
                "seeMoreWebUrl": attr_url,
            }
            if cite.get("kind"):
                att["kind"] = str(cite["kind"])
            if cite.get("id"):
                att["id"] = str(cite["id"])
            attributions.append(att)

        raw_meta = {
            "source": "transcript-import",
            "record_id": rec.get("id", ""),
            "citations": rec.get("citations", []),
        }
        answer_turn = ChatTurn(
            text=str(rec.get("answer") or ""),
            attributions=attributions,
            started=started,
            ended=ended,
            latency_ms=lat,
            raw=raw_meta,
        )

        why_text = str(rec.get("why") or "").strip()
        raw_why_json = rec.get("why_json")
        why_json_dict: dict[str, Any] | None = (
            dict(raw_why_json) if isinstance(raw_why_json, Mapping) else parse_json_block(why_text)
        )
        if not why_text and why_json_dict is not None:
            why_text = "```json\n" + json.dumps(why_json_dict, ensure_ascii=False) + "\n```"

        explain_turn: ChatTurn | None = None
        if explain_mode != "off" and why_text:
            explain_turn = ChatTurn(
                text=why_text,
                attributions=[],
                started=ended,
                ended=ended,
                latency_ms=0.0,
                raw={"source": "transcript-import-why"},
            )

        dax_statements: list[tuple[str, str]] = []
        default_model = str(rec.get("model") or "").strip()
        if not default_model and rec.get("citations"):
            default_model = str(rec["citations"][0].get("name") or "").strip()

        for tc in rec.get("tool_calls") or []:
            if isinstance(tc, Mapping):
                raw_args = tc.get("arguments")
                args: Mapping[str, Any] = raw_args if isinstance(raw_args, Mapping) else {}
                tc_dax = str(
                    tc.get("dax") or tc.get("Dax") or tc.get("query") or args.get("dax") or args.get("query") or ""
                ).strip()
                tc_model = str(tc.get("model") or tc.get("dataset") or args.get("model") or default_model).strip()
                if tc_dax:
                    dax_statements.append((tc_dax, tc_model))

        if not dax_statements and str(rec.get("dax") or "").strip():
            dax_statements.append((str(rec["dax"]).strip(), default_model))

        exec_user = str(rec.get("user") or self.test_user)
        mid_time = started + (ended - started) / 2
        for idx, (dax_stmt, model_name) in enumerate(dax_statements):
            fq = FabricQuery(
                query_time=mid_time + timedelta(milliseconds=idx),
                workspace_id="transcript-workspace",
                item_id=_slug(model_name or "semantic-model"),
                item_name=model_name or "Semantic Model",
                application_name="TranscriptImport",
                operation_name="QueryEnd",
                duration_ms=max(1.0, round(lat * 0.25, 1)),
                dax=dax_stmt,
                correlation_id=f"{conv_id}-{idx}",
                operation_id="transcript-dax",
                executing_user=exec_user,
            )
            self._recorded.append(fq)
            self.monitoring.record(fq)

        result = AskResult(
            question=prompt_text,
            conversation_id=conv_id,
            answer=answer_turn,
            why_text=why_text if explain_mode != "off" else "",
            http_status=200,
            started=started,
            ended=ended,
        )
        if explain_turn is not None:
            result.explain = explain_turn
        if explain_mode != "off" and why_json_dict is not None:
            result.why_json = why_json_dict
        return result

    def recorded_queries(self) -> list[FabricQuery]:
        return list(self._recorded)
