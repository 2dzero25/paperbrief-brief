"""질문 API: ask about a finished 보고서, list this paper's saved Q&A (oldest first).

Q&A rows live in `questions`, keyed by paper and never touched by the report, so a 다시 작성 (#12) keeps them.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paperbrief.deps import BoundariesDep, DbDep, SettingsDep
from paperbrief.llm import QA, Report
from paperbrief.parser import ParseResult
from paperbrief.reports import DONE

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)


class Ask(BaseModel):
    question: str = Field(min_length=1)


def saved(db, arxiv_id: str) -> list[dict]:
    rows = db.execute("SELECT id, question, answer, asked_at FROM questions WHERE arxiv_id = ? ORDER BY id", (arxiv_id,))
    return [dict(r) for r in rows]


def known_paper(db, arxiv_id: str) -> None:
    if db.execute("SELECT 1 FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone() is None:
        raise HTTPException(404, "unknown paper")


@router.get("/papers/{arxiv_id}/questions")
def list_questions(arxiv_id: str, db: DbDep) -> dict:
    known_paper(db, arxiv_id)
    return {"questions": saved(db, arxiv_id)}


@router.post("/papers/{arxiv_id}/questions")
def ask(arxiv_id: str, body: Ask, db: DbDep, settings: SettingsDep, boundaries: BoundariesDep) -> dict:
    known_paper(db, arxiv_id)
    row = db.execute("SELECT status, report_json FROM reports WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
    if row is None or row["status"] != DONE or not row["report_json"]:
        raise HTTPException(409, "보고서가 완료되지 않음")
    report = Report.model_validate_json(row["report_json"])
    text = ParseResult.load(settings.data_dir / "papers" / arxiv_id / "parsed").markdown
    history = [QA(question=q["question"], answer=q["answer"]) for q in saved(db, arxiv_id)]
    try:
        answer = boundaries.llm.answer(text, report, history, body.question)
    except Exception as e:  # nothing is saved: the page keeps the question text and offers [다시]
        log.exception("answer for %s failed", arxiv_id)
        raise HTTPException(502, str(e)) from e
    asked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db:
        cur = db.execute(
            "INSERT INTO questions (arxiv_id, question, answer, asked_at) VALUES (?, ?, ?, ?)",
            (arxiv_id, body.question, answer, asked_at),
        )
    return {"id": cur.lastrowid, "question": body.question, "answer": answer, "asked_at": asked_at}
