"""Seam: HTTP API through TestClient. Ticket #3: the app serves an empty PaperBrief screen."""


def test_root_serves_empty_screen_with_openai_notice(make_client):
    res = make_client().get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "PaperBrief" in res.text
    assert "본문은 OpenAI API로 전송됨" in res.text


def test_vanilla_js_is_served(make_client):
    res = make_client().get("/static/app.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
