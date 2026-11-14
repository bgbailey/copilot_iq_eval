"""Command line: python -m cfeval <command>  (run 'python -m cfeval -h')."""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import random
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__, runtime
from .clock import SimClock, SystemClock, iso, parse_iso, utc_now
from .config import Settings
from .golden import GoldenQuestion, golden_hash, load_golden, resolve_golden_path, write_golden
from .kqlgen import OPTIONAL_MARK, setup_commands, setup_script
from .pipeline import EvalHarness, deterministic_run_id, load_run
from .schema import TABLES
from .scoring import LocalBackend
from .sinks import EventhouseSink, JsonlSink

OPTIONS: dict[str, tuple[str, ...]] = {
    "fabric-native": ("fabric-native",),
    "foundry": ("foundry",),
    "both": ("fabric-native", "foundry"),
}
PROFILES_CLI = ("baseline", "untuned", "improving", "tuned", "ambiguous")
GATE_PROFILES_CLI = (
    "auto",
    "with_engine_evidence",
    "without_engine_evidence",
    "tool_call_evidence",
    "work_iq",
)
DEMO_USER = "eval.tester@contoso.com"
DEFAULT_DEMO_AS_OF = "2026-11-01T12:00:00Z"
DEFAULT_LINT_PATHS = (
    "data/golden/contoso.yaml",
    "data/golden/contoso-smoke.yaml",
    "data/golden/contoso-work.yaml",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_local_path(raw: str | Path) -> Path:
    p = Path(raw)
    if p.exists():
        return p
    candidate = _repo_root() / p
    if candidate.exists():
        return candidate
    pkg_dir = Path(__file__).resolve().parent
    norm = p.as_posix().lstrip("./")
    bundled_map = {
        "schemas/golden.schema.json": pkg_dir / "resources" / "golden.schema.json",
        "config/gates.yaml": pkg_dir / "resources" / "gates.yaml",
        "data/judge_calibration/answers.jsonl": pkg_dir / "resources" / "judge_calibration_answers.jsonl",
    }
    if norm in bundled_map and bundled_map[norm].exists():
        return bundled_map[norm]
    if norm.startswith("data/golden/"):
        sample_cand = pkg_dir / "sample" / Path(norm).name
        if sample_cand.exists():
            return sample_cand
    return p


def _parse_shard(raw: str | None) -> tuple[int, int]:
    if not raw:
        return (0, 1)
    parts = raw.strip().split("/")
    if len(parts) != 2:
        raise SystemExit("Invalid --shard %r: expected format 'i/N' (for example '0/2')." % raw)
    try:
        idx, total = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise SystemExit("Invalid --shard %r: shard index and total must be integers." % raw) from exc
    if total < 1 or not (0 <= idx < total):
        raise SystemExit("Invalid --shard %r: expected 0 <= i < N and N >= 1." % raw)
    return (idx, total)


def _eventhouse_sinks(settings: Settings, enabled: bool = True) -> list[EventhouseSink]:
    if not (enabled and settings.telemetry_enabled):
        return []
    return [
        EventhouseSink(
            settings.eventhouse_query_uri,
            settings.eventhouse_database,
            settings.eventhouse_ingest_uri,
            settings=settings,
        )
    ]


def _monitoring(settings: Settings, questions: Sequence[GoldenQuestion], log: Callable[..., Any]) -> tuple[Any, Any]:
    from .kusto import KustoQueryClient
    from .powerbi import DaxWatermark, DaxWatermarks, PowerBiClient
    from .trace import CombinedMonitoringSource, WorkspaceMonitoringSource

    raw = getattr(settings, "monitoring_sources", "")
    try:
        entries = (
            json.loads(raw)
            if raw
            else [
                {
                    "query_uri": settings.monitoring_query_uri,
                    "database": settings.monitoring_database,
                    "workspace_id": settings.semantic_model_workspace_id,
                }
            ]
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit("MONITORING_SOURCES must be a JSON list of monitoring sources: %s" % exc) from exc
    if (
        not isinstance(entries, list)
        or not entries
        or any(
            not isinstance(e, dict)
            or not all(isinstance(e.get(k), str) and e[k].strip() for k in ("query_uri", "database"))
            for e in entries
        )
    ):
        raise SystemExit("Each MONITORING_SOURCES entry needs query_uri and database.")
    sources = [
        WorkspaceMonitoringSource(KustoQueryClient(e["query_uri"], settings=settings), e["database"]) for e in entries
    ]
    monitoring = CombinedMonitoringSource(sources) if len(sources) > 1 else sources[0]
    watermark = None
    if all(e.get("workspace_id") for e in entries):
        try:
            client = PowerBiClient(settings=settings)
            watermark = DaxWatermarks(
                [DaxWatermark.for_questions(client, e["workspace_id"], questions, include_decoys=True) for e in entries]
            )
        except Exception as exc:
            log(
                "DAX watermark unavailable (%s); every configured monitoring source must show later event progress."
                % exc
            )
    return monitoring, watermark


def _instantiate_plugin_target(
    target_name: str,
    *,
    settings: Settings,
    mock: bool,
    questions: Sequence[GoldenQuestion],
    clock: Any,
    transcript_path: str | Path | None,
    profile: str,
    seed: int,
    persona: str,
    user: str,
    chat_client: Any = None,
    monitoring: Any = None,
) -> Any:
    from .targets import get_target

    clean = target_name.strip()
    tx_path = str(transcript_path or getattr(settings, "transcript_path", "") or "").strip()

    if clean in ("transcript-import", "import"):
        if not tx_path:
            raise SystemExit("Target 'transcript-import' requires --transcript <path> or TRANSCRIPT_PATH.")
        return get_target(
            clean,
            transcript_path=_resolve_local_path(tx_path),
            questions=questions,
            clock=clock,
            test_user=user,
        )

    if clean in ("mcp-agent", "mcp-reference", "fabric-iq-mcp-reference"):
        return get_target(
            clean,
            questions=questions,
            mock=mock,
            clock=clock,
            test_user=user,
            mcp_server_command=settings.mcp_server_command,
            workspace_id=settings.semantic_model_workspace_id or "00000000-0000-0000-0000-000000000001",
        )

    if clean in ("fabric-data-agent", "data-agent"):
        return get_target(
            clean,
            endpoint=settings.data_agent_endpoint,
            token_provider=(
                None if mock else lambda: runtime.token_for("https://api.fabric.microsoft.com", settings=settings)
            ),
            questions=questions,
            mock=mock,
            clock=clock,
            test_user=user,
            workspace_id=settings.semantic_model_workspace_id or "00000000-0000-0000-0000-000000000001",
        )

    if clean == "copilot-chat":
        return get_target(
            clean,
            chat_client=chat_client,
            persona=persona,
            monitoring=monitoring,
        )

    pool: dict[str, Any] = {
        "settings": settings,
        "mock": mock,
        "questions": questions,
        "clock": clock,
        "transcript_path": _resolve_local_path(tx_path) if tx_path else None,
        "profile": profile,
        "seed": seed,
        "persona": persona,
        "test_user": user,
        "chat_client": chat_client,
        "monitoring": monitoring,
    }
    try:
        from .targets import _ALIASES, _REGISTRY  # type: ignore[attr-defined]

        canonical = _ALIASES.get(clean, clean)
        if canonical in _REGISTRY:
            factory, _meta = _REGISTRY[canonical]
            sig = inspect.signature(factory)
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not has_var_kw:
                filtered = {k: v for k, v in pool.items() if k in sig.parameters}
                return get_target(clean, **filtered)
    except Exception:
        pass
    return get_target(clean, **pool)


def build_harness(
    settings: Settings,
    option: str = "fabric-native",
    mock: bool = False,
    trace: bool = True,
    publish: bool = True,
    run_name: str = "",
    notes: str = "",
    profile: str = "baseline",
    seed: int = 7,
    start: datetime | None = None,
    repeats: int | None = None,
    explain_mode: str | None = None,
    questions: Sequence[GoldenQuestion] | None = None,
    run_id: str | None = None,
    log: Callable[..., Any] = print,
    chat_required: bool = True,
    chat_max_retries: int = 4,
    judge_max_retries: int = 2,
    judge_max_calls: int | None = None,
    *,
    golden_override: str | Path | None = None,
    target_name: str = "",
    transcript_path: str | Path | None = None,
    gate_profile: str = "",
    gates: Sequence[str] | str = (),
    persona: str = "",
    shard: tuple[int, int] = (0, 1),
    max_questions: int | None = None,
    max_wall_seconds: float | None = None,
    resume: bool = False,
    expand_paraphrases: bool = False,
) -> EvalHarness:
    """Wire up an evaluation harness from settings. mock=True uses the simulated tenant (no network)."""
    backends = OPTIONS[option]
    configured_golden = str(golden_override) if golden_override else settings.golden_set
    golden_path: Path | None = None
    if questions is None:
        local_candidate = _resolve_local_path(configured_golden)
        golden_path = local_candidate if local_candidate.exists() else resolve_golden_path(configured_golden, log=log)
        loaded_questions = load_golden(golden_path, expand_paraphrases=expand_paraphrases)
    else:
        loaded_questions = list(questions)
        if expand_paraphrases:
            from .golden_v2 import expand_question_paraphrases

            loaded_questions = expand_question_paraphrases(loaded_questions)

    eff_target = (target_name or getattr(settings, "target", "") or "copilot-chat").strip()
    eff_transcript = str(transcript_path or getattr(settings, "transcript_path", "") or "").strip()
    if eff_transcript and eff_target == "copilot-chat" and not target_name:
        eff_target = "transcript-import"
    eff_gate_profile = (gate_profile or getattr(settings, "gate_profile", "") or "auto").strip()
    eff_persona = (persona or getattr(settings, "persona", "") or "").strip()

    common: dict[str, Any] = dict(
        questions=loaded_questions,
        backends=backends,
        output_dir=settings.output_dir,
        explain_mode=explain_mode or settings.explain_mode,
        repeats=repeats or settings.repeats,
        pause_seconds=settings.pause_seconds,
        trace_wait_seconds=settings.trace_wait_seconds,
        trace_poll_seconds=settings.trace_poll_seconds,
        trace_settle_seconds=getattr(settings, "trace_settle_seconds", 40.0),
        golden_name=golden_path.name if golden_path else Path(configured_golden).name,
        golden_hash=golden_hash(golden_path) if golden_path else "",
        run_name=run_name,
        notes=notes,
        settings_public=settings.public(),
        log=log,
        run_id=run_id,
        gate_profile=eff_gate_profile,
        gates=gates,
        persona=eff_persona,
        shard=shard,
        max_questions=max_questions,
        max_wall_seconds=max_wall_seconds,
        resume=resume,
    )

    if eff_target != "copilot-chat":
        use_sim = mock or eff_target in ("transcript-import", "import")
        clock: Any = SimClock(start or utc_now()) if use_sim else SystemClock()
        user = settings.test_user_upn or DEMO_USER
        plugin_target = _instantiate_plugin_target(
            eff_target,
            settings=settings,
            mock=mock,
            questions=loaded_questions,
            clock=clock,
            transcript_path=eff_transcript or None,
            profile=profile,
            seed=seed,
            persona=eff_persona,
            user=user,
        )
        canonical_name = str(getattr(plugin_target, "name", eff_target) or eff_target)
        supports_trace = bool(getattr(plugin_target, "supports_engine_trace", False))
        plugin_mon = (
            getattr(plugin_target, "monitoring", None)
            if (trace and (supports_trace or eff_gate_profile == "with_engine_evidence"))
            else None
        )
        if mock:
            from .mock import LocalFoundryEmulator, MockJudge

            m_judge = MockJudge(max_calls=judge_max_calls)
            return EvalHarness(
                target=plugin_target,
                target_name=canonical_name,
                clock=clock,
                rng=random.Random("%s|%s|%s" % (seed, profile, option)),
                local_backend=LocalBackend(judge=m_judge, gate_on_judge=settings.judge_gates_verdict),
                foundry_runner=LocalFoundryEmulator(
                    include_trace=(plugin_mon is not None),
                    include_builtin=settings.foundry_builtin_evaluators,
                ),
                monitoring=plugin_mon,
                watermark=None,
                extra_sinks=() if mock else _eventhouse_sinks(settings, publish),
                test_user=user,
                trace_user=user,
                judge_model=m_judge.model_name,
                surface=str(getattr(plugin_target, "surface", canonical_name)),
                host=runtime.host_name(),
                **common,
            )

        live_judge = None
        if "fabric-native" in backends:
            from .judge import make_judge

            live_judge = make_judge(settings, max_retries=judge_max_retries, max_calls=judge_max_calls)
        live_foundry = None
        if "foundry" in backends:
            if not settings.foundry_enabled:
                raise SystemExit("Option 2 needs FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_EVAL_DEPLOYMENT.")
            from .credentials import foundry_credential
            from .foundry import FoundryEvaluation

            live_foundry = FoundryEvaluation(
                settings.foundry_project_endpoint,
                settings.foundry_eval_deployment,
                credential=foundry_credential(settings),
                include_trace=(plugin_mon is not None),
                include_builtin=settings.foundry_builtin_evaluators,
                log=log,
            )
        j_model = (
            (live_judge.model_name if live_judge else "")
            if "fabric-native" in backends
            else settings.foundry_eval_deployment
        )
        return EvalHarness(
            target=plugin_target,
            target_name=canonical_name,
            clock=clock,
            rng=random.Random("%s|%s|%s" % (seed, profile, option)),
            local_backend=LocalBackend(judge=live_judge, gate_on_judge=settings.judge_gates_verdict),
            foundry_runner=live_foundry,
            monitoring=plugin_mon,
            watermark=None,
            extra_sinks=_eventhouse_sinks(settings, publish),
            test_user=user,
            trace_user=settings.effective_trace_user or user,
            judge_model=j_model,
            surface=str(getattr(plugin_target, "surface", canonical_name)),
            host=runtime.host_name(),
            **common,
        )

    if mock:
        from .mock import (
            LocalFoundryEmulator,
            MockCopilotChat,
            MockJudge,
            MockMonitoringSource,
            MockWatermark,
            MockWorld,
        )

        sim_clock = SimClock(start or utc_now())
        user = settings.test_user_upn or DEMO_USER
        world = MockWorld(sim_clock, loaded_questions, profile=profile, seed=seed, test_user=user)
        mock_chat = MockCopilotChat(world)
        mock_mon = MockMonitoringSource(world) if trace else None
        mock_wm = MockWatermark(world) if trace else None
        mock_judge = MockJudge(max_calls=judge_max_calls)
        mock_target = None
        if eff_persona:
            try:
                mock_target = _instantiate_plugin_target(
                    "copilot-chat",
                    settings=settings,
                    mock=True,
                    questions=loaded_questions,
                    clock=sim_clock,
                    transcript_path=None,
                    profile=profile,
                    seed=seed,
                    persona=eff_persona,
                    user=user,
                    chat_client=mock_chat,
                    monitoring=mock_mon,
                )
            except Exception:
                mock_target = None
        return EvalHarness(
            chat=None if mock_target is not None else mock_chat,
            target=mock_target,
            target_name="copilot-chat",
            clock=sim_clock,
            rng=random.Random("%s|%s|%s" % (seed, profile, option)),
            local_backend=LocalBackend(judge=mock_judge, gate_on_judge=settings.judge_gates_verdict),
            foundry_runner=LocalFoundryEmulator(
                include_trace=trace,
                include_builtin=settings.foundry_builtin_evaluators,
            ),
            monitoring=mock_mon,
            watermark=mock_wm,
            extra_sinks=(),
            test_user=user,
            trace_user=user,
            judge_model=MockJudge.model_name,
            surface="simulated",
            host=runtime.host_name(),
            **common,
        )

    chat = None
    if chat_required:
        from .auth import DelegatedAuth
        from .chat import CopilotChatClient

        if not (settings.tenant_id and settings.client_id and settings.test_user_upn):
            raise SystemExit("Set TENANT_ID, CLIENT_ID and TEST_USER_UPN (see .env.example), or use --mock.")
        auth = DelegatedAuth.from_settings(settings)
        chat = CopilotChatClient(auth.token, time_zone=settings.time_zone, max_retries=chat_max_retries)
    monitoring = watermark = None
    if trace and settings.trace_enabled and not settings.effective_trace_user:
        raise SystemExit("Set TEST_USER_UPN or TRACE_USER so DAX can be matched to the test user's asks.")
    if trace and settings.trace_enabled:
        monitoring, watermark = _monitoring(settings, loaded_questions, log)
    elif trace:
        log("DAX capture is off: set MONITORING_QUERY_URI and MONITORING_DATABASE to capture Fabric IQ's DAX.")
    judge = None
    if "fabric-native" in backends:
        from .judge import make_judge

        judge = make_judge(settings, max_retries=judge_max_retries, max_calls=judge_max_calls)
        if judge is None:
            log("No judge model configured (JUDGE_ENDPOINT): Option 1 runs deterministic checks only.")
    foundry_runner = None
    if "foundry" in backends:
        if not settings.foundry_enabled:
            raise SystemExit("Option 2 needs FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_EVAL_DEPLOYMENT.")
        from .credentials import foundry_credential
        from .foundry import FoundryEvaluation

        foundry_runner = FoundryEvaluation(
            settings.foundry_project_endpoint,
            settings.foundry_eval_deployment,
            credential=foundry_credential(settings),
            include_trace=monitoring is not None,
            include_builtin=settings.foundry_builtin_evaluators,
            log=log,
        )
    judge_model = (
        (judge.model_name if judge else "") if "fabric-native" in backends else settings.foundry_eval_deployment
    )
    return EvalHarness(
        chat=chat,
        target_name="copilot-chat",
        clock=SystemClock(),
        local_backend=LocalBackend(judge=judge, gate_on_judge=settings.judge_gates_verdict),
        foundry_runner=foundry_runner,
        monitoring=monitoring,
        watermark=watermark,
        extra_sinks=_eventhouse_sinks(settings, publish),
        test_user=settings.test_user_upn,
        trace_user=settings.effective_trace_user,
        judge_model=judge_model,
        surface="copilot-chat-api",
        host=runtime.host_name(),
        **common,
    )


def simulate_runs(
    settings: Settings,
    runs: int = 8,
    days: int = 7,
    seed: int = 7,
    publish: bool = False,
    log: Callable[..., Any] = print,
    *,
    as_of: str | None = None,
    output_dir: str | Path | None = None,
    golden_override: str | Path | None = None,
) -> list[Any]:
    """Simulated runs that tell a progression story (baseline -> improving -> tuned), spread over past days."""
    profiles_default = ["baseline", "baseline", "improving", "improving", "tuned", "tuned"]
    profiles_8 = ["baseline", "baseline", "baseline", "improving", "improving", "tuned", "tuned", "tuned"]
    options_8 = ["fabric-native", "foundry", "both", "fabric-native", "foundry", "fabric-native", "foundry", "both"]
    options_default = ["fabric-native", "foundry", "both"]
    outcomes: list[Any] = []
    if publish and not settings.telemetry_enabled:
        raise SystemExit("Set EVENTHOUSE_QUERY_URI and EVENTHOUSE_DATABASE before using demo-data --publish.")
    eff_settings = dataclasses.replace(settings, output_dir=str(output_dir)) if output_dir is not None else settings
    anchor = parse_iso(as_of) if as_of else utc_now()
    today = anchor - timedelta(hours=3)
    for i in range(runs):
        if runs == 8:
            profile = profiles_8[i]
            opt = options_8[i]
        else:
            profile = profiles_default[min(i * len(profiles_default) // max(runs, 1), len(profiles_default) - 1)]
            opt = options_default[i % len(options_default)]
        start = today - timedelta(days=round(days * (runs - 1 - i) / max(runs - 1, 1)), hours=-(i % 3))
        det_id = deterministic_run_id(seed, profile, opt, i, start=start) if as_of else None
        harness = build_harness(
            eff_settings,
            option=opt,
            mock=True,
            publish=False,
            profile=profile,
            seed=seed + i,
            start=start,
            run_id=det_id,
            golden_override=golden_override,
            run_name="Simulated %s run %d" % (profile, i + 1),
            notes="Simulated data (profile %s)" % profile,
            log=lambda *_: None,
        )
        if publish:
            harness.sink.others.extend(_eventhouse_sinks(eff_settings))
        outcomes.append(harness.run())
        log(
            "%s  %-13s %-26s pass rate %s"
            % (
                outcomes[-1].run_id,
                profile,
                outcomes[-1].run_row["EvalOption"],
                "%.0f%%" % (100 * (outcomes[-1].metrics["PassRate"] or 0)),
            )
        )
    return outcomes


def app_sample(
    outcomes: Sequence[Any],
    tables: Sequence[str] = ("EvalRun", "EvalQuestion", "EvalResult", "FabricIqQuery", "EvalEvent"),
    *,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    gen_str = iso(parse_iso(generated_utc)) if generated_utc else iso(utc_now())
    data: dict[str, Any] = {"generatedUtc": gen_str, "simulated": True, "tables": {t: [] for t in tables}}
    seen_by_table: dict[str, set[str]] = {t: set() for t in tables}
    for o in outcomes:
        sink = JsonlSink(o.folder)
        for t in tables:
            for row in sink.read(t):
                rid = str(row.get("RowId") or "")
                if rid and rid in seen_by_table[t]:
                    continue
                if rid:
                    seen_by_table[t].add(rid)
                data["tables"][t].append(row)
    return data


def _republish(
    settings: Settings,
    folder: Path,
    tables: Sequence[str] | None = None,
    log: Callable[..., Any] = print,
) -> None:
    sinks = _eventhouse_sinks(settings)
    if not sinks:
        raise SystemExit("Set EVENTHOUSE_QUERY_URI and EVENTHOUSE_DATABASE to publish.")
    unknown = set(tables or []) - set(TABLES)
    if unknown:
        raise SystemExit("Unknown table(s): %s" % ", ".join(sorted(unknown)))
    src = JsonlSink(folder)
    for table in tables or TABLES:
        rows = src.read(table)
        if rows:
            sinks[0].write(table, rows)
            log("Published %d %s rows" % (len(rows), table))


def cmd_doctor(settings: Settings, args: argparse.Namespace) -> int:
    def mark(ok: Any) -> str:
        return "ok " if ok else "-- "

    print("cfeval %s on %s" % (__version__, runtime.host_name()))
    checks = [
        (
            "Copilot Chat sign-in (TENANT_ID, CLIENT_ID, TEST_USER_UPN)",
            settings.tenant_id and settings.client_id and settings.test_user_upn,
        ),
        ("Telemetry Eventhouse (EVENTHOUSE_QUERY_URI, EVENTHOUSE_DATABASE)", settings.telemetry_enabled),
        ("DAX capture (MONITORING_QUERY_URI, MONITORING_DATABASE)", settings.trace_enabled),
        ("DAX watermark / golden refresh (SEMANTIC_MODEL_WORKSPACE_ID)", settings.semantic_model_workspace_id),
        ("Option 1 judge model (JUDGE_ENDPOINT, JUDGE_DEPLOYMENT)", settings.judge_enabled),
        ("Option 2 Foundry project (FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_EVAL_DEPLOYMENT)", settings.foundry_enabled),
    ]
    for label, ok in checks:
        print("  %s%s" % (mark(ok), label))
    try:
        path = resolve_golden_path(settings.golden_set, log=lambda *_: None)
        questions = load_golden(path)
        print("  ok golden set %s: %d questions" % (path, len(questions)))
    except Exception as exc:
        print("  !! golden set %s: %s" % (settings.golden_set, exc))
    for module, extra in (
        ("msal", "copilot"),
        ("azure.kusto.data", "kusto"),
        ("azure.kusto.ingest", "kusto"),
        ("openai", "judge"),
        ("azure.identity", "judge"),
        ("azure.ai.projects", "foundry"),
    ):
        try:
            __import__(module)
            print("  ok package %s" % module)
        except ImportError:
            print('  -- package %s (pip install "cfeval[%s]")' % (module, extra))

    strict_errors = 0
    try:
        import importlib.metadata as _im

        _im.version("fabric-data-agent-sdk")
        _im.version("azure-ai-projects")
        strict_errors += 1
        print(
            "  !! dependency conflict: fabric-data-agent-sdk (openai<3) and azure-ai-projects (openai>=3) "
            "cannot share one environment; use separate virtual environments."
        )
    except Exception:
        pass

    from .judge import judge_prompt_hash

    p_hash = judge_prompt_hash()
    cal_file = _resolve_local_path("data/judge_calibration/answers.jsonl")
    if settings.judge_enabled and not cal_file.exists():
        print("  -- judge prompt %s has no local calibration dataset (%s)" % (p_hash[:12], cal_file))

    if getattr(args, "strict", False):
        import re as _re

        guid_re = _re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        for g_label, g_val in (
            ("TENANT_ID", settings.tenant_id),
            ("CLIENT_ID", settings.client_id),
            ("SEMANTIC_MODEL_WORKSPACE_ID", settings.semantic_model_workspace_id),
            ("EVENTHOUSE_WORKSPACE_ID", settings.eventhouse_workspace_id),
            ("EVENTHOUSE_DATABASE_ID", settings.eventhouse_database_id),
            ("LAKEHOUSE_WORKSPACE_ID", settings.lakehouse_workspace_id),
            ("LAKEHOUSE_ID", settings.lakehouse_id),
        ):
            if g_val and not guid_re.match(g_val.strip()):
                strict_errors += 1
                print("  !! strict: %s is not a valid UUID (%s)" % (g_label, g_val))
        for u_label, u_val in (
            ("EVENTHOUSE_QUERY_URI", settings.eventhouse_query_uri),
            ("EVENTHOUSE_INGEST_URI", settings.eventhouse_ingest_uri),
            ("MONITORING_QUERY_URI", settings.monitoring_query_uri),
            ("JUDGE_ENDPOINT", settings.judge_endpoint),
            ("FOUNDRY_PROJECT_ENDPOINT", settings.foundry_project_endpoint),
            ("KEY_VAULT_URL", settings.key_vault_url),
        ):
            if u_val and not u_val.strip().lower().startswith("https://"):
                strict_errors += 1
                print("  !! strict: %s must be an https:// URL (%s)" % (u_label, u_val))
        if settings.repeats < 1 or settings.http_timeout_s <= 0:
            strict_errors += 1
            print("  !! strict: REPEATS must be >= 1 and HTTP_TIMEOUT_S must be > 0")
        try:
            g_check = resolve_golden_path(settings.golden_set, log=lambda *_: None)
            load_golden(g_check)
        except Exception as exc:
            strict_errors += 1
            print("  !! strict: golden set load failed: %s" % exc)

    token_failures = 0
    if getattr(args, "verify_tokens", False):
        from .auth import verify_token_claims

        cache_spec = settings.token_cache.strip()
        if cache_spec.lower() == "keyvault":
            print("  -- token cache uses Key Vault (%s); skip local file inspection" % settings.key_vault_url)
        else:
            cache_path = Path(cache_spec)
            if not cache_path.is_file():
                print("  -- token cache file not found (%s)" % cache_path)
            else:
                try:
                    cache_json = json.loads(cache_path.read_text(encoding="utf-8"))
                    access_tokens = (cache_json.get("AccessToken") or {}) if isinstance(cache_json, dict) else {}
                    if not access_tokens:
                        print("  -- token cache %s contains 0 cached access tokens" % cache_path)
                    for key, entry in access_tokens.items():
                        secret = entry.get("secret", "") if isinstance(entry, dict) else ""
                        if not secret:
                            continue
                        ver = verify_token_claims(
                            secret,
                            expected_tid=settings.tenant_id,
                            expected_upn=settings.test_user_upn,
                            allow_app_only=False,
                        )
                        if ver["ok"]:
                            print("  ok cached token %s (upn=%s)" % (str(key)[:24], ver.get("upn") or "n/a"))
                        else:
                            token_failures += 1
                            print("  !! cached token %s failed: %s" % (str(key)[:24], "; ".join(ver["issues"])))
                except Exception as exc:
                    token_failures += 1
                    print("  !! token cache %s could not be inspected: %s" % (cache_path, exc))
    return 1 if (token_failures or strict_errors) else 0


def cmd_login(settings: Settings, args: argparse.Namespace) -> int:
    from .auth import DelegatedAuth, browser_login_callback

    auth = DelegatedAuth.from_settings(settings, login_callback=browser_login_callback(settings))
    auth.token(interactive=True)
    print(
        "Verified Copilot Chat test user %s in tenant %s; private token cache saved."
        % (auth.signed_in_upn(), settings.tenant_id)
    )
    return 0


def cmd_kql(settings: Settings, args: argparse.Namespace) -> int:
    text = setup_script(args.database or settings.eventhouse_database, args.onelake_latency)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print("Wrote %s" % args.out)
    else:
        print(text)
    return 0


def cmd_setup_eventhouse(settings: Settings, args: argparse.Namespace) -> int:
    if not settings.telemetry_enabled:
        raise SystemExit("Set EVENTHOUSE_QUERY_URI and EVENTHOUSE_DATABASE first.")
    from .kusto import KustoQueryClient

    client = KustoQueryClient(settings.eventhouse_query_uri, settings=settings)
    failures = 0
    for command in setup_commands(settings.eventhouse_database, getattr(args, "onelake_latency", 5)):
        optional = command.startswith(OPTIONAL_MARK)
        body = command.split("\n", 1)[1] if optional else command
        try:
            client.mgmt(settings.eventhouse_database, body)
            print("ok  %s" % body.splitlines()[0][:100], flush=True)
        except Exception as exc:
            prefix = "--" if optional else "!! "
            print("%s %s\n    %s" % (prefix, body.splitlines()[0][:100], str(exc)[:300]), flush=True)
            failures += 0 if optional else 1
            if not optional:
                return 1
    return 1 if failures else 0


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    eff_golden = args.golden or settings.golden_set
    questions: list[GoldenQuestion] | None = None
    if args.questions:
        wanted = [q.strip() for q in args.questions.split(",") if q.strip()]
        g_local = _resolve_local_path(eff_golden)
        g_path = g_local if g_local.exists() else resolve_golden_path(eff_golden)
        everything = load_golden(g_path, expand_paraphrases=bool(args.expand_paraphrases))
        questions = [q for q in everything if q.id in wanted]
        unknown = sorted(set(wanted) - {q.id for q in questions})
        if unknown:
            raise SystemExit("Unknown question id(s): %s" % ", ".join(unknown))

    shard = _parse_shard(args.shard)
    gates_override = [g.strip() for g in (args.gates or "").split(",") if g.strip()]
    m365_src = getattr(args, "from_m365_copilot_eval", None)
    eff_target = (args.target or "") or ("import" if m365_src else "")
    eff_transcript = m365_src or args.transcript

    harness = build_harness(
        settings,
        option=args.option,
        mock=args.mock,
        trace=not args.no_trace,
        publish=not args.no_publish,
        run_name=args.name or "",
        notes=args.notes or "",
        profile=args.profile,
        seed=args.seed,
        repeats=args.repeats,
        explain_mode=args.explain,
        questions=questions,
        run_id=args.run_id,
        judge_max_calls=args.max_judge_calls,
        golden_override=args.golden,
        target_name=eff_target,
        transcript_path=eff_transcript,
        gate_profile=args.gate_profile or "",
        gates=gates_override,
        persona=args.persona or "",
        shard=shard,
        max_questions=args.max_questions,
        max_wall_seconds=args.max_wall_seconds,
        resume=bool(args.resume),
        expand_paraphrases=bool(args.expand_paraphrases) if questions is None else False,
    )
    outcome = harness.run()
    print(outcome.summary_text())

    if args.html:
        from .report import render_html_report

        html_out = render_html_report(outcome.folder, out_path=Path(args.html))
        print("Wrote HTML report %s" % html_out)

    if args.otel_out:
        from .otel import export_otel_spans

        otel_out = export_otel_spans(outcome.folder, out_path=Path(args.otel_out), endpoint=settings.otel_endpoint)
        print("Wrote OTel spans %s" % otel_out)

    if outcome.sink_errors:
        return 3
    if outcome.status in ("partial", "failed"):
        return 2
    if args.strict:
        pass_rate = float(outcome.metrics.get("PassRate") or 0.0)
        errors = int(outcome.metrics.get("error") or 0)
        crit_failed = int(outcome.stats.get("critical_failures") or 0)
        if errors > 0 or crit_failed > 0 or pass_rate < args.min_pass_rate:
            return 1
    return 0


def cmd_rescore(settings: Settings, args: argparse.Namespace) -> int:
    folder = Path(args.run_folder)
    questions, _asks = load_run(folder)
    settings.output_dir = str(folder.parent)
    if not args.mock and not settings.trace_enabled and not args.no_trace:
        raise SystemExit(
            "rescore re-captures DAX: set MONITORING_QUERY_URI and MONITORING_DATABASE, or pass --no-trace."
        )
    harness = build_harness(
        settings,
        option=args.option,
        mock=bool(args.mock),
        trace=not args.no_trace,
        questions=questions,
        run_id=folder.name,
        publish=not args.no_publish,
        chat_required=False,
    )
    outcome = harness.rescore()
    print(outcome.summary_text())
    return 3 if outcome.sink_errors else 2 if outcome.status in ("partial", "failed") else 0


def cmd_publish(settings: Settings, args: argparse.Namespace) -> int:
    tables = [t.strip() for t in args.tables.split(",")] if args.tables else None
    _republish(settings, Path(args.run_folder), tables)
    return 0


def cmd_golden_refresh(settings: Settings, args: argparse.Namespace) -> int:
    from .powerbi import PowerBiClient, refresh_expected_values

    if not settings.semantic_model_workspace_id:
        raise SystemExit("Set SEMANTIC_MODEL_WORKSPACE_ID (the workspace that holds the semantic models).")
    path = resolve_golden_path(settings.golden_set)
    questions = load_golden(path)
    report = refresh_expected_values(questions, PowerBiClient(settings=settings), settings.semantic_model_workspace_id)
    for r in report:
        print(
            "%-5s %-9s %-22s %s -> %s %s"
            % (r["QuestionId"], r["Status"], r["Model"][:22], r["Old"], r["New"], r["Detail"])
        )
    if args.write:
        write_golden(questions, path)
        print("Updated %s" % path)
    return 1 if any(r["Status"] == "error" for r in report) else 0


def cmd_shortcuts(settings: Settings, args: argparse.Namespace) -> int:
    from .fabric_rest import FabricClient, create_app_shortcuts

    results = create_app_shortcuts(
        FabricClient(settings=settings),
        args.lakehouse_workspace,
        args.lakehouse,
        args.kql_workspace,
        args.kql_database,
        path=args.path,
    )
    return 1 if any(r["status"] != "ok" for r in results) else 0


def cmd_demo_data(settings: Settings, args: argparse.Namespace) -> int:
    golden_choice: Path | str | None = args.golden
    if not golden_choice:
        smoke_candidate = _resolve_local_path("data/golden/contoso-smoke.yaml")
        if smoke_candidate.exists():
            golden_choice = smoke_candidate

    staging_root = Path(args.app_json).resolve().parent if args.app_json else Path(settings.output_dir).resolve()
    staging_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".demo-data-", dir=str(staging_root)))
    try:
        outcomes = simulate_runs(
            settings,
            runs=args.runs,
            days=args.days,
            seed=args.seed,
            publish=args.publish,
            as_of=args.as_of,
            output_dir=tmp_dir,
            golden_override=golden_choice,
        )
        if args.app_json:
            payload = app_sample(outcomes, generated_utc=args.as_of)
            out_path = Path(args.app_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
            print("Wrote %s" % args.app_json)
        return 3 if any(o.sink_errors for o in outcomes) else 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def cmd_golden_lint(settings: Settings, args: argparse.Namespace) -> int:
    from .golden_v2 import validate_golden_file

    raw_paths = list(args.paths) if args.paths else list(DEFAULT_LINT_PATHS)
    invalid = 0
    for raw in raw_paths:
        resolved = _resolve_local_path(raw)
        res = validate_golden_file(resolved, raise_on_error=False)
        warnings = res.get("warnings") or []
        if res.get("valid"):
            print("ok  %s: %d questions (%d warnings)" % (resolved, res.get("count", 0), len(warnings)))
            for w in warnings:
                print("    warn: %s" % w)
        else:
            invalid += 1
            print("ERR %s: validation failed" % resolved)
            for err in res.get("errors") or []:
                print("    error: %s" % err)
    return 1 if invalid else 0


def _load_latest_results_for_compare(folder: Path, backend: str) -> tuple[list[dict[str, Any]], int]:
    sink = JsonlSink(folder)
    runs = sink.read("EvalRun")
    k_val = int(runs[-1].get("K") or runs[-1].get("Repeats") or 1) if runs else 1
    all_rows = sink.read("EvalResult")
    if not all_rows:
        raise SystemExit("No EvalResult rows found in %s." % folder)
    matching = [r for r in all_rows if r.get("Backend") == backend]
    chosen = matching if matching else all_rows
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for r in chosen:
        key = (str(r.get("AskId") or ""), str(r.get("Backend") or ""))
        prev = dedup.get(key)
        if prev is None or str(r.get("ScoredUtc") or "") >= str(prev.get("ScoredUtc") or ""):
            dedup[key] = r
    return list(dedup.values()), k_val


def cmd_compare(settings: Settings, args: argparse.Namespace) -> int:
    from .stats import compare_runs

    base_dir = Path(args.baseline)
    cand_dir = Path(args.candidate)
    base_rows, base_k = _load_latest_results_for_compare(base_dir, args.backend)
    cand_rows, cand_k = _load_latest_results_for_compare(cand_dir, args.backend)
    cmp = compare_runs(base_rows, cand_rows, k=max(base_k, cand_k), alpha=args.alpha)

    b_lo, b_hi = cmp["baseline_wilson"]
    c_lo, c_hi = cmp["candidate_wilson"]
    regressions = list(cmp["regressions"])
    improvements = list(cmp["improvements"])

    md_lines = [
        "# Evaluation Run Comparison",
        "",
        "| Metric | Baseline (`%s`) | Candidate (`%s`) | Delta |" % (base_dir.name, cand_dir.name),
        "|---|---:|---:|---:|",
        "| Pass rate | %.1f%% | %.1f%% | %+.1f%% |"
        % (100 * cmp["baseline_pass_rate"], 100 * cmp["candidate_pass_rate"], 100 * cmp["delta_pass_rate"]),
        "| 95%% Wilson CI | [%.1f%%, %.1f%%] | [%.1f%%, %.1f%%] | — |"
        % (100 * b_lo, 100 * b_hi, 100 * c_lo, 100 * c_hi),
        "| Paired questions | %d | %d | — |" % (cmp["paired_questions"], cmp["paired_questions"]),
        "| Regressions (b) | — | %d | %s |" % (cmp["b"], ", ".join(regressions) or "none"),
        "| Improvements (c) | — | %d | %s |" % (cmp["c"], ", ".join(improvements) or "none"),
        "| McNemar exact p-value | — | %.4f | %s |"
        % (cmp["mcnemar_p"], "significant" if cmp["significant"] else "not significant"),
    ]
    md_text = "\n".join(md_lines) + "\n"
    print(md_text, end="")

    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(md_text, encoding="utf-8")
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(cmp, indent=2, default=str) + "\n", encoding="utf-8")

    return 1 if len(regressions) > args.max_regressions else 0


def cmd_calibrate_judge(settings: Settings, args: argparse.Namespace) -> int:
    from .judge import MockJudge as CalMockJudge
    from .judge import calibrate_judge, make_judge

    ds_path = _resolve_local_path(args.dataset)
    if args.mock:
        judge: Any = CalMockJudge()
    else:
        judge = make_judge(settings)
        if judge is None:
            raise SystemExit("Set JUDGE_ENDPOINT and JUDGE_DEPLOYMENT to calibrate a live judge, or pass --mock.")

    res = calibrate_judge(judge, ds_path, min_kappa=args.min_kappa)
    ok = bool(res.get("ok", res.get("passed", False)))
    res["ok"] = ok

    print(
        "Judge calibration (%s): kappa=%.4f (min=%.2f) accuracy=%.1f%% precision=%.1f%% fail_recall=%.1f%% "
        "[TP=%d TN=%d FP=%d FN=%d] -> %s"
        % (
            res["model_name"],
            res["kappa"],
            res["min_kappa"],
            100 * res["accuracy"],
            100 * res["pass_precision"],
            100 * res["fail_recall"],
            res["tp"],
            res["tn"],
            res["fp"],
            res["fn"],
            "PASS" if ok else "FAIL",
        )
    )
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    return 0 if ok else 1


def cmd_report(settings: Settings, args: argparse.Namespace) -> int:
    from .report import render_html_report

    target_dir = getattr(args, "run_folder", None) or getattr(args, "run_dir", None)
    if not target_dir:
        raise SystemExit("Pass a run folder path (positional <run_folder> or --run-dir <dir>).")
    cmp_dir = getattr(args, "baseline", None) or getattr(args, "compare", None)
    out = render_html_report(
        Path(target_dir),
        out_path=Path(args.out) if args.out else None,
        compare_dir=Path(cmp_dir) if cmp_dir else None,
    )
    print("Wrote HTML report %s" % out)
    return 0


def cmd_export(settings: Settings, args: argparse.Namespace) -> int:
    fmt = args.format
    out_path = Path(args.out)
    if fmt == "otel":
        if not args.run_dir:
            raise SystemExit("export --format otel requires --run-dir <dir>.")
        from .otel import export_otel_spans

        written = export_otel_spans(Path(args.run_dir), out_path=out_path, endpoint=settings.otel_endpoint)
    elif fmt == "foundry":
        if not args.run_dir:
            raise SystemExit("export --format foundry requires --run-dir <dir>.")
        from .interop import export_foundry_jsonl

        written = export_foundry_jsonl(Path(args.run_dir), out_path)
    elif fmt == "promptfoo":
        golden_src = _resolve_local_path(args.golden or settings.golden_set)
        if not golden_src.exists():
            golden_src = resolve_golden_path(args.golden or settings.golden_set)
        from .interop import export_promptfoo

        written = export_promptfoo(golden_src, out_path)
    elif fmt == "m365-copilot-eval":
        golden_src = _resolve_local_path(args.golden or settings.golden_set)
        if not golden_src.exists():
            golden_src = resolve_golden_path(args.golden or settings.golden_set)
        from .interop import export_m365_copilot_eval

        written = export_m365_copilot_eval(golden_src, out_path)
    else:
        raise SystemExit("Unsupported export format: %s" % fmt)
    print("Exported %s to %s" % (fmt, written))
    return 0


def cmd_targets(settings: Settings, args: argparse.Namespace) -> int:
    from .targets import list_targets

    entries = list_targets()
    for t in entries:
        exp_tag = " [experimental]" if t.get("experimental") else ""
        trace_tag = "trace=yes" if t.get("supports_engine_trace") else "trace=no"
        print(
            "%-20s surface=%-20s %-10s%s  %s"
            % (t["name"], t.get("surface", ""), trace_tag, exp_tag, t.get("description", ""))
        )
    return 0


def cmd_setup(settings: Settings, args: argparse.Namespace) -> int:
    if not args.skip_eventhouse:
        rc = cmd_setup_eventhouse(settings, args)
        if rc != 0:
            return rc
    if not args.skip_shortcuts:
        lh_ws = args.lakehouse_workspace or settings.lakehouse_workspace_id
        lh_id = args.lakehouse or settings.lakehouse_id
        kql_ws = args.kql_workspace or settings.eventhouse_workspace_id
        kql_db = args.kql_database or settings.eventhouse_database_id
        sc_path = args.path or settings.lakehouse_shortcut_path or "Tables"
        if not (lh_ws and lh_id and kql_ws and kql_db):
            raise SystemExit(
                "Set LAKEHOUSE_WORKSPACE_ID, LAKEHOUSE_ID, EVENTHOUSE_WORKSPACE_ID, and EVENTHOUSE_DATABASE_ID "
                "(or pass --skip-shortcuts)."
            )
        sc_ns = argparse.Namespace(
            lakehouse_workspace=lh_ws,
            lakehouse=lh_id,
            kql_workspace=kql_ws,
            kql_database=kql_db,
            path=sc_path,
        )
        rc = cmd_shortcuts(settings, sc_ns)
        if rc != 0:
            return rc
    return 0


def cmd_verify(settings: Settings, args: argparse.Namespace) -> int:
    from .golden_v2 import validate_golden_file

    golden_raw = args.golden or settings.golden_set
    g_local = _resolve_local_path(golden_raw)
    g_path = g_local if g_local.exists() else resolve_golden_path(golden_raw, log=lambda *_: None)
    lint = validate_golden_file(g_path, raise_on_error=False)
    if not lint.get("valid"):
        print("ERR golden validation failed for %s: %s" % (g_path, "; ".join(lint.get("errors") or [])))
        return 1

    staging: Path | None = None
    eff_settings = settings
    if args.output_dir:
        eff_settings = dataclasses.replace(settings, output_dir=str(args.output_dir))
    elif args.mock:
        base_parent = Path(settings.output_dir).resolve()
        base_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".verify-", dir=str(base_parent)))
        eff_settings = dataclasses.replace(settings, output_dir=str(staging))

    try:
        harness = build_harness(
            eff_settings,
            option="fabric-native",
            mock=bool(args.mock),
            publish=not args.mock,
            profile="tuned" if args.mock else "baseline",
            golden_override=g_path,
            log=lambda *_: None,
        )
        outcome = harness.run()
        sink = JsonlSink(outcome.folder)
        required_tables = ("EvalRun", "EvalQuestion", "EvalAsk", "EvalScore", "EvalResult", "EvalEvent")
        empty_tables = [t for t in required_tables if not sink.read(t)]
        errors = int(outcome.metrics.get("error") or 0)
        pass_rate = float(outcome.metrics.get("PassRate") or 0.0)
        crit_failed = int(outcome.stats.get("critical_failures") or 0)

        print(
            "Verify %s: asks=%d pass_rate=%.1f%% errors=%d empty_tables=%s"
            % (outcome.run_id, outcome.metrics["asks"], 100 * pass_rate, errors, empty_tables or "none")
        )
        if errors > 0 or empty_tables:
            return 1
        if args.strict and (crit_failed > 0 or pass_rate < 0.80):
            return 1
        return 0
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def cmd_golden(settings: Settings, args: argparse.Namespace) -> int:
    import csv as _csv

    import yaml as _yaml

    action = args.golden_action
    if action in ("validate", "lint"):
        ns = argparse.Namespace(paths=args.paths)
        return cmd_golden_lint(settings, ns)
    if action == "convert":
        src_p = _resolve_local_path(args.src)
        questions = load_golden(src_p)
        doc: dict[str, Any] = {
            "version": 2,
            "name": src_p.stem,
            "questions": [
                {
                    "id": q.id,
                    "question": q.question,
                    "category": q.category,
                    "case_type": q.case_type or "scalar",
                    "expected_artifact": q.expected_artifact,
                    "artifact_aliases": list(q.artifact_aliases),
                    "expected_model": q.expected_model,
                    "decoys": list(q.decoys),
                    "expected_value": q.expected_value,
                    "unit": q.unit,
                    "rel_tol": q.rel_tol,
                    "abs_tol": q.abs_tol,
                    "display_tol": q.display_tol,
                    "expected_answer": q.expected_answer,
                    "reference_dax": q.reference_dax,
                    "criticality": q.criticality,
                }
                for q in questions
            ],
        }
        dst_p = Path(args.out)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        dst_p.write_text(_yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print("Converted %d cases from %s -> %s" % (len(questions), src_p, dst_p))
        return 0
    if action == "scaffold":
        m_path = _resolve_local_path(args.measures)
        if not m_path.exists():
            raise SystemExit("Measures file not found: %s" % m_path)
        raw_items: list[dict[str, Any]] = []
        if m_path.suffix.lower() == ".csv":
            with m_path.open("r", encoding="utf-8-sig", newline="") as fh:
                raw_items = [dict(r) for r in _csv.DictReader(fh)]
        elif m_path.suffix.lower() == ".json":
            loaded = json.loads(m_path.read_text(encoding="utf-8-sig"))
            raw_items = list(loaded.get("measures", loaded) if isinstance(loaded, dict) else loaded)
        else:
            loaded_y = _yaml.safe_load(m_path.read_text(encoding="utf-8-sig"))
            raw_items = list(loaded_y.get("measures", loaded_y) if isinstance(loaded_y, dict) else (loaded_y or []))
        cases: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_items, start=1):
            m_name = str(item.get("name") or item.get("measure") or ("Measure %d" % idx)).strip()
            model = str(item.get("model") or item.get("semantic_model") or "Semantic Model").strip()
            artifact = str(item.get("artifact") or model).strip()
            unit = str(item.get("unit") or "number").strip()
            cases.append(
                {
                    "id": "M%02d" % idx,
                    "question": "What is %s according to %s?" % (m_name, artifact),
                    "category": "scaffold",
                    "case_type": "scalar",
                    "expected_artifact": artifact,
                    "expected_model": model,
                    "expected_value": 0.0,
                    "unit": unit,
                    "rel_tol": 0.005,
                    "reference_dax": 'EVALUATE ROW("Value", [%s])' % m_name,
                    "criticality": "standard",
                }
            )
        scaffold_doc = {"version": 2, "name": "%s-starter" % m_path.stem, "questions": cases}
        dst_p = Path(args.out)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        dst_p.write_text(_yaml.safe_dump(scaffold_doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print("Scaffolded %d starter cases to %s" % (len(cases), dst_p))
        return 0
    if action == "export":
        exp_ns = argparse.Namespace(format=args.format, run_dir=None, golden=args.golden, out=args.out)
        return cmd_export(settings, exp_ns)
    raise SystemExit("Unknown golden action: %s" % action)


def cmd_gate(settings: Settings, args: argparse.Namespace) -> int:
    from xml.sax.saxutils import escape as _xml_escape

    from .stats import summarize_run_stats

    folder = Path(args.run_folder)
    if not folder.exists():
        print("ERR run folder not found: %s" % folder)
        return 4
    sink = JsonlSink(folder)
    all_rows = sink.read("EvalResult")
    if not all_rows:
        print("ERR no EvalResult rows in %s" % folder)
        return 4
    rows, k_val = _load_latest_results_for_compare(folder, args.backend)
    stats = summarize_run_stats(rows, k=k_val)
    n_err = int(stats["error_count"])
    n_inc = int(stats["inconclusive_count"])
    n_pass = int(stats["passed_asks"])
    n_crit = int(stats["critical_failures"])
    pass_rate = float(stats["pass_rate"])
    lo, hi = float(stats["wilson_low"]), float(stats["wilson_high"])

    if n_err > 0 or (n_pass == 0 and n_inc == len(rows)):
        exit_code = 3
        gate_verdict = "INCONCLUSIVE_OR_ERROR"
    elif n_crit > 0 or pass_rate < args.min_pass_rate:
        exit_code = 2
        gate_verdict = "FAIL"
    else:
        exit_code = 0
        gate_verdict = "PASS"

    md = (
        "## Release Gate: `%s` (%s)\n\n"
        "- **Pass rate**: %.1f%% (min %.1f%%, 95%% Wilson CI [%.1f%%, %.1f%%])\n"
        "- **Critical failures**: %d\n"
        "- **Errors / Inconclusive**: %d / %d\n"
        % (
            folder.name,
            gate_verdict,
            100 * pass_rate,
            100 * args.min_pass_rate,
            100 * lo,
            100 * hi,
            n_crit,
            n_err,
            n_inc,
        )
    )
    print(md, end="")

    if args.summary_md:
        Path(args.summary_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_md).write_text(md, encoding="utf-8")

    if args.junit:
        cases_xml: list[str] = []
        failures_cnt = 0
        for r in rows:
            qid = _xml_escape(str(r.get("QuestionId") or ""))
            verdict = str(r.get("Verdict") or "")
            reasons = _xml_escape(str(r.get("Reasons") or r.get("Error") or verdict))
            if verdict == "PASS":
                cases_xml.append('  <testcase classname="cfeval" name="%s"/>' % qid)
            else:
                failures_cnt += 1
                cases_xml.append(
                    '  <testcase classname="cfeval" name="%s"><failure message="%s">%s</failure></testcase>'
                    % (qid, _xml_escape(verdict), reasons)
                )
        xml_doc = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<testsuite name="cfeval-gate" tests="%d" failures="%d" errors="%d">\n%s\n</testsuite>\n'
            % (len(rows), failures_cnt, n_err, "\n".join(cases_xml))
        )
        Path(args.junit).parent.mkdir(parents=True, exist_ok=True)
        Path(args.junit).write_text(xml_doc, encoding="utf-8")

    return exit_code


def cmd_judge(settings: Settings, args: argparse.Namespace) -> int:
    return cmd_calibrate_judge(settings, args)


def cmd_plan(settings: Settings, args: argparse.Namespace) -> int:
    from .scorers import load_gate_policy

    golden_raw = args.golden or settings.golden_set
    g_local = _resolve_local_path(golden_raw)
    g_path = g_local if g_local.exists() else resolve_golden_path(golden_raw, log=lambda *_: None)
    all_q = load_golden(g_path)
    shard_idx, shard_total = _parse_shard(args.shard)
    selected = [q for idx, q in enumerate(all_q) if idx % shard_total == shard_idx]
    repeats = args.repeats or settings.repeats
    total_asks = len(selected) * repeats
    target = args.target or settings.target or "copilot-chat"
    trace_targets = ("copilot-chat", "m365-copilot-chat-graph", "mcp-agent", "fabric-iq-mcp-reference")
    trace_on = (not args.no_trace) and (target in trace_targets)
    policy = load_gate_policy(
        args.gate_profile or settings.gate_profile or "auto",
        trace_enabled=trace_on,
        surface=("tool_call" if target in ("mcp-agent", "fabric-iq-mcp-reference") else "copilot-chat"),
        judge_gates_verdict=settings.judge_gates_verdict,
    )
    checks = list(policy.get("gates") or policy.get("checks") or [])
    est_seconds = total_asks * (12.0 + float(settings.pause_seconds))
    print("Execution plan (%s):" % g_path.name)
    print(
        "  target=%s  cases=%d (shard %d/%d)  repeats=%d  total_asks=%d"
        % (target, len(selected), shard_idx, shard_total, repeats, total_asks)
    )
    print("  active_gates=%s  estimated_duration=%.0fs" % (",".join(checks), est_seconds))
    return 0


def cmd_trace(settings: Settings, args: argparse.Namespace) -> int:
    if args.mock:
        from .mock import MockMonitoringSource, MockWorld

        sim_clock = SimClock(utc_now())
        world = MockWorld(sim_clock, [], profile="tuned", seed=7, test_user=DEMO_USER)
        mon = MockMonitoringSource(world)
        latest = mon.latest_timestamp()
        print("ok  workspace monitoring probe (simulated): latest_timestamp=%s" % iso(latest))
        return 0
    if not settings.trace_enabled:
        print("ERR MONITORING_QUERY_URI and MONITORING_DATABASE are not configured.")
        return 4
    mon_live, _wm = _monitoring(settings, [], print)
    latest_live = mon_live.latest_timestamp()
    print("ok  workspace monitoring probe: latest_timestamp=%s" % (iso(latest_live) if latest_live else "none"))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cfeval", description="Copilot Chat x Fabric IQ evaluation harness")
    p.add_argument("--env", default=".env", help="settings file (default .env)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    doc = sub.add_parser("doctor", help="check settings and packages")
    doc.add_argument("--verify-tokens", action="store_true", help="inspect cached delegated access token claims")
    doc.add_argument("--strict", action="store_true", help="validate URLs, UUIDs, bounds, and dependency compatibility")

    sub.add_parser("login", help="explicit test-user sign-in with a persistent labelled browser context")

    for kql_name in ("kql", "print-kql"):
        k = sub.add_parser(kql_name, help="print or write the Eventhouse setup script")
        k.add_argument("--out")
        k.add_argument("--database")
        k.add_argument("--onelake-latency", type=int, default=5)

    s = sub.add_parser("setup-eventhouse", help="create the telemetry tables, mappings, policies and functions")
    s.add_argument("--onelake-latency", type=int, default=5)

    r = sub.add_parser("run", help="ask the golden set and score it (Local scoring or Foundry Evaluations scoring)")
    r.add_argument(
        "--option",
        choices=sorted(OPTIONS),
        default="fabric-native",
        help="scoring backend: fabric-native (Local scoring), foundry (Foundry Evaluations [experimental]), or both",
    )
    r.add_argument("--mock", action="store_true", help="simulated tenant: no sign-in, no network")
    r.add_argument(
        "--profile", choices=list(PROFILES_CLI), default="baseline", help="simulated behaviour (with --mock)"
    )
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--repeats", type=int)
    r.add_argument("--golden", help="golden set path (.yaml, .json, or .csv)")
    r.add_argument("--questions", help="comma-separated question ids to run (default: all)")
    r.add_argument("--explain", choices=["followup", "inline", "off"])
    r.add_argument("--no-trace", action="store_true", help="skip DAX capture")
    r.add_argument("--no-publish", action="store_true", help="local files only, no Eventhouse")
    r.add_argument("--target", help="evaluation target (default: copilot-chat)")
    r.add_argument("--transcript", help="transcript file path when using transcript-import / import")
    r.add_argument(
        "--from-m365-copilot-eval",
        help="score saved results JSON/JSONL from Microsoft 365 Copilot Evaluations CLI",
    )
    r.add_argument("--gate-profile", choices=list(GATE_PROFILES_CLI), help="gate policy profile")
    r.add_argument("--gates", help="comma-separated gate check override (for example: value,artifact)")
    r.add_argument("--persona", help="persona context override")
    r.add_argument("--shard", help="deterministic question shard 'i/N' (for example: 0/2)")
    r.add_argument("--max-questions", type=int, help="maximum questions to ask in this run")
    r.add_argument("--max-judge-calls", type=int, help="maximum judge model calls allowed")
    r.add_argument("--max-wall-seconds", type=float, help="wall-clock budget in seconds for question collection")
    r.add_argument("--resume", action="store_true", help="reuse completed asks in an existing run folder")
    r.add_argument("--run-id", help="explicit run folder identifier (useful with --resume)")
    r.add_argument("--strict", action="store_true", help="exit non-zero on errors, critical failures, or low pass rate")
    r.add_argument("--min-pass-rate", type=float, default=0.80, help="minimum pass rate enforced by --strict")
    r.add_argument("--html", help="write self-contained HTML report to path")
    r.add_argument("--otel-out", help="export OpenTelemetry spans JSONL/JSON to path")
    r.add_argument("--expand-paraphrases", action="store_true", help="expand question paraphrases into separate asks")
    r.add_argument("--name")
    r.add_argument("--notes")

    rs = sub.add_parser("rescore", help="re-capture DAX and re-score an existing run folder")
    rs.add_argument("run_folder")
    rs.add_argument("--option", choices=sorted(OPTIONS), default="fabric-native")
    rs.add_argument("--no-publish", action="store_true")
    rs.add_argument("--mock", action="store_true", help="rescore offline using simulated judge/evaluators")
    rs.add_argument("--no-trace", action="store_true", help="rescore without re-capturing DAX")

    pb = sub.add_parser("publish", help="(re)publish a run folder to the Eventhouse")
    pb.add_argument("run_folder")
    pb.add_argument(
        "--tables",
        help="comma-separated tables to send (default: all); avoids duplicating rows that were already ingested",
    )

    g = sub.add_parser("golden-refresh", help="recompute expected values from reference DAX")
    g.add_argument("--write", action="store_true")

    sc = sub.add_parser("shortcuts", help="shortcut the app tables from the KQL database into a lakehouse")
    sc.add_argument("--lakehouse-workspace", required=True)
    sc.add_argument("--lakehouse", required=True, help="lakehouse item id")
    sc.add_argument("--kql-workspace", required=True)
    sc.add_argument("--kql-database", required=True, help="KQL database item id")
    sc.add_argument(
        "--path", default="Tables", help="destination: Tables, or Tables/dbo for a schema-enabled lakehouse"
    )

    d = sub.add_parser("demo-data", help="simulated runs for demos and the app's sample mode")
    d.add_argument("--runs", type=int, default=8)
    d.add_argument("--days", type=int, default=7)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--as-of", default=DEFAULT_DEMO_AS_OF, help="UTC ISO timestamp anchor for deterministic runs")
    d.add_argument("--golden", help="golden set path for simulated runs")
    d.add_argument("--app-json", help="write the app's sample data file")
    d.add_argument("--publish", action="store_true", help="also ingest the simulated runs into the Eventhouse")

    gl = sub.add_parser("golden-lint", help="validate golden YAML/JSON/CSV suites")
    gl.add_argument("paths", nargs="*", help="golden set files to validate")

    gp = sub.add_parser("golden", help="validate, lint, convert, scaffold, or export golden test sets")
    gp_sub = gp.add_subparsers(dest="golden_action", required=True)
    gp_val = gp_sub.add_parser("validate", help="validate golden files against v2 schema")
    gp_val.add_argument("paths", nargs="*", help="golden set files to validate")
    gp_lnt = gp_sub.add_parser("lint", help="lint golden files for quality warnings")
    gp_lnt.add_argument("paths", nargs="*", help="golden set files to lint")
    gp_cnv = gp_sub.add_parser("convert", help="convert CSV/JSON golden file to v2 YAML")
    gp_cnv.add_argument("src", help="input golden file")
    gp_cnv.add_argument("--out", required=True, help="output YAML file")
    gp_scf = gp_sub.add_parser("scaffold", help="scaffold starter golden YAML from exported measures")
    gp_scf.add_argument("--measures", required=True, help="CSV/JSON/YAML list of measures")
    gp_scf.add_argument("--out", required=True, help="output starter YAML path")
    gp_exp = gp_sub.add_parser("export", help="export golden set to external evaluation formats")
    gp_exp.add_argument("--format", choices=["m365-copilot-eval", "promptfoo"], required=True)
    gp_exp.add_argument("--golden", help="source golden file path")
    gp_exp.add_argument("--out", required=True, help="output file path")

    gt = sub.add_parser("gate", help="apply release gate thresholds and emit JUnit XML / Markdown summary")
    gt.add_argument("run_folder", help="completed run directory")
    gt.add_argument("--backend", choices=["fabric-native", "foundry"], default="fabric-native")
    gt.add_argument("--min-pass-rate", type=float, default=0.80)
    gt.add_argument("--junit", help="write JUnit XML report to path")
    gt.add_argument("--summary-md", help="write Markdown job summary to path")

    cmp_p = sub.add_parser("compare", help="statistically compare baseline and candidate run folders")
    cmp_p.add_argument("--baseline", required=True, help="baseline run directory")
    cmp_p.add_argument("--candidate", required=True, help="candidate run directory")
    cmp_p.add_argument("--backend", choices=["fabric-native", "foundry"], default="fabric-native")
    cmp_p.add_argument("--max-regressions", type=int, default=0)
    cmp_p.add_argument("--alpha", type=float, default=0.05)
    cmp_p.add_argument("--json-out", help="write comparison JSON summary")
    cmp_p.add_argument("--md-out", help="write Markdown diff summary")

    cal = sub.add_parser("calibrate-judge", help="evaluate judge agreement against human-labeled answers")
    cal.add_argument("--dataset", default="data/judge_calibration/answers.jsonl")
    cal.add_argument("--mock", action="store_true", help="evaluate deterministic offline MockJudge")
    cal.add_argument("--min-kappa", type=float, default=0.70)
    cal.add_argument("--json-out", help="write calibration metrics JSON")

    jg = sub.add_parser("judge", help="judge calibration commands")
    jg_sub = jg.add_subparsers(dest="judge_action", required=True)
    jg_cal = jg_sub.add_parser("calibrate", help="evaluate judge agreement against labelled pairs")
    jg_cal.add_argument("--dataset", default="data/judge_calibration/answers.jsonl")
    jg_cal.add_argument("--mock", action="store_true", help="evaluate deterministic offline MockJudge")
    jg_cal.add_argument("--min-kappa", type=float, default=0.70)
    jg_cal.add_argument("--json-out", help="write calibration metrics JSON")

    pln = sub.add_parser("plan", help="preview planned attempts, active gates, and estimated duration")
    pln.add_argument("--golden", help="golden set path")
    pln.add_argument("--repeats", type=int, help="repeats override")
    pln.add_argument("--gate-profile", choices=list(GATE_PROFILES_CLI), help="gate policy profile")
    pln.add_argument("--target", help="evaluation target")
    pln.add_argument("--no-trace", action="store_true")
    pln.add_argument("--persona", help="persona filter")
    pln.add_argument("--shard", help="question shard i/N")

    trp = sub.add_parser("trace", help="workspace monitoring diagnostics")
    trp_sub = trp.add_subparsers(dest="trace_action", required=True)
    trp_prb = trp_sub.add_parser("probe", help="check workspace monitoring connectivity and latest event lag")
    trp_prb.add_argument("--mock", action="store_true", help="probe simulated monitoring source offline")

    rep = sub.add_parser("report", help="render a self-contained HTML5 report for a run directory")
    rep.add_argument("run_folder", nargs="?", help="completed run directory")
    rep.add_argument("--run-dir", help="completed run directory (alias for positional run_folder)")
    rep.add_argument("--baseline", help="optional baseline run directory for comparison")
    rep.add_argument("--compare", help="optional baseline run directory (alias for --baseline)")
    rep.add_argument("--out", help="output HTML file path (default: <run-dir>/report.html)")

    exp = sub.add_parser("export", help="export runs or golden sets to OTel, Promptfoo, Foundry, or M365 Eval formats")
    exp.add_argument("--format", choices=["otel", "promptfoo", "foundry", "m365-copilot-eval"], required=True)
    exp.add_argument("--run-dir", help="completed run directory (required for otel and foundry)")
    exp.add_argument("--golden", help="golden set path (used by promptfoo and m365-copilot-eval)")
    exp.add_argument("--out", required=True, help="output file path")

    sub.add_parser("targets", help="list registered evaluation targets")

    st = sub.add_parser("setup", help="consolidated Eventhouse and Lakehouse shortcut setup")
    st.add_argument("--skip-eventhouse", action="store_true")
    st.add_argument("--skip-shortcuts", action="store_true")
    st.add_argument("--onelake-latency", type=int, default=5)
    st.add_argument("--lakehouse-workspace", default="")
    st.add_argument("--lakehouse", default="")
    st.add_argument("--kql-workspace", default="")
    st.add_argument("--kql-database", default="")
    st.add_argument("--path", default="")

    vf = sub.add_parser("verify", help="end-to-end verification of golden schema, harness, and telemetry tables")
    vf.add_argument("--mock", action="store_true", help="run verification completely offline")
    vf.add_argument("--golden", help="golden set path to verify")
    vf.add_argument("--strict", action="store_true", help="enforce pass-rate and zero critical-failure thresholds")
    vf.add_argument("--output-dir", help="optional directory to retain verification run artifacts")

    return p


COMMANDS: dict[str, Callable[[Settings, argparse.Namespace], int]] = {
    "doctor": cmd_doctor,
    "login": cmd_login,
    "kql": cmd_kql,
    "print-kql": cmd_kql,
    "setup-eventhouse": cmd_setup_eventhouse,
    "run": cmd_run,
    "rescore": cmd_rescore,
    "publish": cmd_publish,
    "golden-refresh": cmd_golden_refresh,
    "shortcuts": cmd_shortcuts,
    "demo-data": cmd_demo_data,
    "golden-lint": cmd_golden_lint,
    "golden": cmd_golden,
    "gate": cmd_gate,
    "compare": cmd_compare,
    "calibrate-judge": cmd_calibrate_judge,
    "judge": cmd_judge,
    "plan": cmd_plan,
    "trace": cmd_trace,
    "report": cmd_report,
    "export": cmd_export,
    "targets": cmd_targets,
    "setup": cmd_setup,
    "verify": cmd_verify,
}


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    settings = Settings.load(env_file=args.env)
    return COMMANDS[args.command](settings, args)
