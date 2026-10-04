"""Boundary 2/4: arXiv API (categories only). One `id_list=` query per call, never RSS, at most one request per 3 s."""
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Protocol

import httpx

from paperbrief.config import ROOT, Settings

API = "https://export.arxiv.org/api/query"
MIN_INTERVAL = 3.0  # seconds between requests (arXiv API terms)
FIXTURES_DIR = ROOT / "tests" / "fixtures"
_NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_ABS_ID = re.compile(r"/abs/(.+?)(?:v\d+)?$")


class ArxivClient(Protocol):
    def categories(self, arxiv_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        """arxiv_id -> (primary category, all categories). Owns the 3 s rate limit and User-Agent."""
        ...


def parse_categories(atom: str) -> dict[str, tuple[str, list[str]]]:
    out: dict[str, tuple[str, list[str]]] = {}
    for entry in ET.fromstring(atom).findall("a:entry", _NS):
        m = _ABS_ID.search(entry.findtext("a:id", "", _NS))
        primary = entry.find("x:primary_category", _NS)
        if not m or primary is None:  # e.g. the error entry arXiv returns for an unknown id
            continue
        main = primary.get("term", "")
        cats = [c.get("term", "") for c in entry.findall("a:category", _NS)]
        out[m.group(1)] = (main, [main] + [c for c in cats if c and c != main])
    return out


class HttpArxiv:
    """The real client. `http` is injected so a recorded response can stand in for arxiv.org."""

    def __init__(
        self,
        http: httpx.Client,
        contact: str = "",
        interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._agent = f"PaperBrief/0.1 (mailto:{contact})" if contact else "PaperBrief/0.1"
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def categories(self, arxiv_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        if not arxiv_ids:
            return {}
        if self._last is not None and (wait := self._last + self._interval - self._clock()) > 0:
            self._sleep(wait)
        self._last = self._clock()  # also counts failed requests
        res = self._http.get(
            API,
            params={"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)},
            headers={"User-Agent": self._agent},
        )
        res.raise_for_status()
        wanted = set(arxiv_ids)
        return {i: v for i, v in parse_categories(res.text).items() if i in wanted}


def live(settings: Settings) -> ArxivClient:
    return HttpArxiv(httpx.Client(timeout=30, follow_redirects=True), settings.arxiv_contact)


def offline(settings: Settings) -> ArxivClient:
    """Serves the recorded response in tests/fixtures (`PAPERBRIEF_OFFLINE=1`)."""
    body = (FIXTURES_DIR / "arxiv_id_list.xml").read_text(encoding="utf-8")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    return HttpArxiv(httpx.Client(transport=transport), settings.arxiv_contact, interval=0)
