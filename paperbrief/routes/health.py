"""Liveness plus the few facts the page needs about the setup."""
from fastapi import APIRouter

from paperbrief.deps import DbDep, SettingsDep

router = APIRouter(prefix="/api")


@router.get("/health")
def health(settings: SettingsDep, db: DbDep) -> dict:
    return {
        "ok": True,
        "offline": settings.offline,
        "openai_configured": bool(settings.openai_api_key),
        "db_version": db.execute("PRAGMA user_version").fetchone()[0],
    }
