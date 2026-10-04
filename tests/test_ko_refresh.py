"""Seam: HTTP API through TestClient. Ticket #6: KO 한 줄 요약 + 최근 3개 발표일 갱신 (fake HF/arXiv/LLM, recorded HF dates)."""
import json
from datetime import date
from pathlib import Path

import httpx

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.hf import API, HttpHF, fixture_handler
from paperbrief.llm import OpenAILLM
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser
from tests.test_collect_list import FRI, THU, collect, paper
from tests.test_hf_collect import page

MON = date(2026, 10, 5)
WED = date(2026, 9, 30)
TUE = date(2026, 9, 29)


class ScriptedLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.fail = False
        self.skip: set[str] = set()  # ids the model leaves out of its answer

    def summarize_ko(self, papers):
        if self.fail:
            self.ko_requests.append(papers)
            raise RuntimeError("OpenAI is down")
        return {i: s for i, s in super().summarize_ko(papers).items() if i not in self.skip}

    def ko_calls(self) -> list[list[tuple[str, str, str]]]:
        return self.ko_requests


def make(make_client, hf, llm=None, arxiv=None):
    llm = llm or ScriptedLLM()
    client = make_client(Boundaries(hf, arxiv or FakeArxiv(), llm, FakeParser()))
    collect(client)
    return client, llm


def cards(client, query=""):
    return {p["arxiv_id"]: p for p in client.get("/api/papers" + query).json()["papers"]}


def test_ko_summaries_come_from_one_call_per_new_day_with_title_and_abstract(make_client):
    hf = FakeHF({FRI: [paper("2610.00001", abstract="Abs one."), paper("2610.00002")]})
    client, llm = make(make_client, hf)

    assert [sorted(call) for call in llm.ko_calls()] == [
        [("2610.00001", "Title 2610.00001", "Abs one."), ("2610.00002", "Title 2610.00002", "First sentence. Second sentence.")]
    ]
    assert cards(client)["2610.00001"]["summary_ko"] == "KO Title 2610.00001"

    collect(client)  # same day again: everything already has a KO summary
    assert len(llm.ko_calls()) == 1


def test_ko_failure_keeps_the_papers_and_the_next_collection_fills_them(make_client):
    llm = ScriptedLLM()
    llm.fail = True
    client, _ = make(make_client, FakeHF({FRI: [paper("2610.00001"), paper("2610.00002")]}), llm)
    assert client.get("/api/collect").json()["error"] is None
    assert {i: c["summary_ko"] for i, c in cards(client).items()} == {"2610.00001": "", "2610.00002": ""}

    llm.fail = False
    llm.skip = {"2610.00002"}  # the model forgets one paper
    collect(client)
    assert {i: c["summary_ko"] for i, c in cards(client).items()} == {"2610.00001": "KO Title 2610.00001", "2610.00002": ""}

    llm.skip = set()
    collect(client)
    assert [i for i, _, _ in llm.ko_calls()[-1]] == ["2610.00002"]  # only the missing one is asked again
    assert cards(client)["2610.00002"]["summary_ko"] == "KO Title 2610.00002"


def test_ko_is_filled_for_the_last_three_saved_days_not_older_ones(make_client):
    hf = FakeHF()
    llm = ScriptedLLM()
    llm.fail = True  # nothing gets summarized while the four days are first saved
    client = make_client(Boundaries(hf, FakeArxiv(), llm, FakeParser()))
    for n, day in enumerate((TUE, WED, THU, FRI), 1):
        hf.days[day] = [paper(f"2610.0000{n}", day)]
        collect(client)
    llm.fail = False
    llm.ko_requests.clear()
    collect(client)

    assert sorted(i for call in llm.ko_calls() for i, _, _ in call) == ["2610.00002", "2610.00003", "2610.00004"]
    assert len(llm.ko_calls()) == 3  # one call per 발표일
    assert cards(client, "?day=2026-09-29")["2610.00001"]["summary_ko"] == ""


class RecordingHF(FakeHF):
    def __init__(self, days=None) -> None:
        super().__init__(days)
        self.asked: list[date] = []

    def day(self, day):
        self.asked.append(day)
        return super().day(day)


