"""Spike S8: which surfaces answer joint Work IQ + Fabric IQ questions, and how well? (ADR-011)

The joint cases (PLAN §4.4, ADR-010) need an answer that takes the actual figure from a certified
semantic model and the target from a seeded SharePoint document, and cites both. Work IQ documents no
Power BI source of its own, so this spike measures, per surface:

    chat        Microsoft 365 Copilot Chat API, no files named
    chat-files  Chat API with the targets memo as a contextual file (contextualResources.files)
    workiq      Work IQ API (POST /rest/conversations/{id}/chat), memo as a contextual file

For JNT-001 as exec it records: memo cited, target stated ($12.5M), actual stated (the deployment
snapshot, $12.84M), Power BI or Fabric attribution present. For JNT-004 as noaccess it checks that
neither the memo nor the figures leak (permission trimming). `--search` first measures how long the
seeded documents take to become findable (Microsoft Search, a proxy for the semantic index).
The declarative-agent surface is checked with spike S3 and the agent from P4.1.

    uv run python spikes/s8_workiq_grounding.py                 # every surface
    uv run python spikes/s8_workiq_grounding.py --surface workiq --search

Needs `evals deploy fabric` and `evals deploy workiq` (runs/deploy/workiq-documents.json names the
memo URL) and, for the workiq surface, Work IQ enabled for the tenant (PLAN §6 T21). Raw responses
go to spikes/out/s8/.
"""

import argparse
import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from _common import (
    GRAPH_CHAT_SCOPES,
    ROOT,
    close_to,
    expected_value,
    golden,
    heading,
    numbers_in,
    persona_token,
    save,
    settings,
    utc_now,
)

CHAT_API = "https://graph.microsoft.com/beta/copilot/conversations"
WORKIQ_API = "https://workiq.svc.cloud.microsoft/rest/conversations"
WORKIQ_SCOPES = ["api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"]
SEARCH_API = "https://graph.microsoft.com/v1.0/search/query"
POWER_BI_HOSTS = ("app.powerbi.com", "app.fabric.microsoft.com", "powerbi.com")
CALIBRATED_ACTUAL = Decimal("12840000")  # nb_01 calibrates FY2025 gross revenue to this figure


def memo_url() -> str:
    seeded = ROOT / "runs" / "deploy" / "workiq-documents.json"
    if not seeded.exists():
        raise SystemExit("run `evals deploy workiq` first: runs/deploy/workiq-documents.json names the memo URL")
    documents = {d["key"]: d for d in json.loads(seeded.read_text(encoding="utf-8"))}
    return str(documents["fy25_revenue_targets"]["web_url"])


def ask(surface: str, persona: str, prompt: str, files: list[str]) -> dict[str, Any]:
    """One question on one surface; returns status, latency, answer text and attributions."""
    if surface == "workiq":
        base, token = WORKIQ_API, persona_token(persona, WORKIQ_SCOPES)
    else:
        base, token = CHAT_API, persona_token(persona, GRAPH_CHAT_SCOPES)
    body: dict[str, Any] = {"message": {"text": prompt}, "locationHint": {"timeZone": settings().chat_api.time_zone}}
    if files:
        body["contextualResources"] = {"files": [{"uri": uri} for uri in files]}
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=settings().chat_api.read_timeout_s, headers=headers) as client:
        conversation = client.post(base, json={})
        if conversation.status_code >= 400:
            return {"status": conversation.status_code, "error": conversation.text}
        started = time.monotonic()
        reply = client.post(f"{base}/{conversation.json()['id']}/chat", json=body)
        latency_ms = int((time.monotonic() - started) * 1000)
    if reply.status_code >= 400:
        return {"status": reply.status_code, "error": reply.text, "latency_ms": latency_ms}
    raw = reply.json()
    answer = next((m for m in reversed(raw.get("messages", [])) if m.get("text") and m.get("text") != prompt), {})
    return {"status": reply.status_code, "latency_ms": latency_ms, "text": answer.get("text", ""),
            "attributions": answer.get("attributions") or [], "raw": raw}


