"""원문 그림 images: served from the paper's parsed folder, only the files a 그림 후보 names."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from paperbrief import figures
from paperbrief.deps import DbDep
from paperbrief.routes.reports import WorkerDep

router = APIRouter(prefix="/api")


@router.get("/papers/{arxiv_id}/figures/{figure_id}/{panel}")
def figure_image(arxiv_id: str, figure_id: str, panel: int, db: DbDep, worker: WorkerDep) -> FileResponse:
    if db.execute("SELECT 1 FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone() is None:
        raise HTTPException(404)
    parsed = worker.parsed_dir(arxiv_id)
    for c in figures.load(parsed):
        if c.id == figure_id and 0 <= panel < len(c.images):
            # the paths were checked when the candidate was built; check again, the JSON is a file on disk
            path = figures.inside(parsed, str(c.images[panel]))
            if path is not None:
                return FileResponse(path)
    raise HTTPException(404)
