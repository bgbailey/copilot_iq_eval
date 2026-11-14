"""Self-contained, accessible HTML5 report renderer for cfeval run folders."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .sinks import JsonlSink
from .stats import compare_runs, summarize_run_stats

_CSS = """
:root {
  --bg: #f8fafc;
  --surface: #ffffff;
  --border: #cbd5e1;
  --text: #0f172a;
  --muted: #475569;
  --accent: #0f4c81;
  --pass-bg: #dcfce7;
  --pass-fg: #14532d;
  --fail-bg: #fee2e2;
  --fail-fg: #7f1d1d;
  --warn-bg: #fef9c3;
  --warn-fg: #713f12;
  --neutral-bg: #e2e8f0;
  --neutral-fg: #1e293b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1.5rem 3rem;
}
header {
  margin-bottom: 1.5rem;
}
h1 {
  margin: 0 0 0.25rem;
  font-size: 1.75rem;
}
h2 {
  margin: 2rem 0 0.75rem;
  font-size: 1.25rem;
}
.meta {
  color: var(--muted);
  font-size: 0.92rem;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
  margin: 1.25rem 0;
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.15rem;
}
.card-label {
  font-size: 0.82rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--muted);
}
.card-value {
  font-size: 1.65rem;
  font-weight: 700;
  margin: 0.25rem 0;
}
.card-sub {
  font-size: 0.85rem;
  color: var(--muted);
}
.banner {
  background: var(--surface);
  border-left: 4px solid var(--accent);
  border-top: 1px solid var(--border);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  border-radius: 6px;
  padding: 1rem 1.25rem;
  margin: 1.25rem 0;
}
.badge {
  display: inline-block;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
}
.badge-pass { background: var(--pass-bg); color: var(--pass-fg); }
.badge-fail { background: var(--fail-bg); color: var(--fail-fg); }
.badge-warn { background: var(--warn-bg); color: var(--warn-fg); }
.badge-neutral { background: var(--neutral-bg); color: var(--neutral-fg); }
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
th, td {
  text-align: left;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--border);
  font-size: 0.9rem;
}
th {
  background: #f1f5f9;
  font-weight: 600;
}
details.ask-row {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 0.65rem;
}
details.ask-row > summary {
  cursor: pointer;
  padding: 0.75rem 1rem;
  font-weight: 500;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}