def assess(result: dict[str, Any], match: list[str]) -> dict[str, bool]:
    text = result.get("text", "")
    attributions = result.get("attributions", [])
    sources = " ".join(f"{a.get('providerDisplayName', '')} {a.get('seeMoreWebUrl', '')}" for a in attributions)
    haystack = f"{text} {sources}".lower()
    numbers = numbers_in(text)
    actual = Decimal(expected_value("JNT-001") or CALIBRATED_ACTUAL)
    return {
        "memo_cited": any(fragment.lower() in haystack for fragment in match),
        "target_stated": close_to(numbers, Decimal("12500000")),
        "actual_stated": close_to(numbers, actual),
        "power_bi_attribution": any(host in sources for host in POWER_BI_HOSTS),
    }


def wait_until_searchable(persona: str, title: str, timeout_s: int) -> float | None:
    """Seconds from the memo's last modification until Microsoft Search returns it, or None."""
    token = persona_token(persona, ["https://graph.microsoft.com/Sites.Read.All"])
    request = {"requests": [{"entityTypes": ["driveItem"], "query": {"queryString": f'"{title}"'}, "size": 5}]}
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
        while time.monotonic() < deadline:
            hits = [hit for container in client.post(SEARCH_API, json=request).json().get("value", [])
                    for group in container.get("hitsContainers", []) for hit in group.get("hits", [])]
            if hits:
                modified = hits[0]["resource"].get("lastModifiedDateTime", "")
                return (utc_now() - datetime.fromisoformat(modified.replace("Z", "+00:00"))).total_seconds()
            print(f"not searchable yet; checking again in 5 minutes (gives up after {timeout_s} s)")
            time.sleep(300)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--surface", choices=["chat", "chat-files", "workiq"], action="append",
                        help="surface to test (repeatable; default all)")
    parser.add_argument("--search", action="store_true", help="first wait until Microsoft Search finds the memo")
    parser.add_argument("--search-timeout", type=int, default=86_400)
    args = parser.parse_args()

    cases = {case.id: case for case in golden().cases}
    target_doc = golden().documents["fy25_revenue_targets"]
    url = memo_url()
    record: dict[str, Any] = {"memo_url": url, "results": []}
    if args.search:
        delay = wait_until_searchable("exec", target_doc.title.removesuffix(".docx"), args.search_timeout)
        record["searchable_after_s"] = delay
        print(f"Memo searchable {f'after {delay:.0f} s' if delay is not None else 'NOT within the timeout'}")

    for surface in args.surface or ["chat", "chat-files", "workiq"]:
        files = [url] if surface in {"chat-files", "workiq"} else []
        for case_id in ("JNT-001", "JNT-004"):
            case = cases[case_id]
            result = ask(surface, case.persona, case.prompt, files)
            checks = assess(result, target_doc.match) if "text" in result else {}
            record["results"].append({"surface": surface, "case": case_id, "persona": case.persona, **result,
                                       "checks": checks})
    path = save("s8", "joint-grounding", record)

    heading("For ADR-011: joint answers by surface")
    print(f"{'surface':<11} {'case':<8} {'persona':<9} {'HTTP':<5} memo  target actual PowerBI  ms")
    for row in record["results"]:
        checks = row.get("checks") or {}
        marks = [("yes" if checks.get(k) else "no ") if checks else " - " for k in
                 ("memo_cited", "target_stated", "actual_stated", "power_bi_attribution")]
        print(f"{row['surface']:<11} {row['case']:<8} {row['persona']:<9} {row['status']:<5} "
              f"{marks[0]:<5} {marks[1]:<6} {marks[2]:<6} {marks[3]:<7} {row.get('latency_ms', '')}")
    print("JNT-001 passes with yes in every column; JNT-004 (noaccess) passes with no memo and no figures.")
    print(f"Raw responses: {path}")


if __name__ == "__main__":
    main()
