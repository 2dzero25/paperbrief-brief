"""Seam: HTTP API through TestClient. Ticket #7: 보고서 만들기 (PDF -> 파싱 -> 작성) with a single FIFO worker.

PDF download is faked at the httpx boundary (MockTransport), the parser and the LLM are recording fakes.
"""
import json
import threading
import time
from collections.abc import Callable
from datetime import date

import httpx
from fastapi.testclient import TestClient

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.hf import HFPaper
from paperbrief.llm import OpenAILLM, Report
from paperbrief.parser import FigureCandidate, ParseResult
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser

FRI = date(2026, 10, 2)
BODY = "# Paper body\n\nWe reach 91.2 on Bench. See Figure 1."
REPORT = Report(
    hook="Bench 91.2점으로 이전 SOTA를 넘음",
    method="방법 본문",
    results="결과 본문",
    difference="차이 본문",
    meaning="의미 본문",
    limitations="명시 없음",
)


def paper(arxiv_id: str, **kw) -> HFPaper:
    kw.setdefault("title", f"Title {arxiv_id}")
    return HFPaper(arxiv_id=arxiv_id, published_day=FRI, abstract="Abstract.", **kw)


class Pdfs:
    """Stands in for arxiv.org: serves a fake PDF per id and records every request."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        return httpx.Response(200, content=b"%PDF fake " + request.url.path.encode())


class GatedParser(FakeParser):
    """Parser that can hold a paper inside 파싱 until the test lets it go."""

    def __init__(self, result: ParseResult) -> None:
        super().__init__(result)
        self.entered = threading.Semaphore(0)
        self.release = threading.Semaphore(0)

    def parse(self, pdf, out_dir):
        self.entered.release()
        assert self.release.acquire(timeout=5), "test never released the parser"
        return super().parse(pdf, out_dir)


def start(
    make_client: Callable[..., TestClient],
    ids=("2610.00001",),
    parser=None,
    llm=None,
    pdfs=None,
) -> tuple[TestClient, FakeParser, FakeLLM, Pdfs]:
    parser = parser or FakeParser(ParseResult(markdown=BODY))
    llm = llm or FakeLLM(REPORT)
    pdfs = pdfs or Pdfs()
    hf = FakeHF({FRI: [paper(i, upvotes=10 - n) for n, i in enumerate(ids)]})
    client = make_client(Boundaries(hf, FakeArxiv(), llm, parser))
    client.app.state.pdf_http = httpx.Client(transport=httpx.MockTransport(pdfs))  # type: ignore[attr-defined]
    client.post("/api/collect")
    wait_for(lambda: not client.get("/api/collect").json()["running"])
    return client, parser, llm, pdfs


def wait_for(cond: Callable[[], bool], what: str = "condition") -> None:
    for _ in range(500):
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError(f"never happened: {what}")


def report_of(client: TestClient, arxiv_id: str) -> dict:
    return client.get(f"/api/papers/{arxiv_id}/report").json()


def wait_status(client: TestClient, arxiv_id: str, status: str) -> dict:
    wait_for(lambda: report_of(client, arxiv_id)["status"] == status, f"{arxiv_id} -> {status}")
    return report_of(client, arxiv_id)


def test_clicking_a_card_runs_the_three_stages_and_stores_the_report(make_client):
    client, parser, llm, pdfs = start(make_client)
    assert report_of(client, "2610.00001")["status"] is None  # never asked for

    res = client.post("/api/papers/2610.00001/report")
    assert res.status_code == 202

    done = wait_status(client, "2610.00001", "완료")
    assert done["report"]["hook"] == "Bench 91.2점으로 이전 SOTA를 넘음"
    assert done["report"]["limitations"] == "명시 없음"
    assert pdfs.requests == ["https://arxiv.org/pdf/2610.00001"]
    # 작성 got the parsed body, not just the abstract
    (name, (body, figures)), = llm.calls
    assert name == "write_report" and BODY in body and figures == []
    # header facts for the report screen
    assert done["paper"]["title"] == "Title 2610.00001"


def test_one_paper_at_a_time_in_click_order_and_waiting_cards_show_their_place(make_client):
    ids = ("2610.00001", "2610.00002", "2610.00003")
    parser = GatedParser(ParseResult(markdown=BODY))
    client, _, llm, _ = start(make_client, ids, parser=parser)

    for i in ids:
        assert client.post(f"/api/papers/{i}/report").status_code == 202
    assert parser.entered.acquire(timeout=5)  # the first paper is inside 파싱

    first = report_of(client, ids[0])
    assert (first["status"], first["stage"]) == ("진행 중", "파싱")
    assert isinstance(first["elapsed"], int) and first["elapsed"] >= 0
    waiting = [report_of(client, i) for i in ids[1:]]
    assert [(r["status"], r["queue_position"]) for r in waiting] == [("대기", 1), ("대기", 2)]
    # the card list sees the same states
    states = client.get("/api/reports").json()["reports"]
    assert {i: s["status"] for i, s in states.items()} == {ids[0]: "진행 중", ids[1]: "대기", ids[2]: "대기"}
    assert not parser.entered.acquire(timeout=0.2)  # nobody else started parsing

    parser.release.release(3)
    for i in ids:
        wait_status(client, i, "완료")
    assert [pdf.parent.name for pdf, _ in parser.calls] == list(ids)  # FIFO
    assert len(llm.calls) == 3


def test_a_finished_report_is_opened_again_never_regenerated(make_client):
    client, parser, llm, pdfs = start(make_client)
    client.post("/api/papers/2610.00001/report")
    first = wait_status(client, "2610.00001", "완료")

    again = client.post("/api/papers/2610.00001/report")

    assert again.status_code == 202
    assert again.json()["status"] == "완료" and again.json()["report"] == first["report"]
    time.sleep(0.1)
    assert (len(pdfs.requests), len(parser.calls), len(llm.calls)) == (1, 1, 1)


def test_every_stage_leaves_its_result_on_disk(make_client):
    client, _, _, _ = start(make_client)
    client.post("/api/papers/2610.00001/report")
    wait_status(client, "2610.00001", "완료")

    folder = client.app.state.settings.data_dir / "papers" / "2610.00001"  # type: ignore[attr-defined]
    assert (folder / "paper.pdf").read_bytes().startswith(b"%PDF")
    assert (folder / "parsed").is_dir() and any((folder / "parsed").iterdir())


def test_collection_keeps_working_while_a_report_is_parsing(make_client):
    parser = GatedParser(ParseResult(markdown=BODY))
    client, _, _, _ = start(make_client, parser=parser)
    client.post("/api/papers/2610.00001/report")
    assert parser.entered.acquire(timeout=5)

    assert client.post("/api/collect").status_code == 202
    wait_for(lambda: not client.get("/api/collect").json()["running"], "collection finished")

    assert client.get("/api/collect").json()["error"] is None
    assert report_of(client, "2610.00001")["status"] == "진행 중"
    parser.release.release()
    wait_status(client, "2610.00001", "완료")


class BrokenParser(FakeParser):
    def __init__(self, result: ParseResult, broken: set[str]) -> None:
        super().__init__(result)
        self.broken = broken

    def parse(self, pdf, out_dir):
        if pdf.parent.name in self.broken:
            raise RuntimeError("CUDA not available")
        return super().parse(pdf, out_dir)


def test_a_failing_paper_is_recorded_with_its_stage_and_does_not_stop_the_queue(make_client):
    parser = BrokenParser(ParseResult(markdown=BODY), {"2610.00001"})
    client, _, llm, _ = start(make_client, ("2610.00001", "2610.00002"), parser=parser)
    client.post("/api/papers/2610.00001/report")
    client.post("/api/papers/2610.00002/report")

    failed = wait_status(client, "2610.00001", "실패")
    wait_status(client, "2610.00002", "완료")

    assert failed["stage"] == "파싱" and "CUDA not available" in failed["error_log"]
    assert failed["report"] is None
    assert len(llm.calls) == 1


def test_the_real_llm_client_asks_the_responses_api_for_a_structured_korean_report(make_client):
    sent: list[dict] = []

    def openai(request: httpx.Request) -> httpx.Response:  # stands in for api.openai.com
        sent.append(json.loads(request.content))
        output = {
            "type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "annotations": [], "text": REPORT.model_dump_json()}],
        }  # fmt: skip
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "created_at": 0, "model": "test-model", "status": "completed",
            "output": [output], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })  # fmt: skip

    settings = Settings(openai_api_key="sk-test", openai_model="test-model")
    llm = OpenAILLM(settings, httpx.Client(transport=httpx.MockTransport(openai)))
    client, _, _, _ = start(make_client, llm=llm)  # type: ignore[arg-type]

    client.post("/api/papers/2610.00001/report")

    assert wait_status(client, "2610.00001", "완료")["report"]["hook"] == REPORT.hook
    (request,) = [r for r in sent if r["model"] == "test-model"]  # the collection also sent its KO summary request
    assert request["model"] == "test-model"
    assert request["text"]["format"]["type"] == "json_schema"
    assert set(request["text"]["format"]["schema"]["properties"]) == set(Report.model_fields)
    assert BODY in request["input"]
    for rule in ("Korean", "명시 없음", "Never write a number"):
        assert rule in request["instructions"]


def test_report_screen_modules_are_served(make_client):
    client = make_client()
    assert client.get("/static/app.js").text.count("reports.js") == 1
    for name in ("reports.js", "reports.css"):
        assert client.get(f"/static/{name}").status_code == 200


def test_unknown_paper_is_404(make_client):
    client, _, _, _ = start(make_client)
    assert client.post("/api/papers/9999.99999/report").status_code == 404
    assert client.get("/api/papers/9999.99999/report").status_code == 404


def test_offline_mode_builds_a_whole_report_from_the_canned_fixtures(make_client):
    from paperbrief import boundaries

    client = make_client(boundaries.offline(Settings()), offline=True)
    client.post("/api/collect")
    wait_for(lambda: not client.get("/api/collect").json()["running"])
    arxiv_id = client.get("/api/papers").json()["papers"][0]["arxiv_id"]

    client.post(f"/api/papers/{arxiv_id}/report")

    done = wait_status(client, arxiv_id, "완료")
    assert "71.4" in done["report"]["hook"] and done["report"]["limitations"] == "명시 없음"
