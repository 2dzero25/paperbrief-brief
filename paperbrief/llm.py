"""Boundary 3/4: OpenAI Responses API. The collection (summaries) and report/question tickets implement it."""
from typing import Literal, Protocol

from pydantic import BaseModel

from paperbrief.config import Settings
from paperbrief.parser import FigureCandidate

Verdict = Literal["공개", "비공개", "명시 없음"]


class ReproItem(BaseModel):
    verdict: Verdict
    evidence: str


class Repro(BaseModel):
    code: ReproItem
    weights: ReproItem
    data: ReproItem
    gpu: ReproItem
    license: ReproItem


class Report(BaseModel):
    """The JSON stored in one column of the reports table (ADR-0001)."""

    hook: str
    figures: list[str]  # 그림 후보 ids, 0-2
    method: str
    results: str
    difference: str
    meaning: str
    limitations: str
    repro: Repro


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


def live(settings: Settings) -> LLMClient:
    return _Unimplemented()


def offline(settings: Settings) -> LLMClient:
    """Returns canned output, never calls OpenAI."""
    return _Unimplemented()
