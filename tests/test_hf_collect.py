"""Seam: HTTP API through TestClient, with the real HF client reading recorded HF responses (tests/fixtures).

hf_daily_page0/1.json: real `daily_papers?limit=100` pages (2026-10-02 has 84 papers, then 2026-10-01), trimmed.
hf_weekend_page*.json: hand-made, one 발표일 (Fri) continuing onto a second page, then Thursday.
"""
import json
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from paperbrief.boundaries import Boundaries
from paperbrief.hf import HttpHF, fixture_handler
from tests.fakes import FakeArxiv, FakeLLM, FakeParser
from tests.test_collect_list import collect

FIXTURES = Path(__file__).parent / "fixtures"


def page(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def client_over(make_client: Callable[..., TestClient], pages: list[list[dict]]) -> tuple[TestClient, list[httpx.URL]]:
    """App whose real HF client talks to the recorded pages; also returns every URL it requested."""
    seen: list[httpx.URL] = []
    serve = fixture_handler(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return serve(request)

    hf = HttpHF(httpx.Client(transport=httpx.MockTransport(handler)))
    return make_client(Boundaries(hf, FakeArxiv(), FakeLLM(), FakeParser())), seen


def test_real_recording_all_84_papers_of_the_latest_day_from_one_request(make_client):
    client, seen = client_over(make_client, [page("hf_daily_page0.json"), page("hf_daily_page1.json")])
    assert collect(client)["error"] is None

    listing = client.get("/api/papers").json()
    assert listing["day"] == "2026-10-02" and listing["count"] == 84
    # the 16 papers of 10-01 on the same page are not saved
    assert len(seen) == 1
    assert (seen[0].path, seen[0].params["limit"], "date" in seen[0].params) == ("/api/daily_papers", "100", False)


def test_real_recording_fields_are_saved_and_thumbnail_is_not(make_client):
    client, _ = client_over(make_client, [page("hf_daily_page0.json")])
    collect(client)
    listing = client.get("/api/papers")
    assert "thumbnail" not in listing.text and "cdn-thumbnails" not in listing.text

    raw = {i["paper"]["id"]: i["paper"] for i in page("hf_daily_page0.json")}
    cards = listing.json()["papers"]
    with_code = next(c for c in cards if raw[c["arxiv_id"]].get("githubRepo"))
    assert with_code["code_url"] == raw[with_code["arxiv_id"]]["githubRepo"] and with_code["has_code"]
    with_org = next(c for c in cards if raw[c["arxiv_id"]].get("organization"))
    assert with_org["organization"] == raw[with_org["arxiv_id"]]["organization"]["fullname"]
    assert [c["upvotes"] for c in cards] == sorted((c["upvotes"] for c in cards), reverse=True)


def test_a_day_spanning_pages_follows_link_next_until_another_day_appears(make_client):
    first = page("hf_daily_page0.json")
    # real 10-02 papers split over three pages, the third page holds the 10-01 papers, so the fourth must not be fetched
    pages = [first[:40], first[40:84], first[84:], page("hf_daily_page1.json")]
    client, seen = client_over(make_client, pages)
    collect(client)

    assert client.get("/api/papers").json()["count"] == 84
    assert [u.params.get("p", "0") for u in seen] == ["0", "1", "2"]


def test_day_boundary_exactly_at_a_page_end_still_stops_at_the_next_page(make_client):
    client, seen = client_over(make_client, [page("hf_weekend_page0.json"), page("hf_weekend_page1.json")])
    collect(client)

    papers = client.get("/api/papers").json()["papers"]
    assert [p["arxiv_id"] for p in papers] == ["2610.10002", "2610.10001", "2610.10004", "2610.10003"]
    assert len(seen) == 2


def test_hand_made_fields_summary_fallback_and_organization(make_client):
    client, _ = client_over(make_client, [page("hf_weekend_page0.json"), page("hf_weekend_page1.json")])
    collect(client)
    cards = {p["arxiv_id"]: p for p in client.get("/api/papers").json()["papers"]}
    assert cards["2610.10001"]["summary_en"] == "Fri A first sentence."
    assert cards["2610.10001"]["organization"] == "ACME Research"
    assert cards["2610.10002"]["summary_en"] == "HF says B in one line."
    assert cards["2610.10003"]["organization"] == ""


def test_http_failure_is_a_failed_collection_and_keeps_the_list(make_client):
    pages = [page("hf_weekend_page0.json"), page("hf_weekend_page1.json")]
    client, _ = client_over(make_client, pages)
    collect(client)
    before = client.get("/api/papers").json()

    pages.clear()  # the fixture server now answers 404 for every page
    state = collect(client)
    assert state["error"]
    assert client.get("/api/papers").json() == before
