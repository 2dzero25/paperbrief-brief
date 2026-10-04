"""Seam: HTTP API through TestClient. Ticket #9: 원문 그림 1~2장과 캡션.

The parser fake writes hand-made MinerU output (tests/mineru_fixtures.py); the fake LLM records the 그림 후보 it is
given and picks ids; we look at what the report screen would get from `GET /api/papers/<id>/report`.
"""
import json
import shutil
from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from paperbrief.app import create_app
from paperbrief.config import STATIC_DIR, Settings
from paperbrief.db import connect
from paperbrief.llm import OpenAILLM, Report
from tests.fakes import FakeLLM, fake_boundaries
from tests.mineru_fixtures import MineruFixtureParser, block, jpeg
from tests.test_reports import REPORT, start, wait_for, wait_status

PID = "2610.00001"
BODY = (
    "# Paper\n\nWe reach 91.2 on Bench. Figure 1 shows the architecture. See Figure 2 and Figure 1 for details.\n\n"
    "Figure 1: Architecture overview.\n\nFigure 2 plots the scaling curve."
)


def make_report(make_client, pages, files, pick=("fig1",), markdown=BODY):
    parser = MineruFixtureParser(markdown, pages, files)
    llm = FakeLLM(Report(**{**REPORT.model_dump(), "figures": list(pick)}))
    client, _, llm, _ = start(make_client, parser=parser, llm=llm)
    client.post(f"/api/papers/{PID}/report")
    return client, llm, wait_status(client, PID, "완료")


def sent_to_llm(llm):
    (_, (_, figures)), = llm.calls
    return figures


def test_the_captioned_image_becomes_a_candidate_the_model_can_pick_and_the_app_serves(make_client):
    red = jpeg((200, 30, 30))
    pages = [[block("image", ["Figure 1: Architecture overview."], "images/page_2_image_0.jpg")]]
    client, llm, done = make_report(make_client, pages, {"images/page_2_image_0.jpg": red})

    (fig,) = sent_to_llm(llm)
    assert (fig.id, fig.caption) == ("fig1", "Figure 1: Architecture overview.")
    assert fig.mentions == ["Figure 1 shows the architecture.", "See Figure 2 and Figure 1 for details."]

    assert done["report"]["figures"] == ["fig1"]  # ids only in the stored report
    (shown,) = done["figures"]
    assert shown["id"] == "fig1" and shown["caption"] == "Figure 1: Architecture overview."
    (url,) = shown["images"]
    res = client.get(url)
    assert (res.status_code, res.headers["content-type"], res.content) == (200, "image/jpeg", red)


def test_panels_without_caption_right_before_the_captioned_one_are_one_figure_in_order(make_client):
    a, b, c = jpeg((255, 0, 0)), jpeg((0, 255, 0)), jpeg((0, 0, 255))
    pages = [[
        block("text", []),
        block("image", [], "images/page_3_image_0.jpg"),  # panel (a)
        block("chart", ["legend scrap"], "images/page_3_chart_1.jpg"),  # panel (b): no Figure caption
        block("image", ["Figure 1: Three panels."], "images/page_3_image_2.jpg"),  # caption on the last panel
    ]]
    files = {"images/page_3_image_0.jpg": a, "images/page_3_chart_1.jpg": b, "images/page_3_image_2.jpg": c}
    client, llm, done = make_report(make_client, pages, files)

    (fig,) = sent_to_llm(llm)
    assert fig.caption == "Figure 1: Three panels." and len(fig.images) == 3
    (shown,) = done["figures"]
    assert [client.get(u).content for u in shown["images"]] == [a, b, c]


