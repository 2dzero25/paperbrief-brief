"""수집 and the 카드 list of the most recent saved 발표일.

Later tickets extend `list_papers` (KO summary) and reuse `collector_of`.
"""
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from paperbrief.collector import Collector
from paperbrief.deps import DbDep


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.collector.start()  # every app start collects in the background
    yield


router = APIRouter(prefix="/api", lifespan=lifespan)


def collector_of(request: Request) -> Collector:
    return request.app.state.collector  # created by `create_app`


CollectorDep = Annotated[Collector, Depends(collector_of)]


def get_today() -> date:
    return datetime.now(timezone.utc).date()  # 발표일 are UTC dates, so "today" is too; a dependency so tests can pick the day


TodayDep = Annotated[date, Depends(get_today)]

# upvotes high to low; among equals, papers with a 등록 코드 first. A paper matches a category when any of its
# categories does (papers without categories only show when no category is chosen).
_LIST = """
SELECT * FROM papers WHERE published_day = :day
  AND (:category = '' OR EXISTS (SELECT 1 FROM json_each(categories) WHERE value = :category))
  AND (NOT :code OR code_url != '')
ORDER BY upvotes DESC, (code_url != '') DESC, arxiv_id
"""
# chips: every category present that day, most papers first
_CHIPS = """
SELECT value AS category, count(*) AS count FROM papers, json_each(categories)
WHERE published_day = :day GROUP BY value ORDER BY count DESC, value
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
def list_papers(db: DbDep, today: TodayDep, day: str = "", category: str = "", code: bool = False) -> dict:
    days = [r[0] for r in db.execute("SELECT DISTINCT published_day FROM papers ORDER BY published_day")]
    if not days:
        return {"day": None, "recent": False, "count": 0, "papers": [], "categories": [], "prev_day": None, "next_day": None}
    day = day or days[-1]
    if day not in days:  # ◀ ▶ only walk saved 발표일, nothing is backfilled
        raise HTTPException(404, "no papers saved for that day")
    i = days.index(day)
    papers = [card(r) for r in db.execute(_LIST, {"day": day, "category": category, "code": code})]
    return {
        "day": day,
        # "최근": the newest 발표일 is not today (weekend, holiday, or HF has not posted yet)
        "recent": day == days[-1] and day != today.isoformat(),
        "count": len(papers),  # follows the filters
        "papers": papers,
        "categories": [dict(r) for r in db.execute(_CHIPS, {"day": day})],  # the whole day, whatever the filters
        "prev_day": days[i - 1] if i > 0 else None,
        "next_day": days[i + 1] if i + 1 < len(days) else None,
    }


@router.post("/collect", status_code=202)
def start_collect(collector: CollectorDep) -> dict:
    collector.start()  # already running: same answer, no second run
    return collector.state()


@router.get("/collect")
def collect_state(collector: CollectorDep) -> dict:
    return collector.state()
