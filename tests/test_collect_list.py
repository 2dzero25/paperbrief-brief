"""Seam: HTTP API through TestClient. Ticket #4: 수집 -> 최근 발표일 목록 (fake HF; the real HF client has its own tests)."""
import threading
import time
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from paperbrief.boundaries import Boundaries
from paperbrief.hf import HFPaper
from paperbrief.routes.papers import get_today
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser

FRI = date(2026, 10, 2)
THU = date(2026, 10, 1)
CODE = "https://example.test/o/r"


def paper(arxiv_id: str, day: date = FRI, **kw) -> HFPaper:
    kw.setdefault("title", f"Title {arxiv_id}")
    kw.setdefault("abstract", "First sentence. Second sentence.")
    return HFPaper(arxiv_id=arxiv_id, published_day=day, **kw)


def client_with(make_client, hf) -> TestClient:
    return make_client(Boundaries(hf, FakeArxiv(), FakeLLM(), FakeParser()))


def wait_idle(client: TestClient) -> dict:
    for _ in range(500):
        state = client.get("/api/collect").json()
        if not state["running"]:
            return state
        time.sleep(0.01)
    raise AssertionError("collection never finished")


def collect(client: TestClient) -> dict:
    assert client.post("/api/collect").status_code == 202
    return wait_idle(client)


class ScriptedHF(FakeHF):
    """FakeHF that can be told to fail or to wait, and counts calls."""

    def __init__(self, days):
        super().__init__(days)
        self.fail = False
        self.gate: threading.Event | None = None
        self.calls = 0

    def latest_day(self):
        self.calls += 1
        if self.gate is not None:
            assert self.gate.wait(5)
        if self.fail:
            raise ConnectionError("HF is down")
        return super().latest_day()


def test_collect_saves_latest_day_only_and_lists_it(make_client):
    hf = FakeHF({FRI: [paper("2610.00001"), paper("2610.00002")], THU: [paper("2610.00009", THU)]})
    client = client_with(make_client, hf)
    assert client.get("/api/papers").json() == {"day": None, "recent": False, "count": 0, "papers": []}

    assert collect(client)["error"] is None

    listing = client.get("/api/papers").json()
    assert listing["day"] == "2026-10-02"
    assert listing["count"] == 2
    assert {p["arxiv_id"] for p in listing["papers"]} == {"2610.00001", "2610.00002"}


def test_card_shows_upvotes_title_en_summary_organization_and_code_flag(make_client):
    hf = FakeHF(
        {
            FRI: [
                paper(
                    "2610.00001",
                    title="With HF summary",
                    abstract="Abstract one. Abstract two.",
                    organization="Nanjing University",
                    upvotes=160,
                    ai_summary="HF one-liner.",
                    code_url=CODE,
                ),
                paper("2610.00002", abstract="Only the first sentence is used. The rest is dropped."),
            ]
        }
    )
    client = client_with(make_client, hf)
    collect(client)
    cards = {p["arxiv_id"]: p for p in client.get("/api/papers").json()["papers"]}

    full = cards["2610.00001"]
    assert (full["title"], full["upvotes"], full["organization"]) == ("With HF summary", 160, "Nanjing University")
    assert full["summary_en"] == "HF one-liner."
    assert (full["has_code"], full["code_url"]) == (True, CODE)

    plain = cards["2610.00002"]
    assert plain["summary_en"] == "Only the first sentence is used."
    assert plain["has_code"] is False and plain["organization"] == ""


def test_cards_sorted_by_upvotes_then_registered_code(make_client):
    hf = FakeHF(
        {
            FRI: [
                paper("2610.00001", upvotes=5),
                paper("2610.00002", upvotes=9),
                paper("2610.00003", upvotes=5, code_url=CODE),
                paper("2610.00004", upvotes=1, code_url=CODE),
            ]
        }
    )
    client = client_with(make_client, hf)
    collect(client)
    ids = [p["arxiv_id"] for p in client.get("/api/papers").json()["papers"]]
    assert ids == ["2610.00002", "2610.00003", "2610.00001", "2610.00004"]


def test_every_paper_of_the_day_is_kept_beyond_fifty(make_client):
    client = client_with(make_client, FakeHF({FRI: [paper(f"2610.{n:05d}", upvotes=n) for n in range(84)]}))
    collect(client)
    listing = client.get("/api/papers").json()
    assert listing["count"] == 84 == len(listing["papers"])


def test_newest_day_is_marked_recent_only_when_it_is_not_today(make_client):
    client = client_with(make_client, FakeHF({FRI: [paper("2610.00001")]}))
    collect(client)
    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_today] = lambda: date(2026, 10, 4)  # a Sunday
    assert client.get("/api/papers").json()["recent"] is True
    client.app.dependency_overrides[get_today] = lambda: FRI
    assert client.get("/api/papers").json()["recent"] is False


def test_recollecting_updates_upvotes_without_duplicating(make_client):
    hf = FakeHF({FRI: [paper("2610.00001", upvotes=3)]})
    client = client_with(make_client, hf)
    collect(client)
    hf.days[FRI] = [paper("2610.00001", upvotes=7), paper("2610.00002")]
    collect(client)
    papers = client.get("/api/papers").json()["papers"]
    assert [(p["arxiv_id"], p["upvotes"]) for p in papers] == [("2610.00001", 7), ("2610.00002", 0)]


def test_failed_collection_reports_error_and_keeps_the_previous_list(make_client):
    hf = ScriptedHF({FRI: [paper("2610.00001")]})
    client = client_with(make_client, hf)
    collect(client)
    before = client.get("/api/papers").json()

    hf.fail = True
    state = collect(client)

    assert state["error"] and "HF is down" in state["error"]
    assert client.get("/api/papers").json() == before
    hf.fail = False
    assert collect(client)["error"] is None  # [다시] works


def test_collection_never_runs_twice_at_once(make_client):
    hf = ScriptedHF({FRI: [paper("2610.00001")]})
    hf.gate = threading.Event()
    client = client_with(make_client, hf)
    assert client.post("/api/collect").json()["running"] is True
    assert client.post("/api/collect").status_code == 202
    assert client.get("/api/collect").json()["running"] is True
    hf.gate.set()
    wait_idle(client)
    assert hf.calls == 1
    assert client.get("/api/papers").json()["count"] == 1


def test_collection_starts_by_itself_when_the_app_starts(make_client):
    client = client_with(make_client, FakeHF({FRI: [paper("2610.00001")]}))
    with client:  # runs the app lifespan, like uvicorn does
        wait_idle(client)
        assert client.get("/api/papers").json()["count"] == 1


def test_list_page_modules_are_served(make_client):
    client = make_client()
    assert client.get("/static/app.js").text.count("papers.js") == 1
    for name in ("papers.js", "papers.css"):
        assert client.get(f"/static/{name}").status_code == 200
