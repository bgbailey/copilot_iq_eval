"""Simulated tenant for offline runs, tests and demo data.

A seeded, deterministic stand-in for Copilot Chat, Fabric IQ's DAX, workspace
monitoring (with ingestion delay), the judge model and Foundry Evaluations.
Nothing here calls a network. Behaviour per question comes from a 'profile'
so a series of runs tells a story (baseline -> improving -> tuned).

Simulated data is labelled Surface = "simulated" wherever it is published.
"""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .chat import AskResult, ChatTurn, parse_json_block
from .foundry import BUILTIN_EVALUATORS, CODE_EVALUATORS, code_bundle, foundry_checks, parse_output_items
from .judge import MockJudge as _CoreMockJudge
from .scorers import PASS, normalize_name, score_value, show, split_list
from .trace import WATERMARK_TAG, FabricQuery, watermark_dax

SCENARIOS = ("correct", "rounded", "no_citation", "decoy", "decoy_doc", "wrong_model", "document", "clarify", "error")

_BASELINE_PLAN: dict[str, str | list[str]] = {
    "Q01": "correct",
    "Q02": "decoy",
    "Q03": "wrong_model",
    "Q04": "rounded",
    "Q05": "correct",
    "Q06": "document",
    "Q07": "clarify",
    "Q08": "decoy_doc",
}

# Per-question behaviour for the bundled Contoso golden set. Unknown questions draw from PROFILE_MIXES.
PROFILES: dict[str, dict[str, str | list[str]]] = {
    "baseline": dict(_BASELINE_PLAN),
    "untuned": dict(_BASELINE_PLAN),
    "improving": {
        "Q01": "correct",
        "Q02": "correct",
        "Q03": "wrong_model",
        "Q04": "rounded",
        "Q05": "correct",
        "Q06": "no_citation",
        "Q07": "correct",
        "Q08": "decoy",
    },
    "tuned": {
        "Q01": "correct",
        "Q02": "correct",
        "Q03": "correct",
        "Q04": "rounded",
        "Q05": "correct",
        "Q06": "correct",
        "Q07": "correct",
        "Q08": ["correct", "correct", "rounded"],
    },
    "ambiguous": {
        "Q01": "correct",
        "Q02": "clarify",
        "Q03": "correct",
        "Q04": "rounded",
        "Q05": "correct",
        "Q06": "correct",
        "Q07": "clarify",
        "Q08": "correct",
    },
}
PROFILE_ORDER = ("baseline", "improving", "tuned")
DEFAULT_MIX = ["correct"] * 7 + ["rounded", "no_citation", "decoy", "clarify"]
PROFILE_MIXES: dict[str, list[str]] = {
    "baseline": ["correct"] * 4 + ["rounded", "no_citation", "decoy", "wrong_model", "clarify"],
    "untuned": ["correct"] * 4 + ["rounded", "no_citation", "decoy", "wrong_model", "clarify"],
    "improving": ["correct"] * 6 + ["rounded", "no_citation", "decoy"],
    "tuned": ["correct"] * 9 + ["rounded"],
    "ambiguous": ["correct"] * 5 + ["rounded", "clarify", "clarify"],
}

MEASURE_WORDS = {
    "currency": "revenue",
    "percent": "rate",
    "bps": "basis-point change",
    "count": "total",
    "units": "unit volume",
    "orders": "order count",
    "customers": "customer count",
    "days": "duration in days",
    "hours": "resolution time",
    "headcount": "headcount",
    "ratio": "ratio",
    "number": "value",
}

_CURRENCY_SYMBOLS = {"": "$", "USD": "$", "EUR": "€", "GBP": "£"}


def _uid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "cfeval-demo/" + "/".join(parts)))


WORKSPACE_ID = _uid("workspace")


def report_url(name: str) -> str:
    return "https://app.powerbi.com/groups/%s/reports/%s" % (WORKSPACE_ID, _uid("report", normalize_name(name)))


