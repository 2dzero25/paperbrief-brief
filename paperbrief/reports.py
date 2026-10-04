"""보고서 worker: one in-process thread, FIFO, one paper at a time, three 단계 (PDF -> 파싱 -> 작성).

Not a scheduler: it only runs while the app runs, and it is independent of the Collector. Every stage leaves its
result on disk (or, for 작성, in `reports.report_json`) and is skipped when that result already exists, so running a
paper again continues at the first stage without a result. Cancelling a queued paper is deliberately not possible.

Extension points for later tickets:
  - `STAGES`: (name, done, run) triples. #8 wraps/extends `run_parse` (CPU fallback) and the failure bookkeeping in
    `_process`; the failure path already records status 실패 + stage + traceback and never kills the thread.
  - `ReportWorker.enqueue(rewrite=True)`: #12 [다시 작성] sets `reports.rewrite`, so only 작성 runs again (`write_done` is
    false until the new report is saved; the old `report_json` stays meanwhile).
  - `Work`: what a stage can see; #9/#10 read `Work.parsed` / the parse result from there.
"""
import logging
import queue
import sqlite3
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI

from paperbrief import figures
from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.db import connect
from paperbrief.parser import RESULT_FILE, ParseResult

log = logging.getLogger(__name__)

QUEUED, RUNNING, DONE, FAILED = "대기", "진행 중", "완료", "실패"
PDF_URL = "https://arxiv.org/pdf/{}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Work:
    """One paper being worked on. Files live under `<data dir>/papers/<arxiv id>/` and are never deleted."""

    arxiv_id: str
    folder: Path
    boundaries: Boundaries
    http: httpx.Client
    conn: sqlite3.Connection

    @property
    def pdf(self) -> Path:
        return self.folder / "paper.pdf"

    @property
    def parsed(self) -> Path:  # the parser's output folder plus our `parse_result.json`
        return self.folder / "parsed"

    def report_json(self) -> str:
        row = self.conn.execute("SELECT report_json FROM reports WHERE arxiv_id = ?", (self.arxiv_id,)).fetchone()
        return row["report_json"] if row else ""


def pdf_done(w: Work) -> bool:
    return w.pdf.is_file()


def run_pdf(w: Work) -> None:
    res = w.http.get(PDF_URL.format(w.arxiv_id))
    res.raise_for_status()
    w.folder.mkdir(parents=True, exist_ok=True)
    part = w.pdf.with_name("paper.pdf.part")  # a half-written download must not look like a finished stage
    part.write_bytes(res.content)
    part.replace(w.pdf)


def parse_done(w: Work) -> bool:
    return (w.parsed / RESULT_FILE).is_file()


def run_parse(w: Work) -> None:
    w.parsed.mkdir(parents=True, exist_ok=True)
    result = w.boundaries.parser.parse(w.pdf, w.parsed)
    replace(result, figures=figures.extract(w.parsed, result.markdown)).save(w.parsed)  # 그림 후보 from MinerU's folder


def write_done(w: Work) -> bool:
    row = w.conn.execute("SELECT report_json, rewrite FROM reports WHERE arxiv_id = ?", (w.arxiv_id,)).fetchone()
    return bool(row and row["report_json"] and not row["rewrite"])  # a pending 다시 작성 keeps the old json but is not done


def run_write(w: Work) -> None:
    parsed = ParseResult.load(w.parsed)
    report = w.boundaries.llm.write_report(parsed.markdown, parsed.figures)
    if report.repro is None:  # the field is optional only so reports stored before #10 load; a new one must have it
        raise RuntimeError("repro 누락: 모델이 재현 체크를 돌려주지 않음")
    report.figures = figures.pick(report.figures, parsed.figures)  # only ids that are candidates, at most two
    w.conn.execute("UPDATE reports SET report_json = ?, rewrite = 0 WHERE arxiv_id = ?", (report.model_dump_json(), w.arxiv_id))
    w.conn.commit()


STAGES: list[tuple[str, Callable[[Work], bool], Callable[[Work], None]]] = [
    ("PDF", pdf_done, run_pdf),
    ("파싱", parse_done, run_parse),
    ("작성", write_done, run_write),
]