details.ask-row > summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.ask-body {
  padding: 0.85rem 1rem 1rem;
  border-top: 1px solid var(--border);
  font-size: 0.9rem;
}
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.6rem 1rem;
  margin-bottom: 0.75rem;
}
pre {
  background: #f1f5f9;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem;
  overflow-x: auto;
  font-size: 0.82rem;
  margin: 0.4rem 0 0;
  white-space: pre-wrap;
  word-break: break-word;
}
""".strip()


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.0f} ms"
    except (TypeError, ValueError):
        return "n/a"


def _verdict_badge_class(verdict: str) -> str:
    v = verdict.upper()
    if v == "PASS":
        return "badge badge-pass"
    if v in ("FAIL", "ERROR"):
        return "badge badge-fail"
    if v in ("INCOMPLETE", "INCONCLUSIVE"):
        return "badge badge-warn"
    return "badge badge-neutral"


def _select_primary_results(
    results: Sequence[Mapping[str, Any]],
    run_row: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not results:
        return []
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    backend_order: list[str] = []
    for raw in results:
        row = dict(raw)
        ask_id = str(row.get("AskId") or row.get("QuestionId") or len(dedup))
        backend = str(row.get("Backend") or "fabric-native")
        if backend not in backend_order:
            backend_order.append(backend)
        dedup[(ask_id, backend)] = row

    preferred = str((run_row or {}).get("PrimaryBackend") or "")
    if preferred and any(b == preferred for (_a, b) in dedup):
        chosen_backend = preferred
    elif "fabric-native" in backend_order:
        chosen_backend = "fabric-native"
    else:
        chosen_backend = backend_order[0]

    return [r for (_a, b), r in dedup.items() if b == chosen_backend]


def _load_run_bundle(
    folder: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if not folder.exists():
        raise FileNotFoundError(f"Run directory not found: {folder}")
    sink = JsonlSink(folder)
    runs = sink.read("EvalRun")
    questions = sink.read("EvalQuestion")
    results = sink.read("EvalResult")
    queries = sink.read("FabricIqQuery")

    run_row = dict(runs[-1]) if runs else {}
    qmap = {str(q.get("QuestionId") or ""): dict(q) for q in questions if q.get("QuestionId")}
    primary_results = _select_primary_results(results, run_row)

    queries_by_ask: dict[str, list[dict[str, Any]]] = {}
    for qr in queries:
        aid = str(qr.get("AskId") or "")
        if aid:
            queries_by_ask.setdefault(aid, []).append(dict(qr))
    return run_row, qmap, primary_results, queries_by_ask


def _format_citations(res: Mapping[str, Any]) -> str:
    names = res.get("CitedArtifactNames")
    if isinstance(names, Sequence) and not isinstance(names, (str, bytes)) and names:
        cleaned = [str(n) for n in names if str(n).strip()]
        if cleaned:
            return ", ".join(cleaned)
    arts = res.get("CitedArtifacts")
    if isinstance(arts, str) and arts.strip():
        return arts.strip()
    if isinstance(arts, Sequence) and not isinstance(arts, (str, bytes)) and arts:
        extracted = [
            str(a.get("name") or a.get("url") or "")
            for a in arts
            if isinstance(a, Mapping) and (a.get("name") or a.get("url"))
        ]
        if extracted:
            return ", ".join(extracted)
    return "None"


def _percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    k = (len(vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def render_html_report(
    run_dir: str | Path,
    out_path: str | Path | None = None,
    *,
    compare_dir: str | Path | None = None,
) -> Path:
    """Render a self-contained, accessible HTML5 evaluation report for `run_dir`."""
    folder = Path(run_dir)
    dst = Path(out_path) if out_path is not None else folder / "report.html"

    run_row, qmap, result_rows, queries_by_ask = _load_run_bundle(folder)
    repeats_k = max(
        1,
        int(run_row.get("Repeats") or 0) or max((int(r.get("Attempt") or 1) for r in result_rows), default=1),
    )
    stats = summarize_run_stats(result_rows, k=repeats_k)

    comparison: dict[str, Any] | None = None
    compare_run_id = ""
    if compare_dir is not None:
        comp_folder = Path(compare_dir)
        comp_run_row, _comp_qmap, comp_results, _comp_queries = _load_run_bundle(comp_folder)
        compare_run_id = str(comp_run_row.get("RunId") or comp_folder.name)
        comparison = compare_runs(comp_results, result_rows, k=repeats_k)

    run_id = str(run_row.get("RunId") or folder.name)
    run_name = str(run_row.get("RunName") or run_id)
    target = str(run_row.get("Target") or "copilot-chat")
    surface = str(run_row.get("Surface") or target)

    routing_dist: dict[str, int] = {}
    lat_vals: list[float] = []
    for r in result_rows:
        rev = str(r.get("RoutingEvidence") or "").strip()
        if rev:
            routing_dist[rev] = routing_dist.get(rev, 0) + 1
        if str(r.get("Verdict") or "").upper() != "ERROR" and r.get("LatencyMs") is not None:
            try:
                lat_vals.append(float(r["LatencyMs"]))
            except (TypeError, ValueError):
                pass

    if routing_dist:
        dominant_routing = max(routing_dist.items(), key=lambda kv: kv[1])[0]
    else:
        dominant_routing = "citations-only"

    ci_low = float(stats.get("wilson_low") or 0.0)
    ci_high = float(stats.get("wilson_high") or 0.0)
    k_max = int(stats.get("k") or repeats_k)
    pass_at_k = _fmt_pct(stats.get("mean_pass_at_k"))
    pass_hat_k = _fmt_pct(stats.get("mean_pass_pow_k"))
    lat_p50 = _fmt_ms(_percentile(lat_vals, 50.0))
    lat_p95 = _fmt_ms(_percentile(lat_vals, 95.0))

    compare_html = ""
    if comparison is not None:
        p_val = float(comparison["mcnemar_p"])
        sig_text = (
            "Statistically significant (p < 0.05)" if comparison["significant"] else "Not significant at alpha=0.05"
        )
        delta_pct = float(comparison["delta_pass_rate"]) * 100.0
        regs = ", ".join(_esc(qid) for qid in comparison.get("regressions") or []) or "none"
        imps = ", ".join(_esc(qid) for qid in comparison.get("improvements") or []) or "none"
        compare_html = (
            '<section class="banner" aria-label="Baseline comparison">'
            f"<h2>Baseline vs Candidate Comparison (McNemar Exact Test)</h2>"
            f"<p><strong>Baseline:</strong> <code>{_esc(compare_run_id)}</code> "
            f"({_fmt_pct(comparison['baseline_pass_rate'])}) &rarr; "
            f"<strong>Candidate:</strong> <code>{_esc(run_id)}</code> "
            f"({_fmt_pct(comparison['candidate_pass_rate'])}, "
            f"delta {delta_pct:+.1f} pp across {int(comparison['paired_count'])} paired questions)</p>"
            f"<p><strong>McNemar p-value:</strong> <code>{p_val:.4f}</code> ({_esc(sig_text)}) &middot; "
            f"<strong>Improvements (0&rarr;1):</strong> {int(comparison['c'])} ({imps}) &middot; "
            f"<strong>Regressions (1&rarr;0):</strong> {int(comparison['b'])} ({regs})</p>"
            "</section>"
        )

    cat_rows_html: list[str] = []
    by_cat = stats.get("by_category") or {}
    for cat_name, cat_data in by_cat.items():
        c_low = float(cat_data.get("wilson_low") or 0.0)
        c_high = float(cat_data.get("wilson_high") or 0.0)
        cat_rows_html.append(
            "<tr>"
            f"<td>{_esc(cat_name)}</td>"
            f"<td>{int(cat_data.get('question_count') or 0)}</td>"
            f"<td>{int(cat_data.get('total_asks') or 0)}</td>"
            f"<td>{int(cat_data.get('passed_asks') or 0)}</td>"
            f"<td>{_fmt_pct(cat_data.get('pass_rate'))}</td>"
            f"<td>[{c_low:.3f}, {c_high:.3f}]</td>"
            "</tr>"
        )
    if not cat_rows_html:
        cat_rows_html.append('<tr><td colspan="6">No category results recorded.</td></tr>')

    ask_blocks: list[str] = []
    for res in result_rows:
        ask_id = str(res.get("AskId") or "")
        qid = str(res.get("QuestionId") or "")
        attempt = int(res.get("Attempt") or 1)
        q_meta = qmap.get(qid, {})
        question_text = str(res.get("Question") or q_meta.get("Question") or "")
        verdict_str = str(res.get("Verdict") or "UNKNOWN")
        match_kind = str(res.get("MatchKind") or "n/a")
        extraction_method = str(res.get("ExtractionMethod") or "n/a")
        routing_ev = str(res.get("RoutingEvidence") or dominant_routing)

        exp_val = res.get("ExpectedValue")
        if exp_val is None:
            exp_display = str(q_meta.get("ExpectedAnswer") or q_meta.get("CaseType") or "n/a")
        else:
            unit_str = str(res.get("Unit") or q_meta.get("Unit") or "")
            exp_display = f"{exp_val} ({unit_str})" if unit_str else str(exp_val)

        ext_val = res.get("ExtractedValue")
        ext_display = "n/a" if ext_val is None else str(ext_val)

        citations_display = _format_citations(res)
        dax_preview = str(res.get("DaxPreview") or "").strip()
        if not dax_preview and ask_id in queries_by_ask:
            dax_preview = "\n\n".join(
                str(q_item.get("Dax") or "") for q_item in queries_by_ask[ask_id] if q_item.get("Dax")
            )[:1500]
        if not dax_preview:
            dax_preview = "No engine DAX captured for this ask."

        answer_text = str(res.get("AnswerPreview") or res.get("Answer") or "")
        reasons = res.get("Reasons") or []
        if isinstance(reasons, list):
            reasons_text = "; ".join(str(r) for r in reasons if str(r).strip())
        else:
            reasons_text = str(reasons)

        ask_blocks.append(
            '<details class="ask-row">'
            "<summary>"
            f'<span class="{_verdict_badge_class(verdict_str)}">{_esc(verdict_str)}</span>'
            f"<span><strong>{_esc(qid)}</strong> (#{attempt}): {_esc(question_text)}</span>"
            f'<span class="badge badge-neutral">{_esc(match_kind)}</span>'
            "</summary>"
            '<div class="ask-body">'
            '<div class="kv-grid">'
            f"<div><strong>MatchKind:</strong> <code>{_esc(match_kind)}</code></div>"
            f"<div><strong>ExtractionMethod:</strong> <code>{_esc(extraction_method)}</code></div>"
            f"<div><strong>Expected vs Extracted:</strong> <code>{_esc(exp_display)}</code> vs "
            f"<code>{_esc(ext_display)}</code></div>"
            f"<div><strong>Routing Evidence:</strong> <code>{_esc(routing_ev)}</code></div>"
            f"<div><strong>Citations:</strong> {_esc(citations_display)}</div>"
            f"<div><strong>AskId:</strong> <code>{_esc(ask_id)}</code></div>"
            "</div>"
            f"<div><strong>Answer:</strong><pre>{_esc(answer_text)}</pre></div>"
            + (f"<div><strong>Notes:</strong> {_esc(reasons_text)}</div>" if reasons_text else "")
            + f"<div><strong>DAX Preview:</strong><pre>{_esc(dax_preview)}</pre></div>"
            + "</div></details>"
        )

    if not ask_blocks:
        ask_blocks.append("<p>No ask results recorded in this run.</p>")

    ci_label = f"95% Wilson CI [{ci_low:.3f}, {ci_high:.3f}] ({_fmt_pct(ci_low)} - {_fmt_pct(ci_high)})"
    surface_sub = (
        f"Surface: <code>{_esc(surface)}</code> &middot; "
        f'Evidence: <span class="badge badge-neutral">{_esc(dominant_routing)}</span>'
    )

    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>cfeval Report - {_esc(run_name)}</title>
  <style>{_CSS}</style>
</head>
<body>
  <main>
    <header>
      <h1>{_esc(run_name)}</h1>
      <div class="meta">
        Run ID: <code>{_esc(run_id)}</code> &middot;
        Questions: {int(stats.get("question_count") or 0)} &middot;
        Scored Asks: {int(stats.get("total_asks") or 0)}
      </div>
    </header>

    <section class="cards" aria-label="Executive summary">
      <div class="card">
        <div class="card-label">Pass Rate</div>
        <div class="card-value">{_fmt_pct(stats.get("pass_rate"))}</div>
        <div class="card-sub">{ci_label}</div>
      </div>
      <div class="card">
        <div class="card-label">Repeatability (k={k_max})</div>
        <div class="card-value">pass@{k_max}: {pass_at_k}</div>
        <div class="card-sub">pass^{k_max}: {pass_hat_k}</div>
      </div>
      <div class="card">
        <div class="card-label">Target &amp; Routing Evidence</div>
        <div class="card-value"><span class="badge badge-neutral">{_esc(target)}</span></div>
        <div class="card-sub">{surface_sub}</div>
      </div>
      <div class="card">
        <div class="card-label">Latency</div>
        <div class="card-value">p50: {lat_p50}</div>
        <div class="card-sub">p95: {lat_p95}</div>
      </div>
    </section>

    {compare_html}

    <section aria-label="Category breakdown">
      <h2>Category Breakdown</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Questions</th>
            <th scope="col">Asks</th>
            <th scope="col">Passed</th>
            <th scope="col">Pass Rate</th>
            <th scope="col">95% Wilson CI</th>
          </tr>
        </thead>
        <tbody>
          {"".join(cat_rows_html)}
        </tbody>
      </table>
    </section>

    <section aria-label="Ask details">
      <h2>Per-Ask Results</h2>
      {"".join(ask_blocks)}
    </section>
  </main>
</body>
</html>
"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(doc, encoding="utf-8")
    return dst
