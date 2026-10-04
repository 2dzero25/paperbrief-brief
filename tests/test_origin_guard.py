"""Seam: HTTP API. A page the user visits must not be able to start work on this local app (CSRF, DNS rebinding)."""
import pytest

POST = "/api/papers/2610.00001/report"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://127.0.0.1:9999", "http://evil.example:8765", "null"])
def test_a_state_changing_request_from_another_origin_is_refused_and_starts_nothing(make_client, origin):
    client = make_client()
    res = client.post("/api/collect", headers={"Origin": origin})
    assert res.status_code == 403
    assert client.post(POST, headers={"Origin": origin}).status_code == 403
    assert client.get("/api/collect").json()["running"] is False  # the refused POST started nothing


def test_a_cross_site_fetch_without_an_origin_header_is_refused(make_client):
    res = make_client().post("/api/collect", headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "http://localhost:8765"])
def test_the_app_own_origin_may_post(make_client, origin):
    res = make_client().post("/api/collect", headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})
    assert res.status_code == 202


def test_requests_without_origin_headers_and_reads_from_other_origins_still_work(make_client):
    client = make_client()
    assert client.post("/api/collect").status_code == 202  # curl, TestClient
    assert client.get("/api/papers", headers={"Origin": "https://evil.example"}).status_code == 200  # response is unreadable to them
