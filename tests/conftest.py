"""Shared test seam: build the app with fake boundaries and a temp data dir, talk to it with TestClient."""
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperbrief.app import create_app
from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from tests.fakes import fake_boundaries


@pytest.fixture
def make_client(tmp_path: Path) -> Callable[..., TestClient]:
    """make_client(boundaries=None, **settings_overrides) -> TestClient. Data dir is always under tmp_path."""

    def make(boundaries: Boundaries | None = None, **overrides) -> TestClient:
        settings = Settings(data_dir=tmp_path / "data", **overrides)
        return TestClient(create_app(settings, boundaries or fake_boundaries()))

    return make
