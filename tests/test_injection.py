"""Seam: the four boundaries (HF, arXiv, LLM, parser) are injected at app creation, never imported by routes.

Feature routes read them with `BoundariesDep`; here a throwaway route stands in for a feature.
"""
from datetime import date

from fastapi import APIRouter
from fastapi.testclient import TestClient

from paperbrief import boundaries as boundary_factories
from paperbrief.app import create_app
from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.deps import BoundariesDep
from paperbrief.hf import HFPaper
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser, fake_boundaries

DAY = date(2026, 10, 2)
PAPER = HFPaper(arxiv_id="2610.00001", published_day=DAY, title="Injected", abstract="abs")


def probe_router() -> APIRouter:
    router = APIRouter()

    @router.get("/probe")
    def probe(b: BoundariesDep) -> dict:
        day, papers = b.hf.latest_day()
        return {"day": day.isoformat(), "titles": [p.title for p in papers]}

    return router


def test_routes_see_the_injected_boundaries(tmp_path):
    boundaries = Boundaries(FakeHF({DAY: [PAPER]}), FakeArxiv(), FakeLLM(), FakeParser())
    app = create_app(Settings(data_dir=tmp_path), boundaries)
    app.include_router(probe_router())
    assert TestClient(app).get("/probe").json() == {"day": "2026-10-02", "titles": ["Injected"]}


def test_offline_flag_uses_the_offline_boundaries_through_the_same_injection_point(tmp_path, monkeypatch):
    fakes = Boundaries(FakeHF({DAY: [PAPER]}), FakeArxiv(), FakeLLM(), FakeParser())
    monkeypatch.setattr(boundary_factories, "offline", lambda settings: fakes)
    monkeypatch.setattr(boundary_factories, "live", lambda settings: fake_boundaries())
    app = create_app(Settings(data_dir=tmp_path, offline=True))
    app.include_router(probe_router())
    client = TestClient(app)
    assert client.get("/probe").json()["titles"] == ["Injected"]
    assert client.get("/api/health").json()["offline"] is True


def test_app_starts_without_openai_key_and_says_so(make_client):
    health = make_client(openai_api_key="").get("/api/health").json()
    assert health["ok"] is True and health["openai_configured"] is False
    assert make_client(openai_api_key="sk-test").get("/api/health").json()["openai_configured"] is True