def document_url(name: str) -> str:
    clean = (name or "Reference Document").strip()
    low = clean.lower()
    slug = normalize_name(clean).replace(" ", "-") or "item"
    if any(w in low for w in ("recap", "sync", "meeting")):
        return "https://teams.microsoft.com/l/meetup-join/19%%3ameeting_%s%%40thread.v2/0?title=%s" % (
            _uid("teams", slug),
            quote(clean),
        )
    if any(w in low for w in ("thread", "escalation", "email", "mail")):
        return "https://outlook.office.com/mail/inbox/id/%s?subject=%s" % (
            _uid("mail", slug),
            quote(clean),
        )
    suffix = Path(clean).suffix.lower()
    if suffix == ".pptx" or "deck" in low or "slide" in low:
        filename = clean if suffix else (clean + ".pptx")
        return "https://contoso-my.sharepoint.com/personal/alex_wilber_contoso_com/Documents/%s" % quote(filename)
    filename = clean if suffix else (clean + ".docx")
    return "https://contoso.sharepoint.com/sites/finance/Shared%%20Documents/%s" % quote(filename)


def citation(name: str, url: str) -> dict[str, Any]:
    return {
        "attributionType": "citation",
        "providerDisplayName": name,
        "attributionSource": "model",
        "seeMoreWebUrl": url,
        "imageWebUrl": None,
        "imageFavIcon": None,
        "imageWidth": 0,
        "imageHeight": 0,
    }


def _scaled_str(value: float, scale: float, suffix: str, *, rounded: bool, prefix: str = "") -> str:
    scaled = value / scale
    if rounded:
        approx_1 = round(scaled, 1) * scale
        if value != 0 and abs(approx_1 - value) <= abs(value) * 0.009:
            return "%s%.1f%s" % (prefix, scaled, suffix)
    return "%s%.2f%s" % (prefix, scaled, suffix)


def fmt_value(
    value: float | int | None,
    unit: str = "number",
    style: str | bool = "exact",
    *,
    currency: str = "",
) -> str:
    if value is None:
        return "n/a"
    v = float(value)
    rounded = (style is True) or (str(style).lower() == "rounded")
    u = (unit or "number").strip().lower()
    sym = _CURRENCY_SYMBOLS.get((currency or "").strip().upper(), ((currency or "").strip().upper() + " ") or "$")

    if u == "currency":
        if abs(v) >= 1e9:
            return _scaled_str(v, 1e9, "B", rounded=rounded, prefix=sym)
        if abs(v) >= 1e6:
            return _scaled_str(v, 1e6, "M", rounded=rounded, prefix=sym)
        if rounded and abs(v) >= 1e4:
            return _scaled_str(v, 1e3, "K", rounded=rounded, prefix=sym)
        if float(v).is_integer():
            return f"{sym}{v:,.0f}"
        return f"{sym}{v:,.2f}"

    if u == "percent":
        pct = v * 100.0 if 0.0 < abs(v) < 1.0 else v
        if rounded:
            approx_1 = round(pct, 1)
            if pct == 0 or abs(approx_1 - pct) <= abs(pct) * 0.009:
                return "%.1f%%" % pct
            return "%.2f%%" % pct
        return "%s%%" % show(round(pct, 4))

    if u == "bps":
        return "%s bps" % show(round(v, 1) if rounded else round(v, 4))

    if u in ("days", "hours", "units", "orders", "customers"):
        if rounded and abs(v) >= 1e4 and u in ("units", "orders", "customers"):
            return "%s %s" % (_scaled_str(v, 1e3, "K", rounded=True), u)
        num_txt = f"{v:,.0f}" if float(v).is_integer() else show(round(v, 2))
        return "%s %s" % (num_txt, u)

    if u in ("count", "headcount"):
        if rounded and abs(v) >= 1e6:
            return _scaled_str(v, 1e6, "M", rounded=True)
        if rounded and abs(v) >= 1e3:
            return _scaled_str(v, 1e3, "K", rounded=True)
        return f"{v:,.0f}" if float(v).is_integer() else show(round(v, 2))

    if u == "ratio":
        return ("%.2f" % v) if rounded else show(round(v, 4))

    if rounded and abs(v) >= 1e6:
        return _scaled_str(v, 1e6, "M", rounded=True)
    if rounded and not float(v).is_integer() and abs(round(v, 1) - v) <= abs(v) * 0.009:
        return "%.1f" % v
    return show(round(v, 4))


def _is_m365_question(q: Any) -> bool:
    exp_model = (getattr(q, "expected_model", "") or "").strip()
    if exp_model:
        return False
    q_gates = [str(g).strip().lower() for g in (getattr(q, "gates", None) or ())]
    if "model" in q_gates:
        return False
    if q_gates:
        return True
    art = (getattr(q, "expected_artifact", "") or "").strip()
    return bool(art and _looks_like_document(art))


