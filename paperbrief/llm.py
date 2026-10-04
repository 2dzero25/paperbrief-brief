"""Boundary 3/4: OpenAI Responses API. The collection (summaries) and report/question tickets implement it."""
import time
from typing import Literal, Protocol

import httpx
from openai import OpenAI
from pydantic import BaseModel, model_validator

from paperbrief import question_prompt, report_prompt
from paperbrief.config import Settings
from paperbrief.hf import FIXTURES_DIR
from paperbrief.offline import delay, fail_once
from paperbrief.parser import FigureCandidate


class ReproItem(BaseModel):
    """One 판정 of the 재현 체크. 명시 없음 is always `?`, and then the evidence is that same phrase."""

    verdict: Literal["공개", "비공개", "명시 없음"]  # 판정
    evidence: str  # 근거: URL, 쪽, 표 번호; 원문 표기 for GPU and 라이선스

    @model_validator(mode="after")
    def _missing_has_no_other_evidence(self) -> "ReproItem":
        if self.verdict == "명시 없음":
            self.evidence = "명시 없음"
        return self


class Repro(BaseModel):
    code: ReproItem
    weights: ReproItem
    data: ReproItem
    gpu: ReproItem
    license: ReproItem


class Report(BaseModel):
    """The JSON stored in one column of the reports table (ADR-0001).

    Additive only: a later ticket adds its field WITH A DEFAULT so reports stored earlier still load.
    Planned: `figures: list[str] = []` (#9, 그림 후보 ids, 0-2) and `repro: Repro | None = None` (#10).
    `write_report` asks the model for exactly these fields (it is the `text_format`), so a new field is
    also a new thing the prompt in `report_prompt.py` must describe.
    """

    hook: str  # one sentence holding one key number
    method: str
    results: str
    difference: str
    meaning: str
    limitations: str
    repro: Repro | None = None  # 재현 체크 (#10); None for reports stored before it


class QA(BaseModel):
    question: str
    answer: str


# --- KO 한 줄 요약 (#6) -------------------------------------------------------------------------------------------
class KoSummary(BaseModel):
    arxiv_id: str
    summary: str


class KoSummaries(BaseModel):
    items: list[KoSummary]


KO_INSTRUCTIONS = """You write one-line Korean summaries of research papers for a browsing list.

Rules:
- For every paper in <papers>, return one item with the same arxiv_id and a summary of one sentence in Korean.
- Keep the sentence short (about 60 characters), plain and specific: say what the paper does, not that it is a paper.
- Keep technical terms, model names, dataset names and method names in their English original.
- Use only the title and abstract. Do not add numbers or claims that they do not contain.
"""


def ko_input(papers: list[tuple[str, str, str]]) -> str:
    items = [
        f'<paper arxiv_id="{arxiv_id}">\n<title>{title}</title>\n<abstract>{abstract}</abstract>\n</paper>'
        for arxiv_id, title, abstract in papers
    ]
    return "<papers>\n" + "\n".join(items) + "\n</papers>"


def summarize_ko_with(client: OpenAI, model: str, papers: list[tuple[str, str, str]]) -> dict[str, str]:
    """One structured call for a whole 발표일. Ids the model invented or left out are simply absent from the result."""
    response = client.responses.parse(model=model, instructions=KO_INSTRUCTIONS, input=ko_input(papers), text_format=KoSummaries)
    if response.output_parsed is None:  # a refusal or an unparsable answer
        raise RuntimeError("OpenAI returned no summaries")
    asked = {arxiv_id for arxiv_id, _, _ in papers}
    return {item.arxiv_id: item.summary for item in response.output_parsed.items if item.arxiv_id in asked}


# --- end KO 한 줄 요약 ---------------------------------------------------------------------------------------------
class LLMClient(Protocol):
    def summarize_ko(self, papers: list[tuple[str, str, str]]) -> dict[str, str]:
        """[(arxiv_id, title, abstract)] -> {arxiv_id: KO 한 줄 요약}, one call per 발표일."""
        ...

    def write_report(self, body: str, figures: list[FigureCandidate]) -> Report: ...

    def answer(self, body: str, report: Report, history: list[QA], question: str) -> str: ...


class _Unimplemented:
    def summarize_ko(self, papers: list[tuple[str, str, str]]) -> dict[str, str]:
        raise NotImplementedError("LLM client not implemented yet")

    def write_report(self, body: str, figures: list[FigureCandidate]) -> Report:
        raise NotImplementedError("LLM client not implemented yet")

    def answer(self, body: str, report: Report, history: list[QA], question: str) -> str:
        raise NotImplementedError("LLM client not implemented yet")


class Answer(BaseModel):
    """`text_format` of `answer` (#11)."""

    answer: str


class OpenAILLM(_Unimplemented):
    """The real client: `summarize_ko` (#6), `write_report` (#7) and `answer` (#11)."""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._http_client = http_client  # tests stand in for api.openai.com here

    def summarize_ko(self, papers: list[tuple[str, str, str]]) -> dict[str, str]:
        if not self._settings.openai_api_key or not papers:  # no key: the list works, just without KO lines
            return {}
        client = OpenAI(api_key=self._settings.openai_api_key, http_client=self._http_client)
        return summarize_ko_with(client, self._settings.openai_summary_model, papers)

    def write_report(self, body: str, figures: list[FigureCandidate]) -> Report:
        if not self._settings.openai_api_key:  # #8 turns this into the user-facing "OPENAI_API_KEY 없음" failure
            raise RuntimeError("OPENAI_API_KEY 없음")
        client = OpenAI(api_key=self._settings.openai_api_key, http_client=self._http_client)
        response = client.responses.parse(
            model=self._settings.openai_model,
            instructions=report_prompt.INSTRUCTIONS,
            input=report_prompt.build_input(body, figures),
            text_format=Report,
        )
        if response.output_parsed is None:  # a refusal or an unparsable answer
            raise RuntimeError("OpenAI returned no report")
        return response.output_parsed

    # ---- answer (#11) ----
    def answer(self, body: str, report: Report, history: list[QA], question: str) -> str:
        if not self._settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 없음")
        client = OpenAI(api_key=self._settings.openai_api_key, http_client=self._http_client)
        response = client.responses.parse(
            model=self._settings.openai_model,
            instructions=question_prompt.INSTRUCTIONS,
            input=question_prompt.build_input(body, report, history, question),
            text_format=Answer,
        )
        if response.output_parsed is None:  # a refusal or an unparsable answer
            raise RuntimeError("OpenAI returned no answer")
        return response.output_parsed.answer


class OfflineLLM(_Unimplemented):
    """Canned report from tests/fixtures; `PAPERBRIEF_OFFLINE_DELAY` seconds of fake work make the progress watchable."""

    def summarize_ko(self, papers: list[tuple[str, str, str]]) -> dict[str, str]:
        return {arxiv_id: f"(오프라인) {title}" for arxiv_id, title, _ in papers}

    def write_report(self, body: str, figures: list[FigureCandidate]) -> Report:
        time.sleep(delay())
        fail_once("작성")
        return Report.model_validate_json((FIXTURES_DIR / "report_offline.json").read_text(encoding="utf-8"))

    def answer(self, body: str, report: Report, history: list[QA], question: str) -> str:
        time.sleep(delay())
        return f"(오프라인 예시 답) 본문에 근거해 답하면: {report.hook} · 이전 질문 {len(history)}개 참고"


def live(settings: Settings) -> LLMClient:
    return OpenAILLM(settings)


def offline(settings: Settings) -> LLMClient:
    """Returns canned output, never calls OpenAI."""
    return OfflineLLM()