def test_an_uncaptioned_image_before_a_table_or_on_another_page_is_not_a_panel(make_client):
    x, y, z = jpeg((1, 1, 1)), jpeg((2, 2, 2)), jpeg((3, 3, 3))
    pages = [
        [block("image", [], "images/page_1_image_0.jpg"), block("table", ["Table 1: Costs."], "images/page_1_table_1.jpg")],
        [block("image", ["Figure 1: Alone."], "images/page_2_image_0.jpg")],
    ]
    files = {"images/page_1_image_0.jpg": x, "images/page_1_table_1.jpg": y, "images/page_2_image_0.jpg": z}
    client, llm, done = make_report(make_client, pages, files)
    sent_to_llm(llm)
    assert [client.get(u).content for u in done["figures"][0]["images"]] == [z]


def test_chart_fake_leading_caption_table_missing_file_and_non_figure_caption_are_no_candidates(make_client):
    ok = jpeg((9, 9, 9))
    pages = [[
        block("chart", ["Attention Visualizationsp", "Figure 3: Heads."], "images/page_4_chart_0.jpg"),  # real, behind a fake
        block("table", ["Figure 4: A table that says Figure."], "images/page_5_table_1.jpg"),  # a table is no figure
        block("image", ["Figure 5: Ghost."], "images/page_6_image_0.jpg"),  # image file missing
        block("image", ["Fig. 6: not spelled Figure."], "images/page_7_image_0.jpg"),
        block("chart", ["Attention Visualizationsp"], "images/page_8_chart_0.jpg"),  # fake caption only
    ]]
    files = {name: ok for name in ("images/page_4_chart_0.jpg", "images/page_5_table_1.jpg",
                                   "images/page_7_image_0.jpg", "images/page_8_chart_0.jpg")}
    client, llm, done = make_report(make_client, pages, files)

    assert [(f.id, f.caption) for f in sent_to_llm(llm)] == [("fig1", "Figure 3: Heads.")]
    assert [f["caption"] for f in done["figures"]] == ["Figure 3: Heads."]


def test_zero_candidates_gives_an_empty_figure_list(make_client):
    pages = [[block("table", ["Table 1: Costs."], "images/page_1_table_0.jpg")]]
    client, llm, done = make_report(make_client, pages, {"images/page_1_table_0.jpg": jpeg((5, 5, 5))}, pick=())
    assert sent_to_llm(llm) == [] and done["report"]["figures"] == [] and done["figures"] == []


def test_a_parser_that_wrote_no_structured_content_gives_no_candidates(make_client):
    client, _, llm, _ = start(make_client, llm=FakeLLM(REPORT))  # the plain FakeParser writes no MinerU folder
    client.post(f"/api/papers/{PID}/report")
    done = wait_status(client, PID, "완료")
    assert sent_to_llm(llm) == [] and done["figures"] == []


def test_the_model_pick_is_kept_to_known_ids_without_repeats_and_two_at_most(make_client):
    img = jpeg((7, 7, 7))
    pages = [[block("image", [f"Figure {n}: F{n}."], f"images/page_{n}_image_0.jpg") for n in (1, 2, 3)]]
    files = {f"images/page_{n}_image_0.jpg": img for n in (1, 2, 3)}
    _, _, done = make_report(make_client, pages, files, pick=("fig9", "fig3", "fig3", "fig1", "fig2"))
    assert done["report"]["figures"] == ["fig3", "fig1"]
    assert [f["caption"] for f in done["figures"]] == ["Figure 3: F3.", "Figure 1: F1."]  # in the model's order


def test_malformed_structured_content_gives_no_figures_and_the_report_still_completes(make_client):
    junk = {"pages": [None, {"blocks": "x"}, {"blocks": [3, {"type": "image"}, {"type": "image", "captions": "Figure 1"}]}]}
    parser = MineruFixtureParser(BODY, [], {})
    client, _, llm, _ = start(make_client, parser=parser, llm=FakeLLM(REPORT))
    parser.pages = [[]]
    orig = parser.parse

    def parse_with_junk(pdf, out_dir):
        result = orig(pdf, out_dir)
        (out_dir / "structured_content.json").write_text(json.dumps(junk), encoding="utf-8")
        return result

    parser.parse = parse_with_junk  # type: ignore[method-assign]
    client.post(f"/api/papers/{PID}/report")
    done = wait_status(client, PID, "완료")
    assert sent_to_llm(llm) == [] and done["figures"] == []


