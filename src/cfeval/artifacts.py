"""Turn Copilot Chat attributions and answer links into typed artifacts."""

import re
from urllib.parse import unquote, urlparse

from .scorers import POWERBI_KINDS

_PBI = re.compile(
    r"https?://(?:app\.)?(?:powerbi\.com|fabric\.microsoft\.com)/"
    r"(?:groups/(?P<ws>[^/?#]+)/)?"
    r"(?P<kind>reports|datasets|semanticmodels|rdlreports|dashboards|apps|links|aiskills|dataagents)/"
    r"(?P<id>[0-9A-Za-z-]+)",
    re.I,
)
_KIND_MAP = {
    "reports": "powerbi_report",
    "datasets": "semantic_model",
    "semanticmodels": "semantic_model",
    "rdlreports": "paginated_report",
    "dashboards": "powerbi_dashboard",
    "apps": "powerbi_app",
    "links": "powerbi_link",
    "aiskills": "fabric_data_agent",
    "dataagents": "fabric_data_agent",
}
_MD_LINK = re.compile(r"\[(?P<name>[^\]]{1,200})\]\((?P<url>https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"(?<![(\[])https?://[^\s)\]>\"']+")


def classify_url(url):
    """Return (kind, workspace_id, item_id) for a URL."""
    url = (url or "").strip()
    m = _PBI.search(url)
    if m:
        return _KIND_MAP[m.group("kind").lower()], (m.group("ws") or ""), m.group("id")
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("-my.sharepoint.com"):
        return "onedrive_file", "", ""
    if host.endswith(".sharepoint.com"):
        return "sharepoint_file", "", ""
    if host.endswith("teams.microsoft.com"):
        return "teams", "", ""
    if host.endswith("office.com") or host.endswith("outlook.office.com") or host.endswith("outlook.office365.com"):
        return "m365", "", ""
    if host:
        return "web", "", ""
    return "other", "", ""


def _name_from_url(url):
    path = urlparse(url).path.rstrip("/")
    last = unquote(path.split("/")[-1]) if path else ""
    return last or (urlparse(url).hostname or url)


def make_artifact(name, url, source, attribution_type="", attribution_source=""):
    kind, ws, item_id = classify_url(url)
    return {
        "kind": kind,
        "name": (name or "").strip() or _name_from_url(url),
        "url": url,
        "workspace_id": ws,
        "item_id": item_id,
        "source": source,
        "attribution_type": attribution_type or "",
        "attribution_source": attribution_source or "",
        "answer_cited": source == "answer_link",
    }


def extract_artifacts(attributions, answer_text=""):
    """Collect artifacts from Chat API attributions plus links in the answer text."""
    found = []
    for att in attributions or []:
        url = att.get("seeMoreWebUrl") or att.get("url") or ""
        if not url:
            continue
        found.append(
            make_artifact(
                att.get("providerDisplayName") or "",
                url,
                "attribution",
                att.get("attributionType") or "",
                att.get("attributionSource") or "",
            )
        )
    text = answer_text or ""
    for m in _MD_LINK.finditer(text):
        found.append(make_artifact(m.group("name"), m.group("url"), "answer_link"))
    for m in _BARE_URL.finditer(_MD_LINK.sub(" ", text)):
        found.append(make_artifact("", m.group(0), "answer_link"))
    unique: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for a in found:
        key = (a["kind"], (a["item_id"] or a["url"]).lower())
        if key in seen:
            # prefer the entry that carries a display name
            for u in unique:
                if (u["kind"], (u["item_id"] or u["url"]).lower()) == key:
                    u["answer_cited"] = u.get("answer_cited", False) or a["answer_cited"]
                    if not u["name"] and a["name"]:
                        u["name"] = a["name"]
            continue
        seen.add(key)
        unique.append(a)
    return unique


def powerbi_artifacts(artifacts):
    return [a for a in artifacts or [] if a.get("kind") in POWERBI_KINDS]


def summarize(artifacts):
    return "; ".join("%s (%s)" % (a.get("name") or a.get("url"), a.get("kind")) for a in artifacts or [])