def _item_label(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("value") or item.get("id") or "")
    return str(item)


def _format_cell_or_field(name: str, val: Any, *, perturb: float = 1.0) -> str:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        num = float(val) * perturb
        low = name.lower()
        if any(w in low for w in ("margin", "rate", "pct", "%", "share", "churn")):
            return "%s%%" % show(round(num, 2))
        if perturb == 1.0 and float(num).is_integer():
            return str(int(num))
        return show(round(num, 2))
    return str(val)


class MockWorld:
    """Copilot Chat + Fabric IQ + workspace monitoring, on a simulated clock."""

    def __init__(
        self,
        clock: Any,
        questions: Sequence[Any],
        profile: str = "baseline",
        seed: int = 7,
        test_user: str = "eval.tester@contoso.com",
        harness_user: str = "eval.admin@contoso.com",
        ingest_delay_s: tuple[float, float] = (45.0, 150.0),
        error_rate: float = 0.0,
    ) -> None:
        self.clock = clock
        self.questions = {q.question.strip(): q for q in questions}
        self.profile = profile
        self.rng = random.Random("%s|%s" % (seed, profile))
        self.test_user = test_user
        self.harness_user = harness_user
        self.ingest_delay_s = ingest_delay_s
        self.error_rate = error_rate
        self.logs: list[dict[str, Any]] = []
        self.asked: dict[str, int] = {}

    # ---- scenario choice --------------------------------------------------------------------------
    def scenario_for(self, q: Any) -> str:
        n = self.asked.get(q.id, 0)
        self.asked[q.id] = n + 1
        if self.error_rate and self.rng.random() < self.error_rate:
            return "error"
        plan = PROFILES.get(self.profile, {}).get(q.id)
        if plan is None:
            mix = PROFILE_MIXES.get(self.profile, DEFAULT_MIX)
            return self.rng.choice(mix)
        if isinstance(plan, list):
            return self.rng.choice(plan)
        return plan

    # ---- workspace monitoring -----------------------------------------------------------------------
    def log_query(
        self,
        when: datetime,
        model: str,
        dax: str,
        duration_ms: float,
        user: str | None = None,
        report_name: str = "",
    ) -> None:
        delay = self.rng.uniform(*self.ingest_delay_s)
        eff_user = user or self.test_user
        item_id = _uid("model", normalize_name(model))
        report_id = _uid("report", normalize_name(report_name or model))
        corr_id = str(uuid.UUID(int=self.rng.getrandbits(128)))
        op_id = str(uuid.UUID(int=self.rng.getrandbits(128)))
        dur = round(float(duration_ms), 1)
        cpu_ms = round(max(5.0, dur * self.rng.uniform(0.35, 0.78)), 1)
        app_ctx = json.dumps({"DatasetId": item_id, "ReportId": report_id}, sort_keys=True)
        self.logs.append(
            {
                "query": FabricQuery(
                    query_time=when,
                    workspace_id=WORKSPACE_ID,
                    item_id=item_id,
                    item_name=model,
                    application_name="PowerBI",
                    operation_name="QueryEnd",
                    duration_ms=dur,
                    dax=dax,
                    correlation_id=corr_id,
                    operation_id=op_id,
                    application_context=app_ctx,
                    cpu_time_ms=cpu_ms,
                    executing_user=eff_user,
                ),
                "user": eff_user,
                "visible_at": when + timedelta(seconds=delay),
            }
        )

    def visible(self) -> list[dict[str, Any]]:
        now = self.clock.now()
        return [row for row in self.logs if row["visible_at"] <= now]

    # ---- Copilot Chat ------------------------------------------------------------------------------
    def ask(self, question: str, explain_mode: str = "followup") -> AskResult:
        q = self.questions.get(question.strip())
        started = self.clock.now()
        result = AskResult(question=question, started=started)
        if q is None:
            self.clock.advance(self.rng.uniform(6, 10))
            text = "I couldn't find data to answer that question."
            result.conversation_id = str(uuid.UUID(int=self.rng.getrandbits(128)))
            result.answer = ChatTurn(text, [], started, self.clock.now(), 0.0)
            result.ended = self.clock.now()
            return result
        scenario = self.scenario_for(q)
        if scenario == "error":
            self.clock.advance(self.rng.uniform(1.5, 4.0))
            result.error = "Copilot Chat API returned 429: Too many requests (retries exhausted)"
            result.http_status = 429
            result.ended = self.clock.now()
            return result
        spec = self.render(q, scenario)
        result.conversation_id = str(uuid.UUID(int=self.rng.getrandbits(128)))
        latency = self.rng.uniform(*spec["latency"])
        offset = self.rng.uniform(2.0, 5.0)
        for dax_entry in spec["dax"]:
            model_name, dax_txt = dax_entry[0], dax_entry[1]
            rep_name = dax_entry[2] if len(dax_entry) > 2 else model_name
            duration = self.rng.uniform(60, 1400)
            offset += duration / 1000.0 + self.rng.uniform(0.2, 1.5)
            self.log_query(
                started + timedelta(seconds=min(offset, latency - 0.5)),
                model_name,
                dax_txt,
                duration,
                report_name=rep_name,
            )
        self.clock.advance(latency)
        text = spec["answer"]
        if explain_mode == "inline":
            text += " " + spec["inline"]
        raw = {
            "id": result.conversation_id,
            "messages": [
                {
                    "@odata.type": "#microsoft.graph.copilotConversationResponseMessage",
                    "text": question,
                    "attributions": [],
                },
                {
                    "@odata.type": "#microsoft.graph.copilotConversationResponseMessage",
                    "text": text,
                    "attributions": spec["attributions"],
                },
            ],
        }
        result.answer = ChatTurn(text, spec["attributions"], started, self.clock.now(), round(latency * 1000, 1), raw)
        if explain_mode == "followup":
            why_start = self.clock.now()
            why_latency = self.rng.uniform(5.0, 11.0)
            for dax_entry in spec["why_dax"]:
                model_name, dax_txt = dax_entry[0], dax_entry[1]
                rep_name = dax_entry[2] if len(dax_entry) > 2 else model_name
                self.log_query(
                    why_start + timedelta(seconds=self.rng.uniform(1.5, 3.0)),
                    model_name,
                    dax_txt,
                    self.rng.uniform(40, 600),
                    report_name=rep_name,
                )
            self.clock.advance(why_latency)
            result.explain = ChatTurn(spec["why"], [], why_start, self.clock.now(), round(why_latency * 1000, 1))
            result.why_text = spec["why"]
            result.why_json = parse_json_block(spec["why"])
        result.ended = self.clock.now()
        return result

    def _render_body(self, q: Any, scenario: str, source_label: str) -> str:
        case_type = (getattr(q, "case_type", "") or "scalar").strip().lower()
        expect = dict(getattr(q, "expect", None) or {})
        unit = getattr(q, "unit", "") or "number"
        currency = getattr(q, "currency", "") or ""
        measure = MEASURE_WORDS.get(unit.lower(), "value")
        good = scenario in ("correct", "rounded", "no_citation")
        suffix = (
            (" according to the %s source." % source_label) if (source_label and scenario != "no_citation") else "."
        )

        if case_type in ("abstention", "negative", "refusal"):
            if good:
                return (
                    "I cannot answer that from the available Contoso semantic models or documents "
                    "because that data is not available in scope."
                )
            return "Based on internal estimates, the figure is $4.2M%s" % suffix

        if case_type == "ranked_list":
            raw_items = [_item_label(x) for x in (expect.get("items") or []) if _item_label(x)]
            if good:
                items = raw_items
            elif len(raw_items) >= 2:
                items = list(reversed(raw_items[:-1])) + ["Unverified Legacy Segment"]
            else:
                items = ["Unverified Legacy Segment"]
            lines = ["%d. %s" % (idx + 1, item) for idx, item in enumerate(items)]
            return "Ranked results%s\n%s" % (suffix, "\n".join(lines))

        if case_type == "set":
            raw_items = [_item_label(x) for x in (expect.get("items") or []) if _item_label(x)]
            if good:
                items = raw_items
            else:
                items = (raw_items[1:] if len(raw_items) > 1 else []) + ["Unverified Legacy Segment"]
            lines = ["- %s" % item for item in items]
            return "Matching items%s\n%s" % (suffix, "\n".join(lines))

        if case_type == "table":
            rows = list(expect.get("rows") or [])
            if not rows:
                return "Summary table%s" % suffix
            cols = list(rows[0].keys())
            perturb = 1.0 if good else 1.08
            header = "| " + " | ".join(str(c) for c in cols) + " |"
            sep = "| " + " | ".join("---" for _ in cols) + " |"
            body_rows = [
                "| " + " | ".join(_format_cell_or_field(str(c), r.get(c, ""), perturb=perturb) for c in cols) + " |"
                for r in rows
            ]
            return "Breakdown table%s\n\n%s\n%s\n%s" % (suffix, header, sep, "\n".join(body_rows))

        if case_type == "record":
            fields = dict(expect.get("fields") or {})
            perturb = 1.0 if good else 1.08
            lines = ["- %s: %s" % (k, _format_cell_or_field(str(k), v, perturb=perturb)) for k, v in fields.items()]
            return "Summary record%s\n%s" % (suffix, "\n".join(lines))

        if case_type == "direction":
            exp_dir = str(expect.get("direction") or getattr(q, "expected_value", "") or "up").strip().lower()
            opp_map = {"up": "down", "down": "up", "flat": "up"}
            chosen_dir = exp_dir if good else opp_map.get(exp_dir, "down")
            phrase_map = {
                "up": "The metric increased (upward trend) over the period",
                "down": "The metric decreased (downward trend) over the period",
                "flat": "The metric remained flat and unchanged over the period",
            }
            phrase = phrase_map.get(chosen_dir, phrase_map["up"])
            mag = expect.get("value")
            if mag is not None:
                d_unit = str(expect.get("unit") or unit)
                mag_val = float(mag) if good else float(mag) * 1.15
                mag_style = "rounded" if scenario == "rounded" else "exact"
                shown_mag = fmt_value(mag_val, d_unit, mag_style, currency=currency)
                return "%s by **%s**%s" % (phrase, shown_mag, suffix)
            return "%s%s" % (phrase, suffix)

        if case_type == "citation_only":
            ref = (getattr(q, "expected_answer", "") or "").strip()
            if good and ref:
                return "%s (Source: %s)" % (ref, source_label) if (source_label and scenario != "no_citation") else ref
            return "Summary notes confirm operational status%s" % suffix

        # Default: scalar
        value = getattr(q, "expected_value", None)
        if good:
            shown = fmt_value(value, unit, "rounded" if scenario == "rounded" else "exact", currency=currency)
        elif scenario in ("decoy", "decoy_doc"):
            mult = self.rng.choice((0.93, 0.96, 1.04))
            wrong = value * mult if value is not None else None
            shown = fmt_value(wrong, unit, "exact", currency=currency)
        elif scenario == "wrong_model":
            wrong = value * 1.075 if value is not None else None
            shown = fmt_value(wrong, unit, "exact", currency=currency)
        else:
            stale = value * 0.978 if value is not None else None
            shown = fmt_value(stale, unit, "exact", currency=currency)

        if scenario == "no_citation" or not source_label:
            return "For the requested period, the %s is **%s**." % (measure, shown)
        return "For the requested period, the %s is **%s**, based on the %s source." % (measure, shown, source_label)

    def render(self, q: Any, scenario: str) -> dict[str, Any]:
        is_m365 = _is_m365_question(q)
        case_type = (getattr(q, "case_type", "") or "scalar").strip().lower()
        is_abstention = case_type in ("abstention", "negative", "refusal")
        fallback_art = "" if is_m365 or is_abstention else getattr(q, "model", "")
        artifact = (getattr(q, "expected_artifact", "") or fallback_art).strip()
        raw_model = getattr(q, "expected_model", "") or getattr(q, "model", "")
        model = "" if (is_m365 or is_abstention) else str(raw_model).strip()
        dax = getattr(q, "reference_dax", "") or ('EVALUATE ROW("v", [%s])' % (getattr(q, "category", "") or "Value"))
        decoys = split_list(getattr(q, "decoys", None))
        unit = getattr(q, "unit", "") or "number"
        measure = MEASURE_WORDS.get(unit.lower(), "value")

        def _cite(src_name: str, *, force_doc: bool = False) -> list[dict[str, Any]]:
            if not src_name:
                return []
            if force_doc or is_m365 or _looks_like_document(src_name):
                return [citation(src_name, document_url(src_name))]
            return [citation(src_name, report_url(src_name))]

        spec: dict[str, Any] = {
            "latency": (8.0, 16.0),
            "dax": [(model, dax, artifact or model)] if model else [],
            "why_dax": [],
            "attributions": _cite(artifact),
        }
        why: dict[str, Any] = {
            "sources": [artifact] if artifact else [],
            "semantic_model": model,
            "filters": "as asked",
            "reasoning": "",
        }

        if scenario in ("correct", "rounded", "no_citation"):
            spec["answer"] = self._render_body(q, scenario, artifact)
            if model:
                why["reasoning"] = "Queried the %s semantic model behind the %s report." % (model, artifact or model)
            elif artifact:
                why["reasoning"] = "Grounded the response in %s from Microsoft 365." % artifact
            else:
                why["reasoning"] = "Verified that no in-scope semantic model or document contains the requested data."
            if scenario == "no_citation":
                spec["attributions"] = []
                why["sources"] = []
            if model and self.rng.random() < 0.35:
                alt_dax = "DEFINE VAR _t = %s\nEVALUATE _t" % dax.replace("EVALUATE ", "")
                spec["dax"].append((model, alt_dax, artifact or model))
        elif scenario in ("decoy", "decoy_doc"):
            docs = [d for d in decoys if _looks_like_document(d)]
            reports = [d for d in decoys if not _looks_like_document(d)]
            if is_m365:
                decoy = (docs or decoys or ["Draft Estimate Notes.docx"])[0]
                spec["attributions"] = _cite(decoy, force_doc=True)
                spec["dax"] = []
                spec["answer"] = self._render_body(q, scenario, decoy)
                why.update(sources=[decoy], semantic_model="", reasoning="Found the figure in %s." % decoy)
            else:
                pool = (docs or reports) if scenario == "decoy_doc" else (reports or docs)
                decoy = pool[0] if pool else "Sales Sandbox"
                if _looks_like_document(decoy):
                    spec["attributions"] = _cite(decoy, force_doc=True)
                    spec["dax"] = []
                    spec["answer"] = self._render_body(q, scenario, decoy)
                    why.update(
                        sources=[decoy],
                        semantic_model="",
                        reasoning="Found the figure in a document in SharePoint.",
                    )
                else:
                    spec["attributions"] = _cite(decoy)
                    spec["dax"] = [(decoy, dax, decoy)]
                    spec["answer"] = self._render_body(q, scenario, decoy)
                    why.update(
                        sources=[decoy],
                        semantic_model=decoy,
                        reasoning="The %s report had the most recent data." % decoy,
                    )
        elif scenario == "wrong_model":
            if is_m365:
                other_doc = decoys[0] if decoys else "Archived Working Draft.docx"
                spec["attributions"] = _cite(other_doc, force_doc=True)
                spec["dax"] = []
                spec["answer"] = self._render_body(q, scenario, other_doc)
                why.update(sources=[other_doc], semantic_model="", reasoning="Used notes from %s." % other_doc)
            else:
                other = "Sales Analytics" if normalize_name(model) != normalize_name("Sales Analytics") else "Finance"
                spec["attributions"] = _cite(other)
                spec["dax"] = [(other, dax.replace("Net Revenue", "Gross Revenue"), other)]
                spec["answer"] = self._render_body(q, scenario, other)
                why.update(
                    sources=[other],
                    semantic_model=other,
                    reasoning="Used the %s measure in %s." % (measure, other),
                )
        elif scenario == "document":
            doc = "%s monthly review" % (artifact or "Operations")
            spec["attributions"] = _cite(doc, force_doc=True)
            spec["dax"] = []
            spec["latency"] = (11.0, 20.0)
            spec["answer"] = self._render_body(q, scenario, doc)
            why.update(sources=[doc], semantic_model="", reasoning="Found the number in a recent review document.")
        elif scenario == "clarify":
            spec["attributions"] = []
            spec["dax"] = []
            spec["latency"] = (4.0, 8.0)
            spec["answer"] = "Do you mean the fiscal or the calendar year, and which business unit?"
            why.update(
                sources=[],
                semantic_model="",
                reasoning="The question was ambiguous, so I asked for clarification.",
            )
        else:
            raise ValueError("unknown scenario %s" % scenario)

        spec["why"] = "```json\n%s\n```" % _json(why)
        spec["inline"] = "Source: %s." % (", ".join(why["sources"]) or "none")
        spec["scenario"] = scenario
        return spec


