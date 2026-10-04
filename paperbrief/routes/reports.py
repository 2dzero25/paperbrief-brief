"""보고서 API: ask for one, read its state (the page polls), list the states for the card dots.

`GET /api/papers/{id}/report` is the one shape the report screen renders; later tickets add keys to it (additively).
"""
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from paperbrief.deps import DbDep
from paperbrief.reports import DONE, RUNNING, ReportWorker, worker_for

router = APIRouter(prefix="/api")


def worker_of(request: Request) -> ReportWorker:
    app: FastAPI = request.app
    return worker_for(app)


WorkerDep = Annotated[ReportWorker, Depends(worker_of)]


def elapsed_seconds(row) -> int | None:
    if row["status"] != RUNNING or not row["stage_started_at"]:
        return None
    return max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(row["stage_started_at"])).total_seconds()))


def short_state(row, worker: ReportWorker) -> dict:
    """What a card needs: status dot plus the progress text."""
    return {
        "status": row["status"],
        "stage": row["stage"],
        "elapsed": elapsed_seconds(row),
        "queue_position": worker.queue_position(row["arxiv_id"]),
    }


def paper_header(p) -> dict:
    return {
        "title": p["title"],
        "primary_category": p["primary_category"],
        "categories": json.loads(p["categories"]),
        "organization": p["organization"],
        "published_day": p["published_day"],
        "upvotes": p["upvotes"],
        "code_url": p["code_url"],
    }


def header_links(arxiv_id: str, code_url: str) -> list[dict]:
    """arXiv, PDF, and GitHub only when a 등록 코드 exists."""
    links = [{"label": "arXiv", "url": f"https://arxiv.org/abs/{arxiv_id}"},
             {"label": "PDF", "url": f"https://arxiv.org/pdf/{arxiv_id}"}]  # fmt: skip
    return links + [{"label": "GitHub", "url": code_url}] if code_url else links


def full_state(db, worker: ReportWorker, arxiv_id: str) -> dict:
    paper = db.execute("SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
    if paper is None:
        raise HTTPException(404, "unknown paper")
    row = db.execute("SELECT * FROM reports WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
    state = {"arxiv_id": arxiv_id, "paper": paper_header(paper), "links": header_links(arxiv_id, paper["code_url"]), "status": None, "stage": "", "elapsed": None,
             "queue_position": None, "error_log": "", "report": None}
    if row is not None:
        state |= short_state(row, worker)
        state["error_log"] = row["error_log"]
        state["report"] = json.loads(row["report_json"]) if row["report_json"] else None
    return state


@router.post("/papers/{arxiv_id}/report", status_code=202)
def make_report(arxiv_id: str, db: DbDep, worker: WorkerDep) -> dict:
    """Card click: start the report, or join the queue; an existing one is just returned (never regenerated)."""
    full_state(db, worker, arxiv_id)  # 404 for an unknown paper
    worker.enqueue(arxiv_id)
    return full_state(db, worker, arxiv_id)


@router.post("/papers/{arxiv_id}/report/rewrite", status_code=202)
def rewrite_report(arxiv_id: str, db: DbDep, worker: WorkerDep) -> dict:
    """[다시 작성]: only a 완료 report, only 작성 runs again, the old report stays until the new one is saved."""
    if full_state(db, worker, arxiv_id)["status"] != DONE:
        raise HTTPException(409, "완료된 보고서만 다시 작성할 수 있음")
    worker.enqueue(arxiv_id, rewrite=True)
    return full_state(db, worker, arxiv_id)


@router.get("/papers/{arxiv_id}/report")
def get_report(arxiv_id: str, db: DbDep, worker: WorkerDep) -> dict:
    return full_state(db, worker, arxiv_id)


@router.get("/reports")
def list_reports(db: DbDep, worker: WorkerDep) -> dict:
    return {"reports": {r["arxiv_id"]: short_state(r, worker) for r in db.execute("SELECT * FROM reports")}}
