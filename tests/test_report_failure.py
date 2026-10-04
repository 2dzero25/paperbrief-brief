"""Seam: HTTP API through TestClient. Ticket #8: 보고서 실패와 복구 (다시 시도, 재시작, 키 없음, 파싱 tier 폴백)."""
import httpx

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.llm import OpenAILLM, Report
from paperbrief.parser import ParseResult, TieredParser
from tests.fakes import FakeArxiv, FakeHF, FakeLLM, FakeParser
from tests.test_reports import BODY, REPORT, GatedParser, Pdfs, report_of, start, wait_status


class FlakyParser(FakeParser):
    """Fails the first `fail_times` calls, then works."""

    def __init__(self, result: ParseResult, fail_times: int = 1) -> None:
        super().__init__(result)
        self.fail_times = fail_times

    def parse(self, pdf, out_dir):
        if len(self.calls) < self.fail_times:
            self.calls.append((pdf, out_dir))
            raise RuntimeError("CUDA not available")
        return super().parse(pdf, out_dir)


class FlakyLLM(FakeLLM):
    def __init__(self, report: Report) -> None:
        super().__init__(report)
        self.broken = True

    def write_report(self, body, figures):
        if self.broken:
            raise RuntimeError("rate limited")
        return super().write_report(body, figures)


def test_retry_after_a_parse_failure_skips_the_pdf_and_finishes_the_report(make_client):
    parser = FlakyParser(ParseResult(markdown=BODY))
    client, _, llm, pdfs = start(make_client, parser=parser)
    client.post("/api/papers/2610.00001/report")
    failed = wait_status(client, "2610.00001", "실패")
    assert failed["stage"] == "파싱" and "CUDA not available" in failed["error_log"]

    assert client.post("/api/papers/2610.00001/report").status_code == 202  # 다시 시도

    done = wait_status(client, "2610.00001", "완료")
    assert done["report"]["hook"] == REPORT.hook and done["error_log"] == ""
    assert len(pdfs.requests) == 1 and len(parser.calls) == 2 and len(llm.calls) == 1


def test_retry_after_a_write_failure_runs_only_the_write_again(make_client):
    llm = FlakyLLM(REPORT)
    client, parser, _, pdfs = start(make_client, llm=llm)
    client.post("/api/papers/2610.00001/report")
    failed = wait_status(client, "2610.00001", "실패")
    assert failed["stage"] == "작성" and "rate limited" in failed["error_log"]

    llm.broken = False
    client.post("/api/papers/2610.00001/report")

    wait_status(client, "2610.00001", "완료")
    assert len(pdfs.requests) == 1 and len(parser.calls) == 1


def test_retry_after_a_pdf_failure_starts_with_the_pdf(make_client):
    pdfs = Pdfs()
    answers = iter([503])  # arxiv.org is down once

    def flaky(request: httpx.Request) -> httpx.Response:
        status = next(answers, 200)
        return httpx.Response(status) if status != 200 else pdfs(request)

    client, parser, _, _ = start(make_client)
    client.app.state.pdf_http = httpx.Client(transport=httpx.MockTransport(flaky))  # type: ignore[attr-defined]
    client.post("/api/papers/2610.00001/report")
    failed = wait_status(client, "2610.00001", "실패")
    assert failed["stage"] == "PDF" and "503" in failed["error_log"]

    client.post("/api/papers/2610.00001/report")

    wait_status(client, "2610.00001", "완료")
    assert len(pdfs.requests) == 1 and len(parser.calls) == 1


def test_reports_left_running_or_waiting_become_failed_when_the_app_starts_again(make_client):
    ids = ("2610.00001", "2610.00002")
    parser = GatedParser(ParseResult(markdown=BODY))
    client, _, _, _ = start(make_client, ids, parser=parser)
    for i in ids:
        client.post(f"/api/papers/{i}/report")
    assert parser.entered.acquire(timeout=5)  # first paper is inside 파싱, the second waits

    restarted = make_client()  # same data dir: the app was switched off and on

    states = restarted.get("/api/reports").json()["reports"]
    logs = [restarted.get(f"/api/papers/{i}/report").json()["error_log"] for i in ids]
    parser.release.release(2)  # lets the old worker thread end; it belongs to the app that is gone
    assert {i: (s["status"], s["stage"]) for i, s in states.items()} == {ids[0]: ("실패", "파싱"), ids[1]: ("실패", "PDF")}
    assert all("앱 종료로 중단" in log for log in logs)


def test_a_report_interrupted_by_a_restart_continues_after_the_retry(make_client):
    parser = GatedParser(ParseResult(markdown=BODY))
    client, _, _, pdfs = start(make_client, parser=parser)
    client.post("/api/papers/2610.00001/report")
    assert parser.entered.acquire(timeout=5)  # PDF is on disk, 파싱 is running
    restarted = make_client(Boundaries(FakeHF(), FakeArxiv(), FakeLLM(REPORT), FakeParser(ParseResult(markdown=BODY))))
    restarted.app.state.pdf_http = httpx.Client(transport=httpx.MockTransport(pdfs))  # type: ignore[attr-defined]

    restarted.post("/api/papers/2610.00001/report")

    assert wait_status(restarted, "2610.00001", "완료")["report"]["hook"] == REPORT.hook
    assert len(pdfs.requests) == 1  # the PDF that was already downloaded was not fetched again
    parser.release.release()  # lets the old app's worker thread end


def test_a_finished_report_survives_a_restart(make_client):
    client, _, _, _ = start(make_client)
    client.post("/api/papers/2610.00001/report")
    wait_status(client, "2610.00001", "완료")

    restarted = make_client()

    assert report_of(restarted, "2610.00001")["status"] == "완료"


