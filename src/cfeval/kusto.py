"""Kusto (Eventhouse) query, management and ingestion helpers.

Authentication uses an explicit, identity-checked token provider for the
standard Kusto audience in both notebooks and local Azure CLI runs.
"""
import io
import json
from datetime import timedelta

from . import runtime

KUSTO_AUDIENCE = "https://kusto.kusto.windows.net"


def derive_ingest_uri(query_uri):
    """https://abc.z1.kusto.fabric.microsoft.com -> https://ingest-abc.z1.kusto.fabric.microsoft.com"""
    if not query_uri:
        return ""
    scheme, rest = query_uri.rstrip("/").split("://", 1)
    return "%s://%s" % (scheme, rest if rest.startswith("ingest-") else "ingest-" + rest)


def connection_builder(uri, settings=None):
    runtime.require_operator_settings(settings, cli=not runtime.in_fabric_notebook())
    from azure.kusto.data import KustoConnectionStringBuilder

    return KustoConnectionStringBuilder.with_token_provider(
        uri, lambda: runtime.token_for(KUSTO_AUDIENCE, settings=settings))


def _rows(table):
    cols = [c.column_name for c in table.columns]
    return [{c: row[c] for c in cols} for row in table]


class KustoQueryClient:
    def __init__(self, query_uri, settings=None):
        builder = connection_builder(query_uri, settings=settings)
        from azure.kusto.data import KustoClient

        self.query_uri = query_uri
        self._client = KustoClient(builder)

    def query(self, database, kql, parameters=None):
        from azure.kusto.data import ClientRequestProperties

        props = ClientRequestProperties()
        props.set_option(ClientRequestProperties.request_timeout_option_name, timedelta(seconds=45))
        for key, value in (parameters or {}).items():
            props.set_parameter(key, str(value))
        return _rows(self._client.execute(database, kql, props).primary_results[0])

    def mgmt(self, database, command):
        from azure.kusto.data import ClientRequestProperties

        props = ClientRequestProperties()
        props.set_option(ClientRequestProperties.request_timeout_option_name, timedelta(seconds=45))
        return _rows(self._client.execute_mgmt(database, command, props).primary_results[0])


class KustoIngestClient:
    """Streaming ingestion with automatic fallback to queued ingestion."""

    def __init__(self, query_uri, ingest_uri="", settings=None):
        query_builder = connection_builder(query_uri, settings=settings)
        ingest_builder = connection_builder(ingest_uri or derive_ingest_uri(query_uri), settings=settings)
        from azure.kusto.ingest import ManagedStreamingIngestClient

        self._client = ManagedStreamingIngestClient(query_builder, ingest_builder)

    def ingest_json(self, database, table, rows, mapping):
        from azure.kusto.data.data_format import DataFormat
        from azure.kusto.ingest import IngestionProperties

        if not rows:
            return 0
        payload = "\n".join(json.dumps(r, default=str, ensure_ascii=False) for r in rows).encode("utf-8")
        props = IngestionProperties(database=database, table=table, data_format=DataFormat.JSON,
                                    ingestion_mapping_reference=mapping)
        self._client.ingest_from_stream(io.BytesIO(payload), ingestion_properties=props)
        return len(rows)
