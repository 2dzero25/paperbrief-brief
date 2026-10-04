"""Boundary 1/4: Hugging Face Daily Papers. The collection ticket implements `live()` and `offline()`."""
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from paperbrief.config import Settings


@dataclass(frozen=True)
class HFPaper:
    arxiv_id: str
    published_day: date  # 발표일
    title: str
    abstract: str
    organization: str = ""
    upvotes: int = 0
    ai_summary: str = ""  # EN one-liner HF sometimes fills in later
    code_url: str = ""  # 등록 코드


class HFClient(Protocol):
    def latest_day(self) -> tuple[date, list[HFPaper]]:
        """All papers of the most recent 발표일 (follows `Link rel=next`, no 50-item cap)."""
        ...

    def day(self, day: date) -> list[HFPaper]:
        """Papers of one 발표일; used to refresh upvotes."""
        ...


class _Unimplemented:
    def latest_day(self) -> tuple[date, list[HFPaper]]:
        raise NotImplementedError("HF client not implemented yet")

    def day(self, day: date) -> list[HFPaper]:
        raise NotImplementedError("HF client not implemented yet")


def live(settings: Settings) -> HFClient:
    return _Unimplemented()


def offline(settings: Settings) -> HFClient:
    """Serves recorded fixtures from tests/fixtures."""
    return _Unimplemented()
