"""Fakes for the four boundaries. Feature tickets extend these (or add fixture-backed ones) in their own tests."""
from datetime import date
from pathlib import Path

from paperbrief.boundaries import Boundaries
from paperbrief.hf import HFPaper
from paperbrief.llm import QA, Report
from paperbrief.parser import FigureCandidate, ParseResult


class FakeHF:
    def __init__(self, days: dict[date, list[HFPaper]] | None = None) -> None:
        self.days = days or {}

    def latest_day(self) -> tuple[date, list[HFPaper]]:
        latest = max(self.days)
        return latest, self.days[latest]

    def day(self, day: date) -> list[HFPaper]:
        return self.days.get(day, [])


class FakeArxiv:
    def __init__(self, cats: dict[str, tuple[str, list[str]]] | None = None) -> None:
        self.cats = cats or {}
        self.calls: list[list[str]] = []

    def categories(self, arxiv_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        self.calls.append(arxiv_ids)
        return {i: self.cats[i] for i in arxiv_ids if i in self.cats}


class FakeLLM:
    """Records inputs, returns canned output."""

    def __init__(self, report: Report | None = None) -> None:
        self.report = report
        self.calls: list[tuple[str, tuple]] = []  # write_report / answer
        self.ko_requests: list[list[tuple[str, str, str]]] = []  # one entry per summarize_ko call (every collection makes some)

    def summarize_ko(self, papers: list[tuple[str, str, str]]) -> dict[str, str]:
        self.ko_requests.append(papers)
        return {i: f"KO {title}" for i, title, _ in papers}

    def write_report(self, body: str, figures: list[FigureCandidate]) -> Report:
        self.calls.append(("write_report", (body, figures)))
        assert self.report is not None, "FakeLLM needs a canned report"
        return self.report

    def answer(self, body: str, report: Report, history: list[QA], question: str) -> str:
        self.calls.append(("answer", (body, report, history, question)))
        return f"answer to {question}"


class FakeParser:
    def __init__(self, result: ParseResult | None = None) -> None:
        self.result = result or ParseResult(markdown="")
        self.calls: list[tuple[Path, Path]] = []

    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        self.calls.append((pdf, out_dir))
        return self.result


def fake_boundaries() -> Boundaries:
    return Boundaries(hf=FakeHF(), arxiv=FakeArxiv(), llm=FakeLLM(), parser=FakeParser())
