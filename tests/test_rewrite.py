"""Seam: HTTP API through TestClient. Ticket #12: 다시 작성 reruns only 작성 through the queue; the old report stays until a new one succeeds."""
import httpx

from paperbrief.boundaries import Boundaries
from paperbrief.llm import QA, Report
from paperbrief.parser import ParseResult
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser
from tests.test_questions import ID
from tests.test_reports import BODY, REPORT, REPRO, GatedParser, report_of, start, wait_for, wait_status

REWRITTEN = Report(hook="새 훅", method="새 방법", results="새 결과", difference="새 차이", meaning="새 의미", limitations="새 한계", repro=REPRO)
REWRITE = f"/api/papers/{ID}/report/rewrite"


class TwoReports(FakeLLM):
    """The first write_report returns REPORT, later ones REWRITTEN; `broken` makes it raise."""

    def __init__(self) -> None:
        super().__init__(REPORT)
        self.broken = False

    def write_report(self, body, figures):
        if self.broken:
            raise RuntimeError("rate limited")
        out = super().write_report(body, figures)
        self.report = REWRITTEN
        return out


def wait_for_new_report(client):
    wait_for(lambda: (s := client.get(f"/api/papers/{ID}/report").json())["status"] == "완료" and s["report"]["hook"] == "새 훅", "rewritten")
    return client.get(f"/api/papers/{ID}/report").json()


def test_rewrite_runs_only_the_write_stage_and_the_new_report_replaces_the_old(make_client):
    client, parser, llm, pdfs = start(make_client, llm=TwoReports())
    client.post(f"/api/papers/{ID}/report")
    wait_status(client, ID, "완료")

    res = client.post(REWRITE)

    assert res.status_code == 202
    assert wait_for_new_report(client)["status"] == "완료"
    assert len(pdfs.requests) == 1 and len(parser.calls) == 1  # PDF and 파싱 kept
    assert [name for name, _ in llm.calls] == ["write_report", "write_report"]
    assert llm.calls[1][1][0] == BODY  # from the stored parse result


def test_a_failed_rewrite_keeps_the_old_report_and_retry_reruns_only_the_write(make_client):
    llm = TwoReports()
    client, parser, _, pdfs = start(make_client, llm=llm)
    client.post(f"/api/papers/{ID}/report")
    wait_status(client, ID, "완료")
    llm.broken = True

    client.post(REWRITE)

    failed = wait_status(client, ID, "실패")
    assert failed["stage"] == "작성" and "rate limited" in failed["error_log"]
    assert failed["report"]["hook"] == REPORT.hook  # the old report is still stored
    llm.broken = False
    assert client.post(f"/api/papers/{ID}/report").status_code == 202  # 다시 시도
    assert wait_for_new_report(client)["error_log"] == ""
    assert len(pdfs.requests) == 1 and len(parser.calls) == 1


def test_only_a_finished_report_can_be_rewritten(make_client):
    client, _, llm, _ = start(make_client, llm=TwoReports())

    assert client.post(REWRITE).status_code == 409  # never asked for
    assert client.post("/api/papers/9999.99999/report/rewrite").status_code == 404
    assert report_of(client, ID)["status"] is None and llm.calls == []


OTHER = "2610.00002"


def test_a_rewrite_waits_in_the_same_queue_as_every_other_report(make_client):
    parser = GatedParser(ParseResult(markdown=BODY))
    client, _, llm, _ = start(make_client, ids=(ID, OTHER), parser=parser, llm=TwoReports())
    client.post(f"/api/papers/{ID}/report")
    parser.release.release()
    wait_status(client, ID, "완료")
    client.post(f"/api/papers/{OTHER}/report")
    assert parser.entered.acquire(timeout=5) and parser.entered.acquire(timeout=5)  # both papers entered 파싱 once; OTHER is inside now

    client.post(REWRITE)

    waiting = report_of(client, ID)
    assert (waiting["status"], waiting["queue_position"]) == ("대기", 1)
    assert client.get("/api/reports").json()["reports"][ID]["status"] == "대기"  # the card dot
    assert len(llm.calls) == 1  # nothing rewrote yet
    parser.release.release()
    wait_status(client, OTHER, "완료")
    assert wait_for_new_report(client)["report"]["hook"] == "새 훅"
    assert [name for name, _ in llm.calls] == ["write_report"] * 3