def test_images_are_served_only_for_candidates_of_a_known_paper(make_client):
    ok = jpeg((4, 4, 4))
    pages = [[
        block("image", ["Figure 1: Escape."], "../../secret.jpg"),  # points out of the parsed folder
        block("image", ["Figure 2: Fine."], "images/page_1_image_0.jpg"),
    ]]
    client, llm, done = make_report(make_client, pages, {"images/page_1_image_0.jpg": ok}, pick=("fig1",))
    secret = client.app.state.settings.data_dir / "papers" / "secret.jpg"  # type: ignore[attr-defined]
    secret.write_bytes(b"SECRET")

    assert [c.caption for c in sent_to_llm(llm)] == ["Figure 2: Fine."]  # the escaping block is no candidate
    assert client.get(f"/api/papers/{PID}/figures/fig1/0").content == ok
    for bad in (
        f"/api/papers/{PID}/figures/fig1/1", f"/api/papers/{PID}/figures/fig1/-1", f"/api/papers/{PID}/figures/fig2/0",
        f"/api/papers/{PID}/figures/..%2F..%2Fsecret.jpg/0", f"/api/papers/{PID}/figures/images%2Fpage_1_image_0.jpg/0",
        "/api/papers/9999.99999/figures/fig1/0", "/api/papers/..%2Fpapers/figures/fig1/0",
    ):
        assert client.get(bad).status_code == 404, bad


def test_a_report_stored_before_figures_existed_still_opens_with_no_figures(make_client):
    old = REPORT.model_dump(exclude={"figures"})
    client, _, _, _ = start(make_client)
    with closing(connect(client.app.state.settings)) as db, db:  # type: ignore[attr-defined]
        db.execute("INSERT INTO reports (arxiv_id, status, report_json, created_at, updated_at) VALUES (?, '완료', ?, '', '')",
                   (PID, json.dumps(old)))
    state = client.get(f"/api/papers/{PID}/report").json()
    assert state["status"] == "완료" and state["figures"] == [] and state["report"]["hook"] == REPORT.hook


def figure_urls(client):
    return client.get(f"/api/papers/{PID}/report").json()["figures"][0]["images"]


def test_figures_are_still_served_after_the_data_dir_is_moved(make_client, tmp_path):
    red = jpeg((200, 30, 30))
    pages = [[block("image", ["Figure 1: Architecture overview."], "images/page_2_image_0.jpg")]]
    client, _, _ = make_report(make_client, pages, {"images/page_2_image_0.jpg": red})
    old_dir = client.app.state.settings.data_dir  # type: ignore[attr-defined]
    new_dir = tmp_path / "moved" / "PaperBrief"
    new_dir.parent.mkdir()
    shutil.move(old_dir, new_dir)

    moved = TestClient(create_app(Settings(data_dir=new_dir), fake_boundaries()))

    (url,) = figure_urls(moved)
    res = moved.get(url)
    assert (res.status_code, res.content) == (200, red)


def test_a_parse_result_saved_with_absolute_paths_by_an_older_version_still_loads(make_client):
    green = jpeg((30, 200, 30))
    pages = [[block("image", ["Figure 1: Architecture overview."], "images/page_2_image_0.jpg")]]
    client, _, _ = make_report(make_client, pages, {"images/page_2_image_0.jpg": green})
    parsed = client.app.state.settings.data_dir / "papers" / PID / "parsed"  # type: ignore[attr-defined]
    saved = json.loads((parsed / "parse_result.json").read_text(encoding="utf-8"))
    for f in saved["figures"]:
        f["images"] = [str((parsed / i).resolve()) for i in f["images"]]  # the old format
    (parsed / "parse_result.json").write_text(json.dumps(saved), encoding="utf-8")

    (url,) = figure_urls(client)

    assert client.get(url).content == green