def test_refresh_updates_upvotes_and_ai_summary_of_the_last_three_saved_days_only(make_client):
    hf = RecordingHF()
    llm = ScriptedLLM()
    client = make_client(Boundaries(hf, FakeArxiv(), llm, FakeParser()))
    for n, day in enumerate((TUE, WED, THU, FRI), 1):
        hf.days[day] = [paper(f"2610.0000{n}", day, upvotes=1)]
        collect(client)
    hf.asked.clear()

    for n, day in enumerate((TUE, WED, THU, FRI), 1):  # HF moves on: more upvotes, and a late ai_summary on two papers
        hf.days[day] = [paper(f"2610.0000{n}", day, upvotes=10 * n, ai_summary="Fresh EN." if n in (2, 4) else "")]
    llm.ko_requests.clear()
    collect(client)

    def card_of(arxiv_id, day):
        return cards(client, f"?day={day}")[arxiv_id]

    assert [card_of("2610.00004", "2026-10-02")["upvotes"], card_of("2610.00003", "2026-10-01")["upvotes"]] == [40, 30]
    assert card_of("2610.00002", "2026-09-30")["upvotes"] == 20
    assert card_of("2610.00001", "2026-09-29")["upvotes"] == 1  # the 4th saved day is left alone
    assert sorted(hf.asked) == [WED, THU]  # the latest day came with latest_day(); no extra request for it
    assert card_of("2610.00004", "2026-10-02")["summary_en"] == "Fresh EN."
    assert card_of("2610.00002", "2026-09-30")["summary_en"] == "Fresh EN."
    assert card_of("2610.00004", "2026-10-02")["summary_ko"] == "KO Title 2610.00004"  # KO is never regenerated
    assert llm.ko_requests == []


def test_refresh_follows_saved_days_not_calendar_days_and_survives_weekend_and_future_dates(make_client):
    hf = RecordingHF({THU: [paper("2610.00001", THU)]})
    client = make_client(Boundaries(hf, FakeArxiv(), ScriptedLLM(), FakeParser()))
    collect(client)
    hf.days[FRI] = [paper("2610.00002")]
    collect(client)
    hf.days[MON] = [paper("2610.00003", MON)]
    hf.asked.clear()
    collect(client)

    assert sorted(hf.asked) == [THU, FRI]  # Sat and Sun were never 발표일
    assert client.get("/api/papers").json()["day"] == "2026-10-05"


class FlakyArxiv(FakeArxiv):
    down = True

    def categories(self, arxiv_ids):
        if self.down:
            raise ConnectionError("arXiv is down")
        return super().categories(arxiv_ids)


def test_missing_categories_are_filled_on_a_later_collection_within_the_last_three_days(make_client):
    arxiv = FlakyArxiv({f"2610.0000{n}": ("cs.CL", ["cs.CL"]) for n in range(1, 5)})
    hf = FakeHF()
    client = make_client(Boundaries(hf, arxiv, ScriptedLLM(), FakeParser()))
    for n, day in enumerate((TUE, WED, THU, FRI), 1):
        hf.days[day] = [paper(f"2610.0000{n}", day)]
        collect(client)
    assert all(not c["categories"] for c in cards(client).values())

    arxiv.down = False
    collect(client)
    assert cards(client, "?day=2026-10-01")["2610.00003"]["categories"] == ["cs.CL"]
    assert cards(client, "?day=2026-09-30")["2610.00002"]["categories"] == ["cs.CL"]
    assert cards(client, "?day=2026-09-29")["2610.00001"]["categories"] == []  # older than the last 3 saved days


def test_hf_failure_while_refreshing_is_a_failed_collection_but_what_was_saved_stays(make_client):
    hf = RecordingHF({THU: [paper("2610.00001", THU)]})
    client = make_client(Boundaries(hf, FakeArxiv(), ScriptedLLM(), FakeParser()))
    collect(client)
    hf.days[FRI] = [paper("2610.00002")]

    def down(day):
        raise ConnectionError("HF is down")

    hf.day = down  # type: ignore[method-assign]
    assert collect(client)["error"]
    listing = client.get("/api/papers").json()
    assert (listing["day"], listing["prev_day"]) == ("2026-10-02", "2026-10-01")
    assert cards(client)["2610.00002"]["summary_ko"] == "KO Title 2610.00002"


DATES = json.loads((Path(__file__).parent / "fixtures" / "hf_dates.json").read_text(encoding="utf-8"))


def two_saved_days(make_client, thursday: httpx.Response):
    """Thursday is saved first, then Friday arrives as the latest 발표일 and the next collection refreshes Thursday.

    `date=D` is answered like huggingface.co: `thursday` for 10-01 (with a rel=next link to an empty `p=1`), 400/0 rows otherwise.
    """
    thu_only = [[item for item in page("hf_weekend_page1.json") if item["paper"]["id"] != "2610.10004"]]
    latest_pages = list(thu_only)
    serve = fixture_handler(latest_pages)
    asked: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "date" not in request.url.params:
            return serve(request)
        asked.append(request.url)
        if request.url.params.get("p", "0") != "0":
            return httpx.Response(200, json=[])
        if thursday.status_code == 200 and json.loads(thursday.content):  # the recorded 0-row and 400 answers carry no link
            thursday.headers["Link"] = f'<{API}?limit=100&date=2026-10-01&p=1>; rel="next"'
        return thursday

    hf = HttpHF(httpx.Client(transport=httpx.MockTransport(handler)))
    client = make_client(Boundaries(hf, FakeArxiv(), ScriptedLLM(), FakeParser()))
    collect(client)
    latest_pages[:] = [page("hf_weekend_page0.json"), page("hf_weekend_page1.json")]  # HF has moved on to Friday
    collect(client)
    return client, asked


