"""Pluggable target wrapping Microsoft 365 Copilot Chat (`CopilotChatClient` or `MockCopilotChat`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..chat import AskResult
from ..trace import FabricQuery


class CopilotChatTarget:
    """Adapter around CopilotChatClient / MockCopilotChat implementing the Target protocol."""

    name: str = "copilot-chat"
    surface: str = "copilot-chat-api"
    supports_engine_trace: bool = True
    experimental: bool = False

    def __init__(
        self,
        chat_client: Any = None,
        *,
        persona: str = "",
        monitoring: Any = None,
    ) -> None:
        self.chat_client = chat_client
        self.persona = persona.strip()
        self.monitoring = monitoring
        self.last_prompt: str = ""

    def _is_mock_lookup(self, raw_prompt: str, prefixed_prompt: str) -> bool:
        world = getattr(self.chat_client, "world", None)
        for attr in ("questions", "by_text"):
            lookup = getattr(world, attr, None)
            if isinstance(lookup, Mapping):
                return prefixed_prompt.strip() not in lookup and raw_prompt.strip() in lookup
        return False

    def ask(
        self,
        question: str | Any,
        explain_mode: str = "followup",
        *,
        attempt: int = 1,
        persona: str = "",
    ) -> AskResult:
        if self.chat_client is None:
            raise RuntimeError("CopilotChatTarget requires an initialized chat_client.")

        raw_prompt = str(getattr(question, "question", question) or "")
        q_persona = str(getattr(question, "persona", "") or "").strip() if not isinstance(question, str) else ""
        eff_persona = (persona or q_persona or self.persona).strip()

        if eff_persona:
            prefixed_prompt = "Context: Respond for persona '%s'.\n\n%s" % (eff_persona, raw_prompt)
        else:
            prefixed_prompt = raw_prompt

        self.last_prompt = prefixed_prompt
        use_raw = bool(eff_persona and self._is_mock_lookup(raw_prompt, prefixed_prompt))
        outbound = raw_prompt if use_raw else prefixed_prompt
        res: AskResult = self.chat_client.ask(outbound, explain_mode)
        return res

    def recorded_queries(self) -> list[FabricQuery]:
        return []
