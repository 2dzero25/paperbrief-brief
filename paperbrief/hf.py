"""Boundary 1/4: Hugging Face Daily Papers."""
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx

from paperbrief.config import ROOT, Settings

API = "https://huggingface.co/api/daily_papers"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


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


def _to_paper(item: dict) -> HFPaper:
    p = item["paper"]
    org = p.get("organization") or {}
    return HFPaper(
        arxiv_id=p["id"],
        published_day=date.fromisoformat(p["submittedOnDailyAt"][:10]),  # 발표일; `publishedAt` is the arXiv date
        title=p["title"],
        abstract=p.get("summary", ""),
        organization=org.get("fullname") or org.get("name", ""),
        upvotes=p.get("upvotes", 0),
        ai_summary=p.get("ai_summary", ""),
        code_url=p.get("githubRepo", ""),
        # the item's `thumbnail` is deliberately never read: its URL can expose an author's email
    )


class HttpHF:
    """The real client. `http` is injected so recorded responses can stand in for huggingface.co."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def _walk(self, params: dict[str, str | int], first_day: date | None) -> tuple[date | None, list[HFPaper]]:
        """Read pages, following `Link rel=next`, until an item of another 발표일 shows up."""
        papers: list[HFPaper] = []
        url: str | None = API
        while url:
            res = self._http.get(url, params=params if url == API else None)
            if res.status_code == 400:  # `date` after the latest 발표일
                break
            res.raise_for_status()
            for item in res.json():
                paper = _to_paper(item)
                first_day = first_day or paper.published_day
                if paper.published_day != first_day:
                    return first_day, papers
                papers.append(paper)
            url = res.links.get("next", {}).get("url")
        return first_day, papers

    def latest_day(self) -> tuple[date, list[HFPaper]]:
        day, papers = self._walk({"limit": 100}, None)
        if day is None:
            raise RuntimeError("HF returned no papers")
        return day, papers

    def day(self, day: date) -> list[HFPaper]:
        return self._walk({"limit": 100, "date": day.isoformat()}, day)[1]


def fixture_handler(pages: list[list[dict]]) -> Callable[[httpx.Request], httpx.Response]:
    """Serve recorded pages like huggingface.co: `?p=N` picks the page, `Link rel=next` points at the following one."""

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params.get("p", "0"))
        if n >= len(pages):
            return httpx.Response(404, json={"error": "no such page"})
        headers = {}
        if n + 1 < len(pages):
            headers["Link"] = f'<{API}?limit=100&p={n + 1}>; rel="next"'
        return httpx.Response(200, json=pages[n], headers=headers)

    return handler


def live(settings: Settings) -> HFClient:
    return HttpHF(httpx.Client(timeout=30, follow_redirects=True))


def offline(settings: Settings) -> HFClient:
    """Serves the recorded pages in tests/fixtures (`PAPERBRIEF_OFFLINE=1`)."""
    pages = [json.loads((FIXTURES_DIR / f"hf_daily_page{n}.json").read_text(encoding="utf-8")) for n in (0, 1)]
    return HttpHF(httpx.Client(transport=httpx.MockTransport(fixture_handler(pages))))
