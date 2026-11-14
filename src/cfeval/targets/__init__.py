"""Registry and plugin discovery for pluggable cfeval evaluation targets."""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any

from .copilot_chat import CopilotChatTarget
from .data_agent import FabricDataAgentTarget
from .mcp_reference import FabricIqMcpReferenceTarget, McpReferenceTarget
from .transcript_import import TranscriptImportTarget


class UnknownTargetError(KeyError, ValueError):
    """Raised when requesting a target name that is neither built-in nor registered."""


_REGISTRY: dict[str, tuple[Callable[..., Any], dict[str, Any]]] = {}
_ALIASES: dict[str, str] = {
    "m365-copilot-chat-graph": "copilot-chat",
    "import": "transcript-import",
    "fabric-iq-mcp-reference": "mcp-agent",
    "mcp-reference": "mcp-agent",
    "data-agent": "fabric-data-agent",
}
_BUILTIN_CLASSES = {
    CopilotChatTarget,
    TranscriptImportTarget,
    McpReferenceTarget,
    FabricDataAgentTarget,
}


def _metadata_from_factory(
    name: str,
    factory: Callable[..., Any],
    extra: dict[str, Any] | None = None,
    *,
    source: str = "registered",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": name,
        "surface": str(getattr(factory, "surface", name)),
        "supports_engine_trace": bool(getattr(factory, "supports_engine_trace", False)),
        "experimental": bool(getattr(factory, "experimental", False)),
        "description": (getattr(factory, "__doc__", "") or "").strip().splitlines()[0]
        if getattr(factory, "__doc__", None)
        else "",
        "source": source,
    }
    if extra:
        meta.update(extra)
    meta["name"] = name
    return meta


def register_target(
    name: str,
    factory: Callable[..., Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Register a custom evaluation target factory by name."""
    clean = name.strip()
    if not clean:
        raise ValueError("Target name must be non-empty")
    source = str((metadata or {}).get("source") or "registered")
    _REGISTRY[clean] = (factory, _metadata_from_factory(clean, factory, metadata, source=source))


def _register_builtins() -> None:
    for cls in (
        CopilotChatTarget,
        TranscriptImportTarget,
        McpReferenceTarget,
        FabricDataAgentTarget,
    ):
        register_target(cls.name, cls, metadata={"source": "builtin"})


_register_builtins()


def _discover_entry_points() -> dict[str, tuple[Callable[..., Any], dict[str, Any]]]:
    discovered: dict[str, tuple[Callable[..., Any], dict[str, Any]]] = {}
    try:
        eps = entry_points(group="cfeval.targets")
    except TypeError:  # pragma: no cover
        eps = entry_points().get("cfeval.targets", ())  # type: ignore[arg-type,assignment]
    for ep in eps:
        ep_name = ep.name.strip()
        if ep_name in _REGISTRY or ep_name in _ALIASES:
            continue
        try:
            loaded = ep.load()
        except Exception:
            continue
        if loaded in _BUILTIN_CLASSES:
            _ALIASES[ep_name] = str(getattr(loaded, "name", ep_name))
            continue
        discovered[ep_name] = (
            loaded,
            _metadata_from_factory(ep_name, loaded, None, source="entry_point"),
        )
    return discovered


def get_target(name: str, **kwargs: Any) -> Any:
    """Instantiate a registered or entry-point evaluation target by name."""
    clean = name.strip()
    canonical = _ALIASES.get(clean, clean)
    if canonical in _REGISTRY:
        factory, _meta = _REGISTRY[canonical]
        return factory(**kwargs)

    discovered = _discover_entry_points()
    canonical = _ALIASES.get(clean, clean)
    if canonical in _REGISTRY:
        factory, _meta = _REGISTRY[canonical]
        return factory(**kwargs)
    if canonical in discovered:
        factory, _meta = discovered[canonical]
        return factory(**kwargs)

    available = ", ".join(sorted(list(_REGISTRY.keys()) + list(discovered.keys())))
    raise UnknownTargetError(f"Unknown target {name!r}. Available targets: {available}")


def list_targets() -> list[dict[str, Any]]:
    """Return metadata dictionaries for all built-in, registered, and entry-point targets."""
    merged: dict[str, dict[str, Any]] = {name: dict(meta) for name, (_fn, meta) in _REGISTRY.items()}
    for ep_name, (_fn, meta) in _discover_entry_points().items():
        merged.setdefault(ep_name, dict(meta))
    return list(merged.values())


__all__ = [
    "CopilotChatTarget",
    "FabricDataAgentTarget",
    "FabricIqMcpReferenceTarget",
    "McpReferenceTarget",
    "TranscriptImportTarget",
    "UnknownTargetError",
    "get_target",
    "list_targets",
    "register_target",
]
