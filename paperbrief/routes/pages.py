"""The single static HTML page."""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from paperbrief.config import STATIC_DIR

router = APIRouter()


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