def _looks_like_document(name: str) -> bool:
    low = (name or "").lower()
    if any(low.endswith(ext) for ext in (".docx", ".pptx", ".xlsx", ".pdf", ".msg", ".eml")):
        return True
    return any(w in low for w in ("draft", "review", "recap", "thread", "notes", "deck", "memo"))


def _json(value: Any) -> str:
    return json.dumps(value, indent=2)


class MockCopilotChat:
    """Drop-in for CopilotChatClient.ask()."""

    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def ask(self, question: str, explain_mode: str = "followup") -> AskResult:
        return self.world.ask(question, explain_mode)


class MockMonitoringSource:
    """Drop-in for WorkspaceMonitoringSource; rows appear after a simulated ingestion delay."""

    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def fetch(self, upn: str, start: datetime, end: datetime) -> list[FabricQuery]:
        rows = [
            r["query"]
            for r in self.world.visible()
            if r["user"].lower() == (upn or "").lower()
            and start <= r["query"].query_time <= end
            and WATERMARK_TAG not in r["query"].dax
        ]
        return sorted(rows, key=lambda q: q.query_time)

    def latest_timestamp(self) -> datetime | None:
        rows = self.world.visible()
        return max(r["query"].query_time for r in rows) if rows else None

    def watermark_seen(self, marker: str, since: datetime) -> bool:
        return any(marker in r["query"].dax and r["query"].query_time > since for r in self.world.visible())


