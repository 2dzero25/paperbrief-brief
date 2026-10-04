"""Seam: HTTP API through TestClient, with the real arXiv client reading a recorded arXiv response.

arxiv_id_list.xml: real `export.arxiv.org/api/query?id_list=...` Atom response for the 84 papers of 2026-10-02
in hf_daily_page0.json (summaries, authors and comments trimmed).
"""
import json
from pathlib import Path

import httpx

from paperbrief.arxiv import HttpArxiv
from paperbrief.boundaries import Boundaries
from paperbrief.hf import HFPaper
from tests.fakes import FakeHF, FakeLLM, FakeParser
from tests.test_collect_list import FRI, collect, paper

FIXTURES = Path(__file__).parent / "fixtures"
RECORDING = (FIXTURES / "arxiv_id_list.xml").read_text(encoding="utf-8")
DAY_IDS = [
    i["paper"]["id"]
    for i in json.loads((FIXTURES / "hf_daily_page0.json").read_text(encoding="utf-8"))
    if i["paper"]["submittedOnDailyAt"].startswith("2026-10-02")
]


class Clock:
    """Fake time: `sleep` only moves the clock, so rate-limit waits are observable and instant."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def day_of_recording() -> list[HFPaper]:
    return [paper(i) for i in DAY_IDS]


def client_over_arxiv(make_client, handler, contact="me@example.test", clock=None, hf=None):
    clock = clock or Clock()
    arxiv = HttpArxiv(httpx.Client(transport=httpx.MockTransport(handler)), contact, clock=clock, sleep=clock.sleep)
    hf = hf or FakeHF({FRI: day_of_recording()})
    return make_client(Boundaries(hf, arxiv, FakeLLM(), FakeParser()))


def serve_recording(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=RECORDING)

    return handler


def test_recorded_response_gives_every_paper_its_primary_and_all_categories(make_client):
    seen: list[httpx.Request] = []
    client = client_over_arxiv(make_client, serve_recording(seen))
    assert collect(client)["error"] is None

    cards = {p["arxiv_id"]: p for p in client.get("/api/papers").json()["papers"]}
    assert len(cards) == 84 and all(c["primary_category"] for c in cards.values())
    # the recording's first entry: primary cs.CV, listed with cs.MM, cs.SD, eess.AS (arXiv id has a version suffix)
    assert cards["2609.34381"]["primary_category"] == "cs.CV"
    assert cards["2609.34381"]["categories"] == ["cs.CV", "cs.MM", "cs.SD", "eess.AS"]
    assert any(len(c["categories"]) > 1 and c["categories"][0] == c["primary_category"] for c in cards.values())


def test_one_id_list_request_per_collection_with_contact_in_user_agent_and_no_rss(make_client):
    seen: list[httpx.Request] = []
    client = client_over_arxiv(make_client, serve_recording(seen), contact="me@example.test")
    collect(client)

    assert len(seen) == 1
    req = seen[0]
    assert (req.url.host, req.url.path) == ("export.arxiv.org", "/api/query")
    assert req.url.params["id_list"].split(",") == DAY_IDS
    assert int(req.url.params["max_results"]) >= len(DAY_IDS)
    assert "me@example.test" in req.headers["user-agent"]
    assert "rss" not in str(req.url).lower()


def test_requests_are_at_least_three_seconds_apart(make_client):
    clock = Clock()
    seen: list[httpx.Request] = []
    client = client_over_arxiv(make_client, serve_recording(seen), clock=clock)
    collect(client)
    assert clock.slept == []  # the first request goes out at once

    clock.now += 1  # a second collection one second later waits out the rest of the 3 s
    collect(client)
    assert len(seen) == 2 and clock.slept == [2.0]

    clock.now += 10
    collect(client)
    assert clock.slept == [2.0]  # long enough ago: no wait


def test_arxiv_failure_still_saves_the_papers_without_a_category(make_client):
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = client_over_arxiv(make_client, down)
    assert collect(client)["error"] is None  # a partial failure, not a failed collection

    listing = client.get("/api/papers").json()
    assert listing["count"] == 84
    assert all(c["primary_category"] == "" and c["categories"] == [] for c in listing["papers"])


def test_a_failed_lookup_keeps_categories_saved_earlier(make_client):
    ok = True

    def flaky(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=RECORDING) if ok else httpx.Response(500)

    client = client_over_arxiv(make_client, flaky)
    collect(client)
    ok = False
    collect(client)
    assert client.get("/api/papers").json()["papers"][0]["primary_category"] != ""


def test_papers_missing_from_the_response_stay_without_a_category(make_client):
    hf = FakeHF({FRI: [paper("2609.34381"), paper("9999.99999")]})
    client = client_over_arxiv(make_client, serve_recording([]), hf=hf)
    collect(client)
    cards = {p["arxiv_id"]: p for p in client.get("/api/papers").json()["papers"]}
    assert cards["2609.34381"]["primary_category"] == "cs.CV"
    assert cards["9999.99999"]["primary_category"] == ""
