"""수집: fetch the latest 발표일 from HF and save it. Runs on a background thread, never twice at once.

`_collect` saves the latest 발표일, then, for the last RECENT_DAYS saved days, fills missing arXiv categories and KO
summaries (one LLM call per day) and refreshes upvotes/`ai_summary` through HF `date=`. Only an HF failure fails it.
"""
import json
import logging
import threading
from datetime import date, datetime

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.db import connect

log = logging.getLogger(__name__)

RECENT_DAYS = 3

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
        latest_day, papers = self._boundaries.hf.latest_day()  # raises on failure before anything is written
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
        days = self._recent_days()
        # the new day always, plus any paper of the last days that still has no category (one lookup)
        ids = [p.arxiv_id for p in papers]
        self._attach_categories(ids + [i for i in self._without_categories(days) if i not in ids])
        for day in days:
            self._add_ko_summaries(day)
        for day in days:
            if day != latest_day.isoformat():  # the latest day was just fetched
                self._refresh(day)

    def _refresh(self, day: str) -> None:
        """New upvotes and `ai_summary` for the papers already saved on this 발표일 (HF failure fails the collection)."""
        fresh = self._boundaries.hf.day(date.fromisoformat(day))
        conn = connect(self._settings)
        try:
            with conn:
                conn.executemany(
                    "UPDATE papers SET upvotes = ?, ai_summary = ? WHERE arxiv_id = ? AND published_day = ?",
                    [(p.upvotes, p.ai_summary, p.arxiv_id, day) for p in fresh],
                )
        finally:
            conn.close()

    def _recent_days(self) -> list[str]:
        """The last RECENT_DAYS saved 발표일 (saved days, not calendar days), newest first."""
        conn = connect(self._settings)
        try:
            rows = conn.execute("SELECT DISTINCT published_day FROM papers ORDER BY published_day DESC LIMIT ?", (RECENT_DAYS,))
            return [r[0] for r in rows]
        finally:
            conn.close()

    def _without_categories(self, days: list[str]) -> list[str]:
        conn = connect(self._settings)
        try:
            marks = ",".join("?" * len(days))
            rows = conn.execute(f"SELECT arxiv_id FROM papers WHERE categories = '[]' AND published_day IN ({marks})", days)
            return [r[0] for r in rows]
        finally:
            conn.close()

    def _add_ko_summaries(self, day: str) -> None:
        """One LLM call for the papers of this 발표일 that have no KO summary. A failure only leaves them for next time."""
        conn = connect(self._settings)
        try:
            todo = [
                (r["arxiv_id"], r["title"], r["abstract"])
                for r in conn.execute("SELECT * FROM papers WHERE published_day = ? AND summary_ko = ''", (day,))
            ]
            if not todo:
                return
            try:
                found = self._boundaries.llm.summarize_ko(todo)
            except Exception as exc:  # no key, network, refusal...: the papers are saved either way
                log.warning("KO summaries for %s failed: %s", day, exc)
                return
            with conn:
                conn.executemany(
                    "UPDATE papers SET summary_ko = ? WHERE arxiv_id = ?",
                    [(found[i].strip(), i) for i, _, _ in todo if found.get(i, "").strip()],
                )
        finally:
            conn.close()