class MockWatermark:
    def __init__(self, world: MockWorld, model: str = "Sales Analytics") -> None:
        self.world = world
        self.model = model

    def send(self, marker: str) -> None:
        self.world.log_query(
            self.world.clock.now(),
            self.model,
            watermark_dax(marker),
            12.0,
            user=self.world.harness_user,
        )


class MockJudge:
    """Deterministic stand-in for the Foundry-hosted judge model (v1 + v2 interfaces)."""

    model_name = "simulated-judge"

    def __init__(
        self,
        *,
        calibration_id: str = "mock-calibrated-v1",
        max_calls: int | None = None,
    ) -> None:
        self._delegate = _CoreMockJudge(calibration_id=calibration_id, max_calls=max_calls)

    @property
    def prompt_hash(self) -> str:
        return self._delegate.prompt_hash

    @property
    def calibration_id(self) -> str:
        return self._delegate.calibration_id

    @calibration_id.setter
    def calibration_id(self, value: str) -> None:
        self._delegate.calibration_id = value

    @property
    def calls(self) -> int:
        return self._delegate.calls

    @property
    def max_calls(self) -> int | None:
        return self._delegate.max_calls

    def score(self, question: str, expected_summary: str, answer: str) -> dict[str, Any]:
        return self._delegate.score_answer(question, expected_summary, answer)

    def score_answer(self, question: str, expected_summary: str, answer: str) -> dict[str, Any]:
        return self._delegate.score_answer(question, expected_summary, answer)

    def extract_value(self, question: str, answer: str) -> dict[str, Any] | None:
        return self._delegate.extract_value(question, answer)

    def judge_answer(self, q: Any, answer: str) -> dict[str, Any] | None:
        case_type = (getattr(q, "case_type", "") or "scalar").strip().lower()
        expect = getattr(q, "expect", None)
        exp_ans = getattr(q, "expected_answer", "")
        exp_val = getattr(q, "expected_value", None)
        if case_type == "scalar" and not (exp_ans or exp_val is not None or expect):
            return None
        r = score_value(
            answer or "",
            exp_val,
            getattr(q, "unit", "") or "number",
            getattr(q, "rel_tol", 0.005),
            getattr(q, "abs_tol", 0.0),
            display_tol=getattr(q, "display_tol", 0.01),
            case_type=case_type,
            expect=expect,
            expected_currency=getattr(q, "currency", "") or "",
        )
        if r.get("outcome") == "INCONCLUSIVE" and case_type == "scalar" and exp_val is None:
            return None
        ok = r["score"] == PASS
        reason = "matches the reference" if ok else "does not match the reference: " + str(r.get("reason") or "")
        return {
            "score": 1.0 if ok else 0.0,
            "reason": reason,
            "raw": {"correct": ok, "prompt_hash": self.prompt_hash, "calibration_id": self.calibration_id},
        }

    def judge_why(
        self,
        q: Any,
        answer: str,
        cited: Sequence[str],
        why: str,
        models: Sequence[str],
        dax: str,
    ) -> dict[str, Any] | None:
        if not why:
            return None
        text = why.lower()
        named = [c for c in cited if c and c.lower() in text]
        all_models_named = not models or any(m.lower() in text for m in models)
        raw = 5 if (named and all_models_named) else 4 if named else 2 if cited else 3
        return {
            "score": (raw - 1) / 4.0,
            "raw_score": raw,
            "reason": "explanation names %s" % (", ".join(named) if named else "none of the cited sources"),
            "raw": {"score": raw},
        }


