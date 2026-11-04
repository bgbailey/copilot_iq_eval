"""JSON over HTTPS for the setup commands: retries, paging and Fabric long-running operations.

Standard library only, so it adds no dependency, and the transport is a plain function that unit
tests replace with a fake. Behaviour follows the documented service contracts
(config/contracts.yaml ``fabric_rest``, ``graph_sharepoint_files``):

* 429 and 5xx responses are retried, waiting for ``Retry-After`` when the service sends it;
* list endpoints are followed through ``continuationUri`` (Fabric) or ``@odata.nextLink`` (Graph,
  Power BI);
* a Fabric ``202 Accepted`` is polled at its ``Location`` until the operation or job finishes.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

#: Returns an access token for a scope, for example ``https://api.fabric.microsoft.com/.default``.
TokenProvider = Callable[[str], str]

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
OPERATION_DONE = frozenset({"Succeeded", "Failed", "Cancelled"})
JOB_DONE = frozenset({"Completed", "Failed", "Cancelled", "Deduped"})


@dataclass(frozen=True)
class Response:
    """An HTTP response with lower-case header names."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        """The body parsed as JSON, or None for an empty body."""
        return json.loads(self.body) if self.body else None

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


#: Sends one request: (method, url, headers, body) -> Response. Must not raise for HTTP error statuses.
Transport = Callable[[str, str, Mapping[str, str], bytes | None], Response]


class SetupError(RuntimeError):
    """A setup step could not complete; the message says what failed and what to check."""


class HttpError(SetupError):
    """A request returned an unexpected status. ``code`` is the service error code when there is one."""

    def __init__(self, method: str, url: str, status: int, body: bytes) -> None:
        self.status = status
        self.code, detail = _service_error(body)
        super().__init__(f"{method} {url.split('?')[0]} returned {status}{f' {self.code}' if self.code else ''}"
                         f"{f': {detail}' if detail else ''}")


def _service_error(body: bytes) -> tuple[str | None, str]:
    """The error code and message from a Fabric, Power BI or Graph error body."""
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        return None, body[:300].decode("utf-8", "replace")
    if not isinstance(payload, dict):
        return None, ""
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("code"), str(error.get("message", ""))
    return payload.get("errorCode"), str(payload.get("message", ""))


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> Response:
    """The production transport: urllib with a 120-second timeout. HTTPS only."""
    if not url.startswith("https://"):
        raise SetupError(f"refusing a non-HTTPS URL: {url}")
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:  # noqa: S310  # nosec B310 - HTTPS checked above
            return Response(reply.status, {k.lower(): v for k, v in reply.headers.items()}, reply.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, {k.lower(): v for k, v in error.headers.items()}, error.read())


class JsonHttp:
    """Authenticated JSON requests with retries. One instance serves every API the setup calls."""

    def __init__(
        self,
        tokens: TokenProvider,
        *,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_attempts: int = 6,
    ) -> None:
        self._tokens = tokens
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._max_attempts = max_attempts

    def request(
        self,
        method: str,
        url: str,
        *,
        scope: str,
        json_body: Any = None,
        data: bytes | None = None,
        content_type: str | None = None,
        expected: tuple[int, ...] = (200, 201, 202),
    ) -> Response:
        """Send a request, retrying throttling and server errors; raise HttpError for other failures."""
        headers = {"Authorization": f"Bearer {self._tokens(scope)}", "Accept": "application/json"}
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type
        for attempt in range(1, self._max_attempts + 1):
            response = self._transport(method, url, headers, body)
            if response.status in expected:
                return response
            if response.status in RETRY_STATUSES and attempt < self._max_attempts:
                self._sleep(_retry_after(response, default=min(2.0**attempt, 60.0)))
                continue
            raise HttpError(method, url, response.status, response.body)
        raise AssertionError("unreachable")  # pragma: no cover

    def get(self, url: str, *, scope: str, expected: tuple[int, ...] = (200,)) -> Any:
        return self.request("GET", url, scope=scope, expected=expected).json()

    def paged(self, url: str, *, scope: str) -> Iterator[dict[str, Any]]:
        """Every item of a list endpoint, following Fabric and OData continuation links."""
        next_url: str | None = url
        while next_url:
            page = self.get(next_url, scope=scope) or {}
            yield from page.get("value", [])
            next_url = page.get("continuationUri") or page.get("@odata.nextLink")

    def wait_for_operation(self, response: Response, *, scope: str, timeout_s: float = 1800) -> Any:
        """The result of a Fabric request that may run as a long-running operation (HTTP 202)."""
        if response.status != 202:
            return response.json()
        location = _required_header(response, "location")
        deadline = self._clock() + timeout_s
        delay = _retry_after(response, default=5.0)
        while True:
            self._sleep(delay)
            poll = self.request("GET", location, scope=scope, expected=(200, 202))
            state = poll.json() or {}
            status = state.get("status")
            if status == "Succeeded":
                result_url = poll.header("location")
                return self.get(result_url, scope=scope) if result_url else None
            if status in OPERATION_DONE:
                raise SetupError(f"Fabric operation {status.lower()}: {json.dumps(state.get('error'))}")
            if self._clock() > deadline:
                raise SetupError(f"Fabric operation still {status} after {timeout_s:.0f} s: {location}")
            delay = _retry_after(poll, default=delay)

    def wait_for_job(
        self, location: str, *, scope: str, timeout_s: float, first_poll_s: float = 60, poll_s: float = 20
    ) -> dict[str, Any]:
        """Poll a Fabric job instance (for example a notebook run) until it finishes; raise unless Completed.

        The first poll waits ``first_poll_s``: the run request's Retry-After, which clients must honour.
        """
        deadline = self._clock() + timeout_s
        delay = max(first_poll_s, 1.0)
        while True:
            self._sleep(delay)
            delay = poll_s
            job: dict[str, Any] = self.get(location, scope=scope) or {}
            status = job.get("status")
            if status == "Completed":
                return job
            if status in JOB_DONE:
                reason = json.dumps(job.get("failureReason")) if job.get("failureReason") else "no reason given"
                raise SetupError(f"Fabric job {status}: {reason}. Open the run in the Fabric monitoring hub.")
            if self._clock() > deadline:
                raise SetupError(f"Fabric job still {status} after {timeout_s:.0f} s: {location}")


def _retry_after(response: Response, *, default: float) -> float:
    value = response.header("retry-after")
    try:
        return max(float(value), 1.0) if value else default
    except ValueError:
        return default


def _required_header(response: Response, name: str) -> str:
    value = response.header(name)
    if not value:
        raise SetupError(f"expected a {name} header on the {response.status} response")
    return value
