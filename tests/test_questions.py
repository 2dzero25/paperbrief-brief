"""Seam: HTTP API through TestClient. Ticket #11: 질문 under a finished 보고서, with a fake LLM that records its inputs."""
import json

import httpx

from paperbrief.config import Settings
from paperbrief.llm import QA, OpenAILLM
from tests.fakes import FakeLLM
from tests.test_reports import BODY, REPORT, start, wait_for, wait_status

ID = "2610.00001"
URL = f"/api/papers/{ID}/questions"


def finished(make_client, llm=None):
    client, _, llm, _ = start(make_client, llm=llm or FakeLLM(REPORT))
    client.post(f"/api/papers/{ID}/report")
    wait_status(client, ID, "완료")
    if isinstance(llm, FakeLLM):
        llm.calls.clear()  # only what 질문 sends from here on
    return client, llm


def test_a_question_is_refused_until_the_report_is_done(make_client):
    client, _, llm, _ = start(make_client)

    assert client.post(URL, json={"question": "무엇을 했나?"}).status_code == 409  # no report asked for
    assert client.get(URL).json() == {"questions": []}
    assert client.post("/api/papers/9999.99999/questions", json={"question": "?"}).status_code == 404
    assert llm.calls == []


def test_the_answer_gets_the_whole_body_the_report_and_this_papers_earlier_questions_and_is_saved(make_client):
    client, llm = finished(make_client)

    first = client.post(URL, json={"question": "Which benchmark?"})
    second = client.post(URL, json={"question": "And the score?"})

    assert first.json()["answer"] == "answer to Which benchmark?"
    (_, (body, report, history, question)) = llm.calls[1]
    assert (body, report, question) == (BODY, REPORT, "And the score?")
    assert history == [QA(question="Which benchmark?", answer="answer to Which benchmark?")]
    assert llm.calls[0][1][2] == []  # the first question had no history
    assert second.status_code == 200
    listed = client.get(URL).json()["questions"]
    assert [(q["question"], q["answer"]) for q in listed] == [
        ("Which benchmark?", "answer to Which benchmark?"),
        ("And the score?", "answer to And the score?"),
    ]


def test_another_papers_questions_are_not_in_the_history(make_client):
    client, _, llm, _ = start(make_client, ids=(ID, "2610.00002"), llm=FakeLLM(REPORT))
    for i in (ID, "2610.00002"):
        client.post(f"/api/papers/{i}/report")
        wait_status(client, i, "완료")
    client.post(URL, json={"question": "mine"})
    llm.calls.clear()

    client.post("/api/papers/2610.00002/questions", json={"question": "yours"})

    assert llm.calls[0][1][2] == []
    assert [q["question"] for q in client.get("/api/papers/2610.00002/questions").json()["questions"]] == ["yours"]


class FailingLLM(FakeLLM):
    def answer(self, body, report, history, question):
        super().answer(body, report, history, question)
        raise RuntimeError("OpenAI is down")


def test_a_failed_answer_saves_nothing_and_the_same_question_can_be_asked_again(make_client):
    llm = FailingLLM(REPORT)
    client, _ = finished(make_client, llm)

    res = client.post(URL, json={"question": "Why?"})

    assert res.status_code == 502 and "OpenAI is down" in res.json()["detail"]
    assert client.get(URL).json()["questions"] == []
    llm.answer = lambda body, report, history, question: "now it works"  # type: ignore[method-assign]
    assert client.post(URL, json={"question": "Why?"}).json()["answer"] == "now it works"
    assert [q["question"] for q in client.get(URL).json()["questions"]] == ["Why?"]


def test_the_real_llm_client_sends_body_then_report_then_history_then_question_in_the_questions_language(make_client):
    sent: list[dict] = []

    def openai(request: httpx.Request) -> httpx.Response:  # stands in for api.openai.com
        sent.append(json.loads(request.content))
        asks = "answer" in sent[-1]["text"]["format"]["schema"]["properties"]
        text = json.dumps({"answer": "It reaches 91.2 on Bench."}) if asks else REPORT.model_dump_json()
        output = {
            "type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "annotations": [], "text": text}],
        }  # fmt: skip
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "created_at": 0, "model": "test-model", "status": "completed",
            "output": [output], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })  # fmt: skip

    http = httpx.Client(transport=httpx.MockTransport(openai))
    llm = OpenAILLM(Settings(openai_api_key="sk-test", openai_model="test-model"), http)
    client, _ = finished(make_client, llm)  # type: ignore[arg-type]
    sent.clear()

    client.post(URL, json={"question": "What score?"})
    res = client.post(URL, json={"question": "Compared to what?"})

    assert res.json()["answer"] == "It reaches 91.2 on Bench."
    first, second = sent
    assert second["model"] == "test-model"
    assert set(second["text"]["format"]["schema"]["properties"]) == {"answer"}
    for rule in ("same language as the question", "명시 없음", "Never write a number"):
        assert rule in second["instructions"]
    assert second["instructions"] == first["instructions"]  # a fixed prefix
    # stable prefix first (body, report), then the growing history, the new question last
    text = second["input"]
    order = [text.index(s) for s in (BODY, REPORT.hook, "What score?", "It reaches 91.2 on Bench.", "Compared to what?")]
    assert order == sorted(order)
    stable = first["input"].split("<history>")[0]
    assert BODY in stable and REPORT.hook in stable and text.startswith(stable)  # cacheable prefix: body + report


def test_offline_mode_answers_with_a_canned_text_and_keeps_it(make_client):
    from paperbrief import boundaries

    client = make_client(boundaries.offline(Settings()), offline=True)
    client.post("/api/collect")
    wait_for(lambda: not client.get("/api/collect").json()["running"])
    arxiv_id = client.get("/api/papers").json()["papers"][0]["arxiv_id"]
    client.post(f"/api/papers/{arxiv_id}/report")
    wait_status(client, arxiv_id, "완료")

    res = client.post(f"/api/papers/{arxiv_id}/questions", json={"question": "어떤 데이터셋을 썼나?"})

    assert res.status_code == 200 and res.json()["answer"]
    assert len(client.get(f"/api/papers/{arxiv_id}/questions").json()["questions"]) == 1


def test_question_screen_modules_are_served(make_client):
    client = make_client()
    assert client.get("/static/app.js").text.count("questions.js") == 1
    for name in ("questions.js", "questions.css"):
        assert client.get(f"/static/{name}").status_code == 200


def test_an_empty_question_is_rejected(make_client):
    client, llm = finished(make_client)
    assert client.post(URL, json={"question": ""}).status_code == 422
    assert llm.calls == []
