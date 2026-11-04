"""Spike S1: does the Microsoft 365 Copilot Chat API reach Fabric IQ / Power BI data? (ADR-001)

Asks one golden-set question through the Chat API (beta) as a persona and records:

* the answer text and every attribution (do any point at Power BI or Fabric?);
* whether the answer states the expected value from the deployment snapshot
  (runs/deploy/expected_snapshot.json, written by `evals deploy fabric`);
* the request window (t0, t1), so spike S2 can look for the query in the engine logs.

    uv run python spikes/s1_chat_api.py --case REV-001 --persona exec

Contract: config/contracts.yaml `copilot_chat_api`. Raw responses go to spikes/out/s1/.
"""

import argparse
import time
from decimal import Decimal

import httpx
from _common import (
    GRAPH_CHAT_SCOPES,
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
POWER_BI_HOSTS = ("app.powerbi.com", "app.fabric.microsoft.com", "powerbi.com")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", default="REV-001", help="golden case whose prompt to ask (default REV-001)")
    parser.add_argument("--persona", help="persona key (default: the case's persona)")
    parser.add_argument("--prompt", help="ask this text instead of the case prompt")
    args = parser.parse_args()

    case = next(c for c in golden().cases if c.id == args.case)
    persona = args.persona or case.persona
    prompt = args.prompt or case.prompt
    token = persona_token(persona, GRAPH_CHAT_SCOPES)
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=settings().chat_api.read_timeout_s, headers=headers) as client:
        conversation = client.post(CHAT_API, json={})
        conversation.raise_for_status()
        conversation_id = conversation.json()["id"]
        t0 = utc_now()
        started = time.monotonic()
        reply = client.post(
            f"{CHAT_API}/{conversation_id}/chat",
            json={"message": {"text": prompt}, "locationHint": {"timeZone": settings().chat_api.time_zone}},
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        t1 = utc_now()
    body = reply.json() if reply.headers.get("content-type", "").startswith("application/json") else reply.text
    path = save("s1", f"{args.case}-{persona}", {
        "case": args.case, "persona": persona, "prompt": prompt, "status": reply.status_code,
        "t0_utc": t0.isoformat(), "t1_utc": t1.isoformat(), "latency_ms": latency_ms, "response": body,
    })

    heading(f"S1 {args.case} as {persona}: HTTP {reply.status_code} in {latency_ms} ms")
    if reply.status_code != 200 or not isinstance(body, dict):
        print(body)
        return
    answer = next((m for m in reversed(body.get("messages", [])) if m.get("text") and m.get("text") != prompt), {})
    text = answer.get("text", "")
    print(text)
    attributions = answer.get("attributions") or []
    heading("Attributions")
    for item in attributions:
        print(f"- {item.get('attributionType')} | {item.get('providerDisplayName')} | {item.get('seeMoreWebUrl')}")
    power_bi = [a for a in attributions if any(h in str(a.get("seeMoreWebUrl", "")) for h in POWER_BI_HOSTS)]
    expected = expected_value(args.case)
    heading("For ADR-001")
    print(f"Power BI / Fabric attribution: {'yes' if power_bi else 'no'} ({len(power_bi)} of {len(attributions)})")
    if expected is None:
        print("Expected value: no deployment snapshot (run `evals deploy fabric` first)")
    else:
        hit = close_to(numbers_in(text), Decimal(expected))
        print(f"Expected value {expected}: {'stated' if hit else 'NOT stated'} in the answer")
    print(f"Engine-log window for S2: --t0 {t0.isoformat()} --t1 {t1.isoformat()}")
    print(f"Raw response: {path}")


if __name__ == "__main__":
    main()