def _load_grade(code_text: str) -> Any:
    namespace: dict[str, Any] = {"__name__": "foundry_code_evaluator"}
    exec(compile(code_text, "<foundry-code-evaluator>", "exec"), namespace)  # noqa: S102 - our own bundled code
    return namespace["grade"]


class LocalFoundryEmulator:
    """Runs Option 2 offline: code evaluators exec the exact bundles registered in Foundry;
    prompt and built-in evaluators are simulated. Output goes through the same parser as real runs."""

    name = "foundry"

    def __init__(self, include_trace: bool = True, include_prompt: bool = True, include_builtin: bool = True) -> None:
        self.include_trace = include_trace
        self.include_prompt = include_prompt
        self.include_builtin = include_builtin
        self.judge = MockJudge()

    def checks(self) -> list[str]:
        return list(foundry_checks(self.include_trace, self.include_prompt, self.include_builtin))

    def run(self, rows: Sequence[dict[str, Any]], name: str) -> dict[str, Any]:
        checks = self.checks()
        graders = {c: _load_grade(code_bundle(c)) for c in CODE_EVALUATORS if c in checks}
        items = []
        for row in rows:
            results: list[dict[str, Any]] = []
            value_ok: bool | None = None
            response_txt = str(row.get("response") or "")
            cited_txt = str(row.get("cited") or "")
            why_txt = str(row.get("why") or "")
            case_type = str(row.get("case_type") or "scalar").strip().lower()
            raw_expect = row.get("expect_json")
            expect_dict: dict[str, Any] | None = None
            if isinstance(raw_expect, str) and raw_expect.strip():
                try:
                    parsed_exp = json.loads(raw_expect)
                    if isinstance(parsed_exp, dict) and parsed_exp:
                        expect_dict = parsed_exp
                except ValueError:
                    expect_dict = None
            elif isinstance(row.get("expect"), dict) and row.get("expect"):
                expect_dict = dict(row["expect"])

            for check in checks:
                if check in graders:
                    if check == "value" and (case_type != "scalar" or expect_dict is not None):
                        exp_raw = row.get("expected_value")
                        exp_num = None if exp_raw in (None, "") else float(exp_raw)
                        vr = score_value(
                            response_txt,
                            exp_num,
                            str(row.get("unit") or "number"),
                            float(row.get("rel_tol") or 0.005),
                            float(row.get("abs_tol") or 0.0),
                            display_tol=float(row.get("display_tol") or 0.01),
                            case_type=case_type,
                            expect=expect_dict,
                            expected_currency=str(row.get("currency") or ""),
                        )
                        score = float(vr.get("score", 0.5))
                    elif check == "model" and str(row.get("trace_status") or "disabled").lower() == "disabled":
                        score = 0.5
                    else:
                        score = float(graders[check]({}, row))
                    if check == "value":
                        value_ok = score == 1.0
                    results.append(
                        {
                            "name": check,
                            "type": "azure_ai_evaluator",
                            "score": score,
                            "passed": score >= 1.0,
                            "sample": {},
                        }
                    )
                elif check == "judge_answer":
                    raw = 5 if value_ok else 1
                    results.append(
                        {
                            "name": check,
                            "score": raw,
                            "passed": raw >= 4,
                            "reason": "simulated grader: %s" % ("matches" if value_ok else "does not match"),
                        }
                    )
                elif check == "why":
                    first_cited = cited_txt.split("; ")[0].lower() if cited_txt else ""
                    named = bool(first_cited and first_cited in why_txt.lower())
                    raw = 5 if named else (3 if not cited_txt and why_txt else 2)
                    results.append(
                        {
                            "name": check,
                            "score": raw,
                            "passed": raw >= 4,
                            "reason": "simulated grader: explanation %s the cited source"
                            % ("names" if named else "doesn't name"),
                        }
                    )
                elif check in BUILTIN_EVALUATORS:
                    raw = (5 if value_ok else 2) if check == "similarity" else (4 if len(response_txt) > 30 else 3)
                    results.append({"name": check, "score": raw, "passed": raw >= 3, "reason": "simulated"})
            items.append({"datasource_item": row, "results": results})
        return {
            "eval_id": "simulated",
            "run_id": "simulated-%s" % _uid(name)[:8],
            "status": "completed",
            "report_url": "",
            "scores": parse_output_items(items, checks),
        }
