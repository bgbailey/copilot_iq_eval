"""Sign in as the test user and ask Microsoft 365 Copilot through the Copilot Chat API.

The Copilot Chat API is a Microsoft Graph beta (preview) API that only accepts delegated sign-in, so
the script signs in as a person: always a dedicated test user, never a real employee.
"""
import os
from datetime import datetime, timezone

import msal
import requests

COPILOT = "https://graph.microsoft.com/beta/copilot"

# Delegated permissions the Copilot Chat API requires, plus the two Fabric resources the script reads.
SCOPES = {
    "copilot": [f"https://graph.microsoft.com/{p}" for p in (
        "Sites.Read.All", "Mail.Read", "People.Read.All", "OnlineMeetingTranscript.Read.All",
        "Chat.Read", "ChannelMessage.Read.All", "ExternalItem.Read.All")],
    "powerbi": ["https://analysis.windows.net/powerbi/api/Dataset.Read.All"],
    "kusto": ["https://kusto.kusto.windows.net/user_impersonation"],
}
CACHE_FILE = ".token_cache.json"  # kept on your machine only (listed in .gitignore)


class SignIn:
    def __init__(self, tenant_id, client_id, test_user):
        self.test_user = test_user
        self.cache = msal.SerializableTokenCache()
        if os.path.exists(CACHE_FILE):
            self.cache.deserialize(open(CACHE_FILE, encoding="utf-8").read())
        self.app = msal.PublicClientApplication(
            client_id, authority=f"https://login.microsoftonline.com/{tenant_id}", token_cache=self.cache)

    def token(self, resource):
        scopes = SCOPES[resource]
        accounts = [a for a in self.app.get_accounts() if a["username"].lower() == self.test_user.lower()]
        result = self.app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
        if not result:
            flow = self.app.initiate_device_flow(scopes=scopes)
            print(f"\nSign in as {self.test_user}. {flow['message']}\n")
            result = self.app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise SystemExit(f"Sign-in failed: {result.get('error_description', result)}")
        signed_in = (result.get("id_token_claims") or {}).get("preferred_username", self.test_user)
        if signed_in.lower() != self.test_user.lower():
            raise SystemExit(f"Signed in as {signed_in}, but TEST_USER is {self.test_user}. Use the test user only.")
        if self.cache.has_state_changed:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(self.cache.serialize())
        return result["access_token"]


def _post(url, token, body):
    r = requests.post(url, json=body, timeout=180,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def ask(token, question):
    """One new conversation per question, web grounding off. Returns the answer, citations and timing."""
    started = datetime.now(timezone.utc)
    conversation = _post(f"{COPILOT}/conversations", token, {})
    reply = _post(f"{COPILOT}/conversations/{conversation['id']}/chat", token, {
        "message": {"text": question},
        "locationHint": {"timeZone": "UTC"},
        "contextualResources": {"webContext": {"isWebEnabled": False}},
    })
    ended = datetime.now(timezone.utc)
    # The conversation echoes our question; Copilot's reply is the last message that isn't the echo.
    messages = [m for m in reply.get("messages", []) if (m.get("text") or "").strip() != question.strip()]
    message = messages[-1] if messages else {}
    citations = [{"title": a.get("providerDisplayName", ""), "url": a.get("seeMoreWebUrl", "")}
                 for a in message.get("attributions") or []]
    return {
        "answer": message.get("text", ""),
        "citations": citations,
        "started": started.isoformat().replace("+00:00", "Z"),
        "ended": ended.isoformat().replace("+00:00", "Z"),
        "latency_ms": int((ended - started).total_seconds() * 1000),
    }
