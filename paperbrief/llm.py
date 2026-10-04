"""Boundary 3/4: OpenAI Responses API. The collection (summaries) and report/question tickets implement it."""
import time
from typing import Protocol

import httpx
from openai import OpenAI
from pydantic import BaseModel

from paperbrief import report_prompt
from paperbrief.config import Settings
from paperbrief.hf import FIXTURES_DIR
from paperbrief.offline import delay, fail_once
from paperbrief.parser import FigureCandidate


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


class QA(BaseModel):
    question: str
    answer: str


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


class OpenAILLM(_Unimplemented):
    """The real client. `summarize_ko` (#6) and `answer` (#11) are still the NotImplementedError of the base class."""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._http_client = http_client  # tests stand in for api.openai.com here

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


class OfflineLLM(_Unimplemented):
    """Canned report from tests/fixtures; `PAPERBRIEF_OFFLINE_DELAY` seconds of fake work make the progress watchable."""

    def write_report(self, body: str, figures: list[FigureCandidate]) -> Report:
        time.sleep(delay())
        fail_once("작성")
        return Report.model_validate_json((FIXTURES_DIR / "report_offline.json").read_text(encoding="utf-8"))


def live(settings: Settings) -> LLMClient:
    return OpenAILLM(settings)


def offline(settings: Settings) -> LLMClient:
    """Returns canned output, never calls OpenAI."""
    return OfflineLLM()
