"""Microsoft 365 Copilot Chat API client (Microsoft Graph beta).

POST /beta/copilot/conversations                      -> create a conversation
POST /beta/copilot/conversations/{id}/chat            -> send a message, synchronous

The API is in preview, delegated-only and returns the reply text plus
attributions (citations and annotations with links). It doesn't return a
reasoning trace, so the harness can ask a follow-up "which sources did you use
and why" turn in the same conversation (self-reported, not proof).
"""
import json
import re
import time
from dataclasses import dataclass, field

import requests

from .clock import SystemClock

GRAPH_BETA = "https://graph.microsoft.com/beta"
RETRY_STATUS = (429, 500, 502, 503, 504)

INLINE_INSTRUCTION = "State the data source, filters, and time period used."
EXPLAIN_PROMPT = (
    "For your previous answer only: list each data source you used (name and link), why you chose it "
    "over other sources, and the measure, filters and time period you applied. Reply only with JSON in "
    'this shape: {"sources": [{"name": "", "link": "", "why": ""}], "measure": "", "filters": "", '
    '"time_period": ""}'
)


class ChatApiError(RuntimeError):
    def __init__(self, status, body):
        super().__init__("Copilot Chat API returned HTTP %s: %s" % (status, (body or "")[:300]))
        self.status = status
        self.body = body


@dataclass
class ChatTurn:
    text: str
    attributions: list
    started: object
    ended: object
    latency_ms: float
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class AskResult:
    question: str
    conversation_id: str = ""
    answer: ChatTurn = None
    explain: ChatTurn = None
    why_text: str = ""
    why_json: dict = None
    error: str = ""
    http_status: int = 200
    started: object = None
    ended: object = None

    @property
    def ok(self):
        return not self.error and self.answer is not None


def parse_json_block(text):
    """Pull the first JSON object out of a reply (handles code fences and prose)."""
    if not text:
        return None
    candidate = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = candidate.find("{")
    for blob in (candidate, candidate[start:] if start >= 0 else ""):
        if not blob:
            continue
        try:
            value, _end = json.JSONDecoder().raw_decode(blob.lstrip())
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            continue
    return None


def reply_message(conversation, sent_text=""):
    """The last message in the conversation that isn't the echo of what we sent."""
    messages = conversation.get("messages") or []
    for msg in reversed(messages):
        if (msg.get("text") or "").strip() != (sent_text or "").strip():
            return msg
    return messages[-1] if messages else {}


class CopilotChatClient:
    def __init__(self, token_provider, time_zone="America/New_York", timeout_s=180, max_retries=4,
                 base_url=GRAPH_BETA, session=None, clock=None):
        self._token = token_provider
        self.time_zone = time_zone
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.clock = clock or SystemClock()

    def _post(self, path, body):
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            r = self.session.post(self.base_url + path, json=body, timeout=self.timeout_s, headers={
                "Authorization": "Bearer " + self._token(), "Content-Type": "application/json"})
            if r.status_code < 300:
                return r.json()
            if r.status_code in RETRY_STATUS and attempt < self.max_retries:
                wait = float(r.headers.get("Retry-After") or delay)
                time.sleep(min(wait, 60))
                delay = min(delay * 2, 30)
                continue
            raise ChatApiError(r.status_code, r.text)
        raise ChatApiError(0, "retries exhausted")

    def create_conversation(self):
        return self._post("/copilot/conversations", {})["id"]

    def chat(self, conversation_id, text, additional_context=None, web_enabled=False):
        body = {
            "message": {"text": text},
            "locationHint": {"timeZone": self.time_zone},
            "contextualResources": {"webContext": {"isWebEnabled": bool(web_enabled)}},
        }
        if additional_context:
            body["additionalContext"] = [{"text": t} for t in additional_context]
        started = self.clock.now()
        t0 = time.monotonic()
        conversation = self._post("/copilot/conversations/%s/chat" % conversation_id, body)
        latency = (time.monotonic() - t0) * 1000.0
        msg = reply_message(conversation, text)
        return ChatTurn(msg.get("text") or "", msg.get("attributions") or [], started, self.clock.now(),
                        round(latency, 1), conversation)

    def ask(self, question, explain_mode="followup"):
        """New conversation, ask the question, optionally ask the follow-up 'why' turn."""
        result = AskResult(question=question, started=self.clock.now())
        try:
            result.conversation_id = self.create_conversation()
            context = [INLINE_INSTRUCTION] if explain_mode == "inline" else None
            result.answer = self.chat(result.conversation_id, question, additional_context=context)
            if explain_mode == "followup":
                try:
                    result.explain = self.chat(result.conversation_id, EXPLAIN_PROMPT)
                    result.why_text = result.explain.text
                    result.why_json = parse_json_block(result.why_text)
                except ChatApiError as exc:
                    result.why_text = "(follow-up turn failed: %s)" % exc
        except ChatApiError as exc:
            result.error = str(exc)
            result.http_status = exc.status
        except requests.RequestException as exc:
            result.error = "request failed: %s" % exc
            result.http_status = 0
        result.ended = self.clock.now()
        return result