def test_offline_mode_report_has_a_two_panel_figure_and_a_chart_figure(make_client):
    from paperbrief import boundaries

    client = make_client(boundaries.offline(Settings()), offline=True)
    client.post("/api/collect")
    wait_for(lambda: not client.get("/api/collect").json()["running"])
    arxiv_id = client.get("/api/papers").json()["papers"][0]["arxiv_id"]
    client.post(f"/api/papers/{arxiv_id}/report")
    done = wait_status(client, arxiv_id, "완료")
    assert [(f["caption"], len(f["images"])) for f in done["figures"]] == [
        ("Figure 1. Overview of OneStreamer.", 2),
        ("Figure 2. StreamBench accuracy by chunk size.", 1),
    ]
    assert all(client.get(u).headers["content-type"] == "image/jpeg" for f in done["figures"] for u in f["images"])


def test_the_report_screen_has_a_figure_section_with_a_no_figure_note():
    """Smoke only (no JS test runner here): the module exists, is loaded, and has the empty note. Rendering is checked in a browser."""
    assert "그림 없음" in (STATIC_DIR / "figures.js").read_text(encoding="utf-8")
    assert 'import "./figures.js"' in (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def test_the_real_llm_client_sends_figure_ids_captions_and_mentions_but_no_image(make_client):
    sent: list[dict] = []

    def openai(request: httpx.Request) -> httpx.Response:  # stands in for api.openai.com
        sent.append(json.loads(request.content))
        report = Report(**{**REPORT.model_dump(), "figures": ["fig1"]})
        output = {
            "type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "annotations": [], "text": report.model_dump_json()}],
        }  # fmt: skip
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "created_at": 0, "model": "test-model", "status": "completed",
            "output": [output], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })  # fmt: skip

    settings = Settings(openai_api_key="sk-test", openai_model="test-model")
    llm = OpenAILLM(settings, httpx.Client(transport=httpx.MockTransport(openai)))
    pages = [[block("image", ["Figure 1: Architecture overview."], "images/page_2_image_0.jpg"),
              block("image", ["Figure 2: Scaling."], "images/page_3_image_0.jpg")]]
    files = {"images/page_2_image_0.jpg": jpeg((1, 2, 3)), "images/page_3_image_0.jpg": jpeg((3, 2, 1))}
    client, _, _, _ = start(make_client, parser=MineruFixtureParser(BODY, pages, files), llm=llm)  # type: ignore[arg-type]
    client.post(f"/api/papers/{PID}/report")
    done = wait_status(client, PID, "완료")

    (request,) = [r for r in sent if r["model"] == "test-model"]  # the collection also sent its KO summary request
    text = request["input"]
    for line in ("fig1", "Figure 1: Architecture overview.", "Figure 1 shows the architecture.", "fig2", "Figure 2: Scaling."):
        assert line in text
    assert "images/" not in text and ".jpg" not in text and "base64" not in text  # no file, no image
    assert "figures" in request["text"]["format"]["schema"]["properties"]
    assert "1-2" in request["instructions"] and "figures" in request["instructions"]
    assert done["report"]["figures"] == ["fig1"]


def test_html_entities_in_a_mineru_caption_are_shown_as_the_characters(make_client):
    """A real run gave `&lt;/Observe&gt;` for `</Observe>`; the page escapes text itself, so it would show the entity."""
    caption = "Figure 1: Tags &lt;/Observe&gt; and &lt;/Silence&gt; mark events."
    pages = [[block("image", [caption], "images/page_2_image_0.jpg")]]
    client, llm, done = make_report(make_client, pages, {"images/page_2_image_0.jpg": jpeg((1, 2, 3))})

    assert sent_to_llm(llm)[0].caption == "Figure 1: Tags </Observe> and </Silence> mark events."
    assert done["figures"][0]["caption"] == "Figure 1: Tags </Observe> and </Silence> mark events."