def test_real_hf_client_refreshes_a_saved_day_through_date(make_client):
    client, asked = two_saved_days(make_client, httpx.Response(200, json=DATES["2026-10-01"]))

    assert [(u.params["date"], u.params["limit"]) for u in asked] == [("2026-10-01", "100"), ("2026-10-01", "100")]  # page 0, empty page 1
    thursday = cards(client, "?day=2026-10-01")
    assert (thursday["2610.10005"]["upvotes"], thursday["2610.10006"]["upvotes"]) == (120, 80)
    assert thursday["2610.10006"]["summary_en"] == "HF now says F in one line."
    assert thursday["2610.10005"]["summary_ko"] == "KO Thu E"  # written when Thursday was first saved, not redone


def test_a_zero_row_weekend_style_answer_changes_nothing(make_client):
    client, asked = two_saved_days(make_client, httpx.Response(200, json=DATES["2026-10-03"]))

    assert len(asked) == 1
    assert client.get("/api/collect").json()["error"] is None
    thursday = cards(client, "?day=2026-10-01")
    assert (thursday["2610.10005"]["upvotes"], thursday["2610.10006"]["upvotes"]) == (99, 77)


def test_a_400_for_a_date_after_the_latest_changes_nothing_and_does_not_fail(make_client):
    client, _ = two_saved_days(make_client, httpx.Response(400, json=DATES["later_than_latest"]))

    assert client.get("/api/collect").json()["error"] is None
    assert cards(client, "?day=2026-10-01")["2610.10005"]["upvotes"] == 99
    assert client.get("/api/papers").json()["count"] == 4


def fake_openai(sent: list[dict], summaries: dict[str, str]):
    """Stands in for api.openai.com: answers every `responses.parse` call with these KO summaries."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        items = [{"arxiv_id": i, "summary": ko} for i, ko in summaries.items()]
        output = {
            "type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "annotations": [], "text": json.dumps({"items": items}, ensure_ascii=False)}],
        }  # fmt: skip
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "created_at": 0, "model": "m", "status": "completed",
            "output": [output], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })  # fmt: skip

    return handler


def test_the_real_llm_client_sends_one_structured_request_per_day_to_the_summary_model(make_client):
    sent: list[dict] = []
    ko = {"2610.00001": "첫째 논문 한 줄 요약", "2610.00002": "둘째 논문 한 줄 요약"}
    settings = Settings(openai_api_key="sk-test", openai_summary_model="summary-model", openai_model="report-model")
    llm = OpenAILLM(settings, httpx.Client(transport=httpx.MockTransport(fake_openai(sent, ko))))
    hf = FakeHF({FRI: [paper("2610.00001", abstract="Abs one."), paper("2610.00002")]})
    client = make_client(Boundaries(hf, FakeArxiv(), llm, FakeParser()))  # type: ignore[arg-type]
    collect(client)

    assert {i: c["summary_ko"] for i, c in cards(client).items()} == ko
    (request,) = sent
    assert request["model"] == "summary-model"
    assert request["text"]["format"]["type"] == "json_schema"
    assert "Title 2610.00001" in request["input"] and "Abs one." in request["input"] and "2610.00002" in request["input"]
    assert "Korean" in request["instructions"] and "one sentence" in request["instructions"]


def test_without_an_openai_key_the_collection_succeeds_and_nothing_is_sent(make_client):
    sent: list[dict] = []
    llm = OpenAILLM(Settings(openai_api_key=""), httpx.Client(transport=httpx.MockTransport(fake_openai(sent, {}))))
    client = make_client(Boundaries(FakeHF({FRI: [paper("2610.00001")]}), FakeArxiv(), llm, FakeParser()))  # type: ignore[arg-type]
    state = collect(client)

    assert state["error"] is None and sent == []
    (card,) = cards(client).values()
    assert card["summary_ko"] == "" and card["summary_en"] == "First sentence."


def test_an_openai_error_does_not_fail_the_collection(make_client):
    refuse = httpx.MockTransport(lambda request: httpx.Response(400, json={"error": {"message": "boom"}}))
    llm = OpenAILLM(Settings(openai_api_key="sk-test"), httpx.Client(transport=refuse))
    client = make_client(Boundaries(FakeHF({FRI: [paper("2610.00001")]}), FakeArxiv(), llm, FakeParser()))  # type: ignore[arg-type]

    assert collect(client)["error"] is None
    assert cards(client)["2610.00001"]["summary_ko"] == ""


def test_offline_mode_gives_every_card_a_canned_ko_summary(make_client):
    from paperbrief import boundaries

    client = make_client(boundaries.offline(Settings()), offline=True)
    collect(client)
    assert all(c["summary_ko"].startswith("(오프라인) ") for c in cards(client).values())


def test_ko_en_tab_module_is_served(make_client):
    client = make_client()
    assert client.get("/static/app.js").text.count("lang.js") == 1
    assert client.get("/static/lang.js").status_code == 200
