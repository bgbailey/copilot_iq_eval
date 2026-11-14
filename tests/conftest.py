"""Shared offline fixtures and live-test skip gate."""

from __future__ import annotations

import os
import socket

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("CFEVAL_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live Microsoft endpoint test skipped unless CFEVAL_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _block_live_network_in_offline_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure non-live tests never accidentally connect to external cloud hosts."""
    if "live" in request.keywords:
        return
    real_create_connection = socket.create_connection

    def guarded_create_connection(address: tuple[str, int], *args: object, **kwargs: object) -> socket.socket:
        host = str(address[0]).lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise AssertionError(f"Offline test attempted external network connection to {host!r}")
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