def openai_answering(report: Report) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        output = {
            "type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "annotations": [], "text": report.model_dump_json()}],
        }  # fmt: skip
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "created_at": 0, "model": "test-model", "status": "completed",
            "output": [output], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })  # fmt: skip

    return httpx.Client(transport=httpx.MockTransport(answer))


def test_without_an_openai_key_pdf_and_parsing_run_and_writing_fails_until_the_key_is_set(make_client):
    parser = FakeParser(ParseResult(markdown=BODY))
    client, _, _, pdfs = start(make_client, parser=parser, llm=OpenAILLM(Settings(openai_api_key="")))
    client.post("/api/papers/2610.00001/report")

    failed = wait_status(client, "2610.00001", "실패")

    assert failed["stage"] == "작성" and "OPENAI_API_KEY 없음" in failed["error_log"]
    assert (len(pdfs.requests), len(parser.calls)) == (1, 1)

    # The key is read when the app starts, so a new key means starting the app again (documented in .env.example).
    keyed = Settings(openai_api_key="sk-test", openai_model="test-model")
    restarted = make_client(Boundaries(FakeHF(), FakeArxiv(), OpenAILLM(keyed, openai_answering(REPORT)), parser))
    restarted.post("/api/papers/2610.00001/report")  # 다시 시도

    done = wait_status(restarted, "2610.00001", "완료")
    assert done["report"]["hook"] == REPORT.hook
    assert (len(pdfs.requests), len(parser.calls)) == (1, 1)  # resumed at 작성


class Runner:
    """Stands in for the MinerU runner of #13: `runner(pdf, out_dir, tier)`; tiers listed in `broken` raise."""

    def __init__(self, broken: set[str]) -> None:
        self.broken = broken
        self.calls: list[str] = []

    def __call__(self, pdf, out_dir, tier):
        self.calls.append(tier)
        if tier in self.broken:
            raise RuntimeError(f"{tier} tier crashed")
        return ParseResult(markdown=f"{BODY} ({tier})")


def tiered(make_client, runner):
    return start(make_client, parser=TieredParser(runner))


def test_parsing_falls_back_from_the_standard_tier_to_basic(make_client):
    runner = Runner({"standard"})
    client, _, llm, _ = tiered(make_client, runner)
    client.post("/api/papers/2610.00001/report")

    wait_status(client, "2610.00001", "완료")

    assert runner.calls == ["standard", "basic"]
    assert "(basic)" in llm.calls[0][1][0]  # 작성 got the basic tier's body


def test_a_working_standard_tier_is_the_only_one_run(make_client):
    runner = Runner(set())
    client, _, _, _ = tiered(make_client, runner)
    client.post("/api/papers/2610.00001/report")

    wait_status(client, "2610.00001", "완료")

    assert runner.calls == ["standard"]


def test_when_both_tiers_fail_parsing_fails_once_with_both_logs(make_client):
    runner = Runner({"standard", "basic"})
    client, _, llm, _ = tiered(make_client, runner)
    client.post("/api/papers/2610.00001/report")

    failed = wait_status(client, "2610.00001", "실패")

    assert failed["stage"] == "파싱"
    assert "standard tier crashed" in failed["error_log"] and "basic tier crashed" in failed["error_log"]
    assert runner.calls == ["standard", "basic"] and llm.calls == []

    runner.broken.clear()  # 다시 시도 runs the tiers again, from standard
    client.post("/api/papers/2610.00001/report")
    wait_status(client, "2610.00001", "완료")
    assert runner.calls == ["standard", "basic", "standard"]


def test_the_failure_screen_is_served_and_loaded_by_the_page(make_client):
    client = make_client()
    assert "report_failure.js" in client.get("/static/app.js").text
    js = client.get("/static/report_failure.js")
    assert js.status_code == 200 and "다시 시도" in js.text


def test_an_error_page_instead_of_the_pdf_is_a_pdf_failure_and_is_fetched_again_on_retry(make_client):
    pdfs = Pdfs()
    answers = iter(["<html>Service Unavailable</html>"])  # 200 with a gateway error page, once

    def gateway(request: httpx.Request) -> httpx.Response:
        page = next(answers, None)
        return httpx.Response(200, content=page.encode()) if page else pdfs(request)

    client, parser, _, _ = start(make_client)
    client.app.state.pdf_http = httpx.Client(transport=httpx.MockTransport(gateway))  # type: ignore[attr-defined]
    client.post("/api/papers/2610.00001/report")
    failed = wait_status(client, "2610.00001", "실패")
    paper = client.app.state.settings.data_dir / "papers" / "2610.00001"  # type: ignore[attr-defined]
    assert failed["stage"] == "PDF" and "PDF" in failed["error_log"]
    assert not (paper / "paper.pdf").exists() and parser.calls == []  # the bad body was never kept or parsed

    client.post("/api/papers/2610.00001/report")

    wait_status(client, "2610.00001", "완료")
    assert len(pdfs.requests) == 1 and len(parser.calls) == 1


def test_an_error_outside_any_stage_is_recorded_as_a_failure_instead_of_leaving_the_report_running(make_client, monkeypatch):
    client, parser, _, _ = start(make_client)

    def broken(app):
        raise RuntimeError("no network stack")

    monkeypatch.setattr("paperbrief.app.http_for", broken)
    client.post("/api/papers/2610.00001/report")

    failed = wait_status(client, "2610.00001", "실패")
    assert failed["stage"] == "PDF" and "no network stack" in failed["error_log"]
    assert parser.calls == []
