"""Power BI REST helpers: run DAX against a semantic model (executeQueries).

Used to refresh the golden set's expected values from reference DAX and to
send a DAX watermark that provides a workspace-monitoring ingestion progress signal.
Needs the tenant setting 'Dataset Execute Queries REST API' and Build (or
Read) permission on the semantic models.
"""
import time

import requests

from . import runtime
from .scorers import normalize_name, split_list
from .trace import watermark_dax

PBI_API = "https://api.powerbi.com/v1.0/myorg"
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"


def powerbi_token(settings=None):
    return runtime.token_for(PBI_RESOURCE, settings)


class PowerBiError(RuntimeError):
    pass


class PowerBiClient:
    def __init__(self, token_provider=None, session=None, base_url=PBI_API, max_retries=3, settings=None):
        self._token = token_provider or (lambda: powerbi_token(settings))
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries

    def _request(self, method, path, body=None):
        for attempt in range(self.max_retries + 1):
            r = self.session.request(method, self.base_url + path, json=body, timeout=120,
                                     headers={"Authorization": "Bearer " + self._token()}, allow_redirects=False)
            if r.status_code == 429 and attempt < self.max_retries:
                time.sleep(min(float(r.headers.get("Retry-After") or 5), 60))
                continue
            if r.status_code >= 300:
                raise PowerBiError("Power BI API %s %s returned %s: %s" % (method, path, r.status_code, r.text[:500]))
            return r.json() if r.content else {}
        raise PowerBiError("Power BI API %s %s: retries exhausted" % (method, path))

    def datasets(self, workspace_id):
        return self._request("GET", "/groups/%s/datasets" % workspace_id).get("value", [])

    def dataset_ids(self, workspace_id):
        """{normalized semantic model name: id} for a workspace."""
        return {normalize_name(d.get("name")): d.get("id") for d in self.datasets(workspace_id)}

    def execute_dax(self, workspace_id, dataset_id, dax):
        out = self._request("POST", "/groups/%s/datasets/%s/executeQueries" % (workspace_id, dataset_id), {
            "queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}})
        result = (out.get("results") or [{}])[0]
        if result.get("error"):
            raise PowerBiError("DAX error: %s" % result["error"])
        tables = result.get("tables") or [{}]
        return tables[0].get("rows") or []

    def scalar(self, workspace_id, dataset_id, dax):
        rows = self.execute_dax(workspace_id, dataset_id, dax)
        if not rows:
            return None
        return next(iter(rows[0].values()), None)


def refresh_expected_values(questions, client, workspace_id, rel_change=1e-9):
    """Run each question's reference DAX and update expected_value. Returns a change report."""
    ids = client.dataset_ids(workspace_id)
    report = []
    for q in questions:
        entry = {"QuestionId": q.id, "Model": q.model, "Old": q.expected_value, "New": None, "Status": "", "Detail": ""}
        if not q.reference_dax:
            entry.update(Status="skipped", Detail="no reference DAX")
        elif normalize_name(q.model) not in ids:
            entry.update(Status="error", Detail="semantic model '%s' not found in the workspace" % q.model)
        else:
            try:
                value = client.scalar(workspace_id, ids[normalize_name(q.model)], q.reference_dax)
                if value is None:
                    entry.update(Status="error", Detail="reference DAX returned no rows")
                else:
                    value = float(value)
                    old = q.expected_value
                    same = old is not None and abs(value - old) <= rel_change * max(abs(old), 1.0)
                    entry.update(New=value, Status="unchanged" if same else "updated")
                    q.expected_value = value
            except (PowerBiError, ValueError, TypeError) as exc:
                entry.update(Status="error", Detail=str(exc)[:300])
        report.append(entry)
    return report


class DaxWatermark:
    """Runs a marker DAX query to observe ingestion progress, not global ordering."""

    def __init__(self, client, workspace_id, dataset_id):
        self.client = client
        self.workspace_id = workspace_id
        self.dataset_id = dataset_id

    @classmethod
    def for_questions(cls, client, workspace_id, questions, include_decoys=False):
        ids = client.dataset_ids(workspace_id)
        for q in questions:
            names = [q.model] + (split_list(q.decoys) if include_decoys else [])
            for name in names:
                dataset_id = ids.get(normalize_name(name))
                if dataset_id:
                    return cls(client, workspace_id, dataset_id)
        raise PowerBiError("none of the golden set's semantic models were found in workspace %s" % workspace_id)

    def send(self, marker):
        self.client.execute_dax(self.workspace_id, self.dataset_id, watermark_dax(marker))


class DaxWatermarks:
    """Send the same marker to each independently collected model/decoy workspace."""

    def __init__(self, watermarks):
        self.watermarks = list(watermarks)

    def send(self, marker):
        for watermark in self.watermarks:
            watermark.send(marker)
