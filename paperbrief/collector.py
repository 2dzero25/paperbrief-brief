"""수집: fetch the latest 발표일 from HF and save it. Runs on a background thread, never twice at once.

Later tickets extend `_collect` (arXiv categories, KO summaries, refreshing the last 3 days).
"""
import json
import logging
import threading
from datetime import datetime

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.db import connect

log = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO papers (arxiv_id, published_day, title, abstract, organization, upvotes, ai_summary, code_url)
VALUES (:arxiv_id, :published_day, :title, :abstract, :organization, :upvotes, :ai_summary, :code_url)
ON CONFLICT (arxiv_id) DO UPDATE SET
    published_day = excluded.published_day, title = excluded.title, abstract = excluded.abstract,
    organization = excluded.organization, upvotes = excluded.upvotes, ai_summary = excluded.ai_summary,
    code_url = excluded.code_url
"""


class Collector:
    def __init__(self, settings: Settings, boundaries: Boundaries) -> None:
        self._settings = settings
        self._boundaries = boundaries
        self._lock = threading.Lock()
        self._running = False
        self._error: str | None = None
        self._finished_at: str | None = None

    def state(self) -> dict:
        with self._lock:
            return {"running": self._running, "error": self._error, "finished_at": self._finished_at}

    def start(self) -> bool:
        """Start a collection in the background. False when one is already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._error = None
        threading.Thread(target=self._run, name="collector", daemon=True).start()
        return True

    def _run(self) -> None:
        error = None
        try:
            self._collect()
        except Exception as exc:  # any failure leaves the previous list untouched
            log.exception("collection failed")
            error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._error = error
            self._finished_at = datetime.now().isoformat(timespec="seconds")
            self._running = False

    def _attach_categories(self, arxiv_ids: list[str]) -> None:
        """One arXiv lookup for these ids. A failure is only logged: the papers stay saved, without a category."""
        try:
            found = self._boundaries.arxiv.categories(arxiv_ids)
        except Exception:
            log.exception("arXiv category lookup failed")
            return
        conn = connect(self._settings)
        try:
            with conn:
                conn.executemany(
                    "UPDATE papers SET primary_category = ?, categories = ? WHERE arxiv_id = ?",
                    [(primary, json.dumps(cats), i) for i, (primary, cats) in found.items()],
                )
        finally:
            conn.close()

    def _collect(self) -> None:
        _, papers = self._boundaries.hf.latest_day()  # raises on failure before anything is written
        conn = connect(self._settings)
        try:
            with conn:  # one transaction: all of the day or nothing
                conn.executemany(
                    _UPSERT,
                    [
                        {
                            "arxiv_id": p.arxiv_id,
                            "published_day": p.published_day.isoformat(),
                            "title": p.title,
                            "abstract": p.abstract,
                            "organization": p.organization,
                            "upvotes": p.upvotes,
                            "ai_summary": p.ai_summary,
                            "code_url": p.code_url,
                        }
                        for p in papers
                    ],
                )
        finally:
            conn.close()
        self._attach_categories([p.arxiv_id for p in papers])