def test_a_rewrite_cut_off_by_a_restart_is_a_failed_write_that_keeps_the_old_report(make_client):
    parser = GatedParser(ParseResult(markdown=BODY))
    client, _, _, pdfs = start(make_client, ids=(ID, OTHER), parser=parser, llm=TwoReports())
    client.post(f"/api/papers/{ID}/report")
    parser.release.release()
    wait_status(client, ID, "완료")
    client.post(f"/api/papers/{OTHER}/report")
    assert parser.entered.acquire(timeout=5) and parser.entered.acquire(timeout=5)
    client.post(REWRITE)
    restarted = make_client(Boundaries(FakeHF(), FakeArxiv(), FakeLLM(REWRITTEN), FakeParser()))
    restarted.app.state.pdf_http = httpx.Client(transport=httpx.MockTransport(pdfs))  # type: ignore[attr-defined]

    failed = report_of(restarted, ID)

    assert (failed["status"], failed["stage"]) == ("실패", "작성") and failed["report"]["hook"] == REPORT.hook
    restarted.post(f"/api/papers/{ID}/report")
    assert wait_for_new_report(restarted)["error_log"] == ""
    assert len(pdfs.requests) == 2  # one per paper, nothing fetched again
    parser.release.release()  # lets the old app's worker thread end


def test_a_rewrite_keeps_the_questions_and_the_next_one_uses_the_new_report(make_client):
    llm = TwoReports()
    client, _, _, _ = start(make_client, llm=llm)
    client.post(f"/api/papers/{ID}/report")
    wait_status(client, ID, "완료")
    client.post(f"/api/papers/{ID}/questions", json={"question": "Which benchmark?"})
    before = client.get(f"/api/papers/{ID}/questions").json()

    client.post(REWRITE)
    wait_for_new_report(client)
    client.post(f"/api/papers/{ID}/questions", json={"question": "And the score?"})

    assert client.get(f"/api/papers/{ID}/questions").json()["questions"][:1] == before["questions"]
    (_, (_, report, history, question)) = llm.calls[-1]
    assert report == REWRITTEN and question == "And the score?"
    assert history == [QA(question="Which benchmark?", answer="answer to Which benchmark?")]


def test_while_a_rewrite_is_failed_the_questions_still_work_against_the_old_report(make_client):
    llm = TwoReports()
    client, _, _, _ = start(make_client, llm=llm)
    client.post(f"/api/papers/{ID}/report")
    wait_status(client, ID, "완료")
    client.post(f"/api/papers/{ID}/questions", json={"question": "Before?"})
    llm.broken = True
    client.post(REWRITE)
    wait_status(client, ID, "실패")

    listed = client.get(f"/api/papers/{ID}/questions").json()["questions"]
    res = client.post(f"/api/papers/{ID}/questions", json={"question": "During?"})

    assert [q["question"] for q in listed] == ["Before?"]
    assert res.status_code == 200 and res.json()["answer"] == "answer to During?"
    (_, (_, report, history, _)) = llm.calls[-1]
    assert report == REPORT and [h.question for h in history] == ["Before?"]  # the stored (old) report


def test_a_report_that_never_completed_still_refuses_questions_after_failing(make_client):
    llm = TwoReports()
    llm.broken = True
    client, _, _, _ = start(make_client, llm=llm)
    client.post(f"/api/papers/{ID}/report")
    wait_status(client, ID, "실패")

    assert client.post(f"/api/papers/{ID}/questions", json={"question": "?"}).status_code == 409
