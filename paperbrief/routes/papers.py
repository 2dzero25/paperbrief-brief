"""수집 and the 카드 list of the most recent saved 발표일.

Later tickets extend `list_papers` (filters, date navigation, KO summary) and reuse `collector_of`.
"""
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request

from paperbrief.collector import Collector
from paperbrief.deps import DbDep

def collector_for(app: FastAPI) -> Collector:
    if not hasattr(app.state, "collector"):  # one per app, created on first use
        app.state.collector = Collector(app.state.settings, app.state.boundaries)
    return app.state.collector


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    collector_for(app).start()  # every app start collects in the background
    yield


router = APIRouter(prefix="/api", lifespan=lifespan)


def collector_of(request: Request) -> Collector:
    return collector_for(request.app)


CollectorDep = Annotated[Collector, Depends(collector_of)]


def get_today() -> date:
    return date.today()  # a dependency so tests can pick the day


TodayDep = Annotated[date, Depends(get_today)]

# upvotes high to low; among equals, papers with a 등록 코드 first
_LIST = """
SELECT * FROM papers WHERE published_day = :day
ORDER BY upvotes DESC, (code_url != '') DESC, arxiv_id
"""


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def card(row) -> dict:
    return {
        "arxiv_id": row["arxiv_id"],
        "title": row["title"],
        "upvotes": row["upvotes"],
        "summary_en": row["ai_summary"] or first_sentence(row["abstract"]),
        "summary_ko": row["summary_ko"],
        "organization": row["organization"],
        "primary_category": row["primary_category"],
        "categories": json.loads(row["categories"]),
        "has_code": bool(row["code_url"]),
        "code_url": row["code_url"],
    }


@router.get("/papers")
def list_papers(db: DbDep, today: TodayDep) -> dict:
    latest = db.execute("SELECT max(published_day) FROM papers").fetchone()[0]
    if latest is None:
        return {"day": None, "recent": False, "count": 0, "papers": []}
    papers = [card(r) for r in db.execute(_LIST, {"day": latest})]
    # "최근": the newest 발표일 is not today (weekend, holiday, or HF has not posted yet)
    return {"day": latest, "recent": latest != today.isoformat(), "count": len(papers), "papers": papers}


@router.post("/collect", status_code=202)
def start_collect(collector: CollectorDep) -> dict:
    collector.start()  # already running: same answer, no second run
    return collector.state()


@router.get("/collect")
def collect_state(collector: CollectorDep) -> dict:
    return collector.state()
