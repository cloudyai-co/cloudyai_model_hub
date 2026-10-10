"""Shared pytest fixtures.

The suite never touches the network. Hub requests are answered by ``fake_hub`` through
``httpx.ASGITransport``, and each test starts with an empty cache and no Hub environment variables.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import hf_client
from backend.tests.fake_hub import create_fake_hub

_HUB_ENV = (
    "HF_ENDPOINT",
    "HF_TOKEN",
    "HUB_CACHE_TTL_SECONDS",
    "HUB_CACHE_MAX_ENTRIES",
    "HUB_HTTP_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _isolated_hub_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in _HUB_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hf_client, "_TRANSPORT", None)
    hf_client.clear_cache()
    yield
    hf_client.clear_cache()


@pytest.fixture
def install_hub(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FastAPI]:
    """Factory: serve Hub requests from a fake Hub built with ``create_fake_hub(**kwargs)``."""

    def install(**kwargs: Any) -> FastAPI:
        app = create_fake_hub(**kwargs)
        monkeypatch.setattr(hf_client, "_TRANSPORT", httpx.ASGITransport(app=app))
        hf_client.clear_cache()
        return app

    return install


@pytest.fixture
def hub(install_hub: Callable[..., FastAPI]) -> FastAPI:
    """The default fake Hub, backed by every fixture model."""
    return install_hub()


@pytest.fixture
def client(hub: FastAPI) -> Any:
    """HTTP client for the real application, wired to the fake Hub."""
    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fixtures_root() -> Path:
    from backend.tests.fake_hub import FIXTURES_DIR

    return FIXTURES_DIR