class ReportWorker:
    def __init__(self, settings: Settings, boundaries: Boundaries, http: Callable[[], httpx.Client]) -> None:
        self._settings = settings
        self._boundaries = boundaries
        self._http = http  # asked for when a paper is processed, so a test can set `app.state.pdf_http` after the app exists
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._waiting: list[str] = []  # FIFO order, for 대기 순번
        self._current: str | None = None
        self._thread: threading.Thread | None = None

    def parsed_dir(self, arxiv_id: str) -> Path:
        return self._settings.data_dir / "papers" / arxiv_id / "parsed"

    def queue_position(self, arxiv_id: str) -> int | None:
        """1 = next in line. None when the paper is not waiting."""
        with self._lock:
            return self._waiting.index(arxiv_id) + 1 if arxiv_id in self._waiting else None

    def enqueue(self, arxiv_id: str, rewrite: bool = False) -> None:
        """Make the report (or continue a failed one). Does nothing for a finished or already queued paper.

        `rewrite` (a 완료 report only) owes 작성 again; the old `report_json` stays until a new one is saved."""
        with self._lock:
            if arxiv_id in self._waiting or arxiv_id == self._current:
                return
            conn = connect(self._settings)
            try:
                row = conn.execute("SELECT status FROM reports WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
                if row and row["status"] == DONE and not rewrite:
                    return
                if rewrite and not (row and row["status"] == DONE):
                    return
                stamp = now()
                with conn:
                    conn.execute(
                        "INSERT INTO reports (arxiv_id, status, created_at, updated_at) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT (arxiv_id) DO UPDATE SET status = ?, error_log = '', updated_at = ?, rewrite = MAX(rewrite, ?)",
                        (arxiv_id, QUEUED, stamp, stamp, QUEUED, stamp, int(rewrite)),
                    )
            finally:
                conn.close()
            self._waiting.append(arxiv_id)
            self._queue.put(arxiv_id)
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="report-worker", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        while True:
            arxiv_id = self._queue.get()
            with self._lock:
                self._waiting.remove(arxiv_id)
                self._current = arxiv_id
            try:
                self._process(arxiv_id)
            except Exception:  # whatever happens to one paper, the next one still runs
                log.exception("report worker failed on %s", arxiv_id)
            with self._lock:
                self._current = None

    def _process(self, arxiv_id: str) -> None:
        conn = connect(self._settings)
        try:
            work = Work(arxiv_id, self._settings.data_dir / "papers" / arxiv_id, self._boundaries, self._http(), conn)
            self._set(conn, arxiv_id, status=RUNNING)
            for name, done, run in STAGES:
                if done(work):
                    continue
                self._set(conn, arxiv_id, status=RUNNING, stage=name, stage_started_at=now())
                try:
                    run(work)
                except Exception:
                    log.exception("report %s failed in %s", arxiv_id, name)
                    self._set(conn, arxiv_id, status=FAILED, stage=name, error_log=traceback.format_exc())
                    return
            self._set(conn, arxiv_id, status=DONE)
        finally:
            conn.close()

    @staticmethod
    def _set(conn: sqlite3.Connection, arxiv_id: str, **cols: str) -> None:
        cols["updated_at"] = now()
        sets = ", ".join(f"{c} = ?" for c in cols)
        with conn:
            conn.execute(f"UPDATE reports SET {sets} WHERE arxiv_id = ?", (*cols.values(), arxiv_id))


def default_http(settings: Settings) -> httpx.Client:
    if settings.offline:  # no network: every PDF is a tiny canned file
        return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"%PDF-1.4 offline")))
    return httpx.Client(timeout=60, follow_redirects=True)


def recover_interrupted(settings: Settings, boundaries: Boundaries) -> None:
    """On app start: a report still `대기`/`진행 중` was cut off by the app being switched off, so it becomes `실패`.

    The stage is the one that was running; a waiting report failed at the first stage it had no result for yet."""
    conn = connect(settings)
    try:
        with default_http(settings) as http:  # the done-checks only look at disk and DB, the client is never used
            for row in conn.execute("SELECT arxiv_id, status, stage FROM reports WHERE status IN (?, ?)", (QUEUED, RUNNING)).fetchall():
                work = Work(row["arxiv_id"], settings.data_dir / "papers" / row["arxiv_id"], boundaries, http, conn)
                stage = row["stage"] if row["status"] == RUNNING else next((n for n, done, _ in STAGES if not done(work)), "")
                ReportWorker._set(conn, row["arxiv_id"], status=FAILED, stage=stage, error_log="앱 종료로 중단")
    finally:
        conn.close()


_http_lock = threading.Lock()


def http_for(app: FastAPI) -> httpx.Client:
    """The PDF client: `app.state.pdf_http` (tests fake arxiv.org there), else a real one made on first use."""
    with _http_lock:
        if getattr(app.state, "pdf_http", None) is None:
            app.state.pdf_http = default_http(app.state.settings)
        return app.state.pdf_http
