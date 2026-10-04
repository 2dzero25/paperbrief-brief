"""Seam: HTTP API through TestClient (fake HF and arXiv). Ticket #5: 분야·코드 필터와 날짜 넘기기."""
from datetime import date

from fastapi import FastAPI

from paperbrief.boundaries import Boundaries
from paperbrief.routes.papers import get_today
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser
from tests.test_collect_list import CODE, FRI, collect, paper

WED = date(2026, 9, 30)
SUN = date(2026, 10, 4)

CATS = {
    "2610.00001": ("cs.CL", ["cs.CL", "cs.LG"]),
    "2610.00002": ("cs.CV", ["cs.CV"]),
    "2610.00003": ("cs.LG", ["cs.LG", "cs.CL"]),  # crosses over into cs.CL
    "2610.00004": ("cs.CV", ["cs.CV", "cs.AI"]),
    "2610.00005": ("cs.CL", ["cs.CL"]),
}


def day_papers():
    return [
        paper("2610.00001", upvotes=10, code_url=CODE),
        paper("2610.00002", upvotes=30),
        paper("2610.00003", upvotes=20, code_url=CODE),
        paper("2610.00004", upvotes=5),
        paper("2610.00005", upvotes=8),
        paper("2610.00006", upvotes=1),  # arXiv knows nothing about it: no category
    ]


def make(make_client, hf=None, arxiv=None):
    boundaries = Boundaries(hf or FakeHF({FRI: day_papers()}), arxiv or FakeArxiv(CATS), FakeLLM(), FakeParser())
    client = make_client(boundaries)
    collect(client)
    return client


def ids(client, query=""):
    return [p["arxiv_id"] for p in client.get("/api/papers" + query).json()["papers"]]


def test_chips_are_the_categories_present_that_day_by_count(make_client):
    client = make(make_client)
    chips = client.get("/api/papers").json()["categories"]
    # cs.CL x3 (00001, 00003, 00005), cs.LG x2, cs.CV x2, cs.AI x1; ties alphabetical
    assert chips == [
        {"category": "cs.CL", "count": 3},
        {"category": "cs.CV", "count": 2},
        {"category": "cs.LG", "count": 2},
        {"category": "cs.AI", "count": 1},
    ]


def test_a_card_carries_its_primary_category(make_client):
    client = make(make_client)
    card = next(p for p in client.get("/api/papers").json()["papers"] if p["arxiv_id"] == "2610.00003")
    assert card["primary_category"] == "cs.LG"


def test_choosing_a_category_shows_every_paper_that_has_it_in_any_slot_keeping_the_sort(make_client):
    client = make(make_client)
    # 00003 is primary cs.LG but also lists cs.CL; upvotes 20 > 10 > 8
    assert ids(client, "?category=cs.CL") == ["2610.00003", "2610.00001", "2610.00005"]
    assert ids(client, "?category=cs.AI") == ["2610.00004"]  # a secondary slot only
    assert ids(client, "?category=cs.RO") == []


def test_papers_without_a_category_only_show_under_all(make_client):
    client = make(make_client)
    assert "2610.00006" in ids(client)
    assert all("2610.00006" not in ids(client, f"?category={c}") for c in ("cs.CL", "cs.CV", "cs.LG", "cs.AI"))


def test_code_toggle_keeps_only_registered_code_and_combines_with_a_category(make_client):
    client = make(make_client)
    assert ids(client, "?code=1") == ["2610.00003", "2610.00001"]
    assert ids(client, "?category=cs.CL&code=1") == ["2610.00003", "2610.00001"]
    assert ids(client, "?category=cs.CV&code=1") == []
    assert len(ids(client, "?code=0")) == 6


def test_count_follows_the_filters_while_chips_describe_the_whole_day(make_client):
    client = make(make_client)
    everything = client.get("/api/papers").json()
    filtered = client.get("/api/papers?category=cs.CV&code=0").json()
    assert (everything["count"], filtered["count"]) == (6, 2)
    assert filtered["categories"] == everything["categories"]
    assert client.get("/api/papers?category=cs.RO").json()["count"] == 0


def test_arrows_move_between_saved_days_only(make_client):
    hf = FakeHF({WED: [paper("2610.10001", WED)]})
    client = make(make_client, hf=hf, arxiv=FakeArxiv({}))
    first = client.get("/api/papers").json()
    assert (first["day"], first["prev_day"], first["next_day"]) == ("2026-09-30", None, None)

    hf.days[FRI] = [paper("2610.10002", FRI)]  # THU is never collected: no backfill
    collect(client)

    latest = client.get("/api/papers").json()
    assert (latest["day"], latest["prev_day"], latest["next_day"]) == ("2026-10-02", "2026-09-30", None)
    older = client.get("/api/papers?day=2026-09-30").json()
    assert (older["day"], older["prev_day"], older["next_day"]) == ("2026-09-30", None, "2026-10-02")
    assert [p["arxiv_id"] for p in older["papers"]] == ["2610.10001"]


def test_an_older_day_is_never_marked_recent_and_filters_apply_to_it(make_client):
    hf = FakeHF({WED: [paper("2610.10001", WED, code_url=CODE), paper("2610.10002", WED)]})
    client = make(make_client, hf=hf, arxiv=FakeArxiv({"2610.10001": ("cs.CL", ["cs.CL"])}))
    hf.days[FRI] = [paper("2610.10003", FRI)]
    collect(client)
    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_today] = lambda: SUN
    assert client.get("/api/papers").json()["recent"] is True
    older = client.get("/api/papers?day=2026-09-30&code=1").json()
    assert older["recent"] is False and older["count"] == 1
    assert older["categories"] == [{"category": "cs.CL", "count": 1}]


def test_unsaved_day_is_not_found(make_client):
    client = make(make_client)
    assert client.get("/api/papers?day=2026-10-01").status_code == 404


def test_page_modules_for_filters_are_served(make_client):
    client = make_client()
    assert client.get("/static/app.js").text.count("filters.js") == 1
    assert client.get("/static/filters.js").status_code == 200
