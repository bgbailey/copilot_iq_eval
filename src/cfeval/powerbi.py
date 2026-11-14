"""Power BI REST helpers: run DAX against a semantic model (executeQueries).

Used to refresh the golden set's expected values from reference DAX and to
send a DAX watermark that provides a workspace-monitoring ingestion progress signal.
Needs the tenant setting 'Dataset Execute Queries REST API' and Build (or
Read) permission on the semantic models.
"""

import time

import requests

from . import runtime
from .config import HttpStatusError, request_with_retry
from .scorers import normalize_name, split_list
from .trace import watermark_dax

PBI_API = "https://api.powerbi.com/v1.0/myorg"
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"


def powerbi_token(settings=None):
    return runtime.token_for(PBI_RESOURCE, settings)


class PowerBiError(RuntimeError):
    pass


def _q_model(q):
    return getattr(q, "model", None) or getattr(q, "expected_model", "") or ""


def _q_dax(q):
    return getattr(q, "reference_dax", None) or getattr(q, "grounding_query_dax", "") or ""


def _q_expected_val(q):
    val = getattr(q, "expected_value", None)
    if val is None:
        val = getattr(q, "expected", None)
    return val if isinstance(val, (int, float)) and not isinstance(val, bool) else None


def _set_q_expected_val(q, value):
    if hasattr(q, "expected_value"):
        q.expected_value = value
    if hasattr(q, "expected"):
        q.expected = value


class PowerBiClient:
    def __init__(
        self,
        token_provider=None,
        session=None,
        base_url=PBI_API,
        max_retries=None,
        timeout_s=None,
        settings=None,
        sleep_fn=time.sleep,
    ):
        self._token = token_provider or (lambda: powerbi_token(settings))
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        if max_retries is None:
            max_retries = getattr(settings, "http_max_retries", 3) if settings is not None else 3
        if timeout_s is None:
            timeout_s = getattr(settings, "http_timeout_s", 120.0) if settings is not None else 120.0
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.sleep_fn = sleep_fn

    def _request(self, method, path, body=None):
        timeout = (
            (min(10.0, float(self.timeout_s)), float(self.timeout_s))
            if isinstance(self.timeout_s, (int, float))
            else self.timeout_s
        )
        try:
            r = request_with_retry(
                self.session,
                method,
                self.base_url + path,
                json=body,
                timeout=timeout,
                max_retries=self.max_retries,
                backoff_base=1.0,
                sleep_fn=self.sleep_fn,
                headers=lambda: {"Authorization": "Bearer " + self._token()},
                allow_redirects=False,
            )
            return r.json() if getattr(r, "content", None) else {}
        except HttpStatusError as exc:
            raise PowerBiError(
                "Power BI API %s %s returned %s: %s" % (method, path, exc.status_code, exc.body[:500])
            ) from exc
        except requests.RequestException as exc:
            raise PowerBiError("Power BI API %s %s failed: %s" % (method, path, exc)) from exc

    def datasets(self, workspace_id):
        return self._request("GET", "/groups/%s/datasets" % workspace_id).get("value", [])

    def dataset_ids(self, workspace_id):
        """{normalized semantic model name: id} for a workspace."""
        return {normalize_name(d.get("name")): d.get("id") for d in self.datasets(workspace_id)}

    def execute_dax(self, workspace_id, dataset_id, dax):
        out = self._request(
            "POST",
            "/groups/%s/datasets/%s/executeQueries" % (workspace_id, dataset_id),
            {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
        )
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
        model_name = _q_model(q)
        ref_dax = _q_dax(q)
        old_val = _q_expected_val(q)
        entry = {"QuestionId": q.id, "Model": model_name, "Old": old_val, "New": None, "Status": "", "Detail": ""}
        if not ref_dax:
            entry.update(Status="skipped", Detail="no reference DAX")
        elif normalize_name(model_name) not in ids:
            entry.update(Status="error", Detail="semantic model '%s' not found in the workspace" % model_name)
        else:
            try:
                value = client.scalar(workspace_id, ids[normalize_name(model_name)], ref_dax)
                if value is None:
                    entry.update(Status="error", Detail="reference DAX returned no rows")
                else:
                    value = float(value)
                    same = old_val is not None and abs(value - old_val) <= rel_change * max(abs(old_val), 1.0)
                    entry.update(New=value, Status="unchanged" if same else "updated")
                    _set_q_expected_val(q, value)
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
            decoys = getattr(q, "decoys", "") or ""
            names = [_q_model(q)] + (split_list(decoys) if include_decoys else [])
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
