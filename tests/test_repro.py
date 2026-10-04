"""Seam: HTTP API through TestClient. Ticket #10: 재현 체크 (5 판정 + 근거) and the header links.

The LLM is a fake with canned structured output; the real client is exercised against a fake api.openai.com
to see the exact prompt it sends.
"""
import json
from contextlib import closing

import httpx

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.db import connect
from paperbrief.llm import OpenAILLM, ReproItem
from paperbrief.parser import ParseResult
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser
from tests.test_reports import BODY, FRI, REPORT, REPRO, Pdfs, paper, wait_for, wait_status

REGISTERED = "https://github.com/someone-else/registered-repo"
ID = "2610.00001"


def start(make_client, report=REPORT, code_url="", llm=None, wait=True):
    hf = FakeHF({FRI: [paper(ID, code_url=code_url)]})
    client = make_client(Boundaries(hf, FakeArxiv(), llm or FakeLLM(report), FakeParser(ParseResult(markdown=BODY))))
    client.app.state.pdf_http = httpx.Client(transport=httpx.MockTransport(Pdfs()))  # type: ignore[attr-defined]
    client.post("/api/collect")
    wait_for(lambda: not client.get("/api/collect").json()["running"])
    client.post(f"/api/papers/{ID}/report")
    return client, wait_status(client, ID, "완료") if wait else {}


def test_the_five_items_come_back_with_their_verdict_and_evidence(make_client):
    _, done = start(make_client, REPORT)

    repro = done["report"]["repro"]
    assert list(repro) == ["code", "weights", "data", "gpu", "license"]
    assert repro["code"] == {"verdict": "공개", "evidence": "https://github.com/author/onestreamer, 1쪽 각주"}
    assert repro["weights"]["verdict"] == "비공개"
    assert repro["gpu"] == {"verdict": "공개", "evidence": "8×A100, 3일"}  # original wording


def test_a_missing_item_is_always_명시_없음_with_that_as_its_evidence(make_client):
    _, done = start(make_client, REPORT)

    assert done["report"]["repro"]["license"] == {"verdict": "명시 없음", "evidence": "명시 없음"}


def test_evidence_that_says_명시_없음_makes_the_verdict_명시_없음_too(make_client):
    repro = REPRO.model_copy(update={"weights": ReproItem(verdict="비공개", evidence=" 명시 없음 ")})
    _, done = start(make_client, REPORT.model_copy(update={"repro": repro}))

    assert done["report"]["repro"]["weights"] == {"verdict": "명시 없음", "evidence": "명시 없음"}


def test_a_report_stored_without_a_repro_check_still_loads(make_client):
    client, _ = start(make_client)
    old = json.dumps(REPORT.model_dump(exclude={"repro"}))
    with closing(connect(client.app.state.settings)) as db, db:  # type: ignore[attr-defined]
        db.execute("UPDATE reports SET report_json = ? WHERE arxiv_id = ?", (old, ID))

    state = client.get(f"/api/papers/{ID}/report").json()

    assert state["status"] == "완료" and state["report"].get("repro") is None and state["report"]["hook"] == REPORT.hook


def test_a_new_report_without_a_repro_check_fails_in_the_write_stage_and_retry_can_fix_it(make_client):
    llm = FakeLLM(REPORT.model_copy(update={"repro": None}))
    client, _ = start(make_client, llm=llm, wait=False)

    failed = wait_status(client, ID, "실패")

    assert failed["stage"] == "작성" and "repro 누락" in failed["error_log"] and failed["report"] is None
    llm.report = REPORT
    client.post(f"/api/papers/{ID}/report")
    assert wait_status(client, ID, "완료")["report"]["repro"]["code"]["verdict"] == "공개"


def test_header_links_point_to_arxiv_pdf_and_the_registered_code(make_client):
    _, done = start(make_client, code_url=REGISTERED)

    assert done["links"] == [
        {"label": "arXiv", "url": f"https://arxiv.org/abs/{ID}"},
        {"label": "PDF", "url": f"https://arxiv.org/pdf/{ID}"},
        {"label": "GitHub", "url": REGISTERED},
    ]
    assert done["paper"]["title"] == f"Title {ID}"


def test_no_registered_code_means_no_github_link(make_client):
    _, done = start(make_client)

    assert [link["label"] for link in done["links"]] == ["arXiv", "PDF"]


def test_the_prompt_judges_by_the_paper_itself_and_never_carries_the_registered_code(make_client):
    sent: list[dict] = []

    def openai(request: httpx.Request) -> httpx.Response:  # stands in for api.openai.com
        sent.append(json.loads(request.content))
        output = {"type": "message", "id": "m", "status": "completed", "role": "assistant",
                  "content": [{"type": "output_text", "annotations": [], "text": REPORT.model_dump_json()}]}  # fmt: skip
        return httpx.Response(200, json={
            "id": "r", "object": "response", "created_at": 0, "model": "test-model", "status": "completed",
            "output": [output], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })  # fmt: skip

    settings = Settings(openai_api_key="sk-test", openai_model="test-model")
    llm = OpenAILLM(settings, httpx.Client(transport=httpx.MockTransport(openai)))
    _, done = start(make_client, code_url=REGISTERED, llm=llm)  # type: ignore[arg-type]

    assert done["report"]["repro"]["data"]["evidence"] == "p.6, Table 2"
    (request,) = [r for r in sent if r["model"] == "test-model"]  # the collection also sent its KO summary request
    assert "repro" in request["text"]["format"]["schema"]["properties"]
    rules = request["instructions"]
    assert "ONLY" in rules and "this paper itself" in rules and "cites or surveys" in rules
    assert "registered" in rules  # the HF-registered code is named as not evidence
    assert "someone-else" not in rules + request["input"]


def test_the_repro_row_is_served_and_wired_into_the_report_screen(make_client):
    client = make_client()

    assert "repro.js" in client.get("/static/app.js").text
    assert "재현" in client.get("/static/repro.js").text
