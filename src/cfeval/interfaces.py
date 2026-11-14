"""Core protocols and run configuration for pluggable targets, evidence sources, and scorers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class TargetTurn:
    """Normalized response returned by any evaluation Target."""

    question: str
    answer_text: str = ""
    attributions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: str = ""
    started: datetime | None = None
    ended: datetime | None = None
    latency_ms: float | None = None
    why_text: str = ""
    why_json: dict[str, Any] | None = None
    why_latency_ms: float | None = None
    http_status: int = 200
    error: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    routing_evidence: str = ""  # "" | "engine+citations" | "citations-only" | "tool_call" | "unverified"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class EngineEvidence:
    """Normalized engine/trace evidence collected for an ask."""

    status: str  # "observed" | "none" | "missing" | "incomplete" | "error" | "disabled"
    queries: list[dict[str, Any]] = field(default_factory=list)
    correlation_confidence: str = "none"  # "high" | "medium" | "low" | "none"
    routing_evidence: str = ""
    detail: str = ""


@dataclass(frozen=True)
class RunConfig:
    """Immutable run-level execution parameters."""

    target: str = "copilot-chat"
    option: str = "fabric-native"
    mock: bool = False
    profile: str = "tuned"
    repeats: int = 1
    explain_mode: str = "followup"
    trace_enabled: bool = False
    strict: bool = False
    gate_profile: str = "auto"  # "auto" | "with_engine_evidence" | "without_engine_evidence"
    gates: tuple[str, ...] = ()
    persona: str = ""
    shard_index: int = 0
    shard_total: int = 1
    max_questions: int | None = None
    max_judge_calls: int | None = None
    max_wall_seconds: float | None = None
    resume: bool = False
    as_of: datetime | None = None
    seed: int = 7


@runtime_checkable
class Target(Protocol):
    """Any conversational or imported surface evaluated by cfeval."""

    name: str
    surface: str
    supports_engine_trace: bool

    def ask(self, question: Any, *, attempt: int = 1, explain_mode: str = "followup", persona: str = "") -> Any: ...


@runtime_checkable
class EvidenceSource(Protocol):
    """Source of ground-truth engine queries (Workspace Monitoring, MCP tool calls, etc.)."""

    def collect(
        self,
        *,
        run_id: str,
        asks: list[dict[str, Any]],
        started: datetime,
        ended: datetime,
        user_upn: str = "",
    ) -> dict[str, Any]: ...


@runtime_checkable
class Scorer(Protocol):
    """Deterministic or model-assisted check producing a normalized check result."""

    name: str

    def score(self, question: Any, observation: dict[str, Any]) -> dict[str, Any]: ...
