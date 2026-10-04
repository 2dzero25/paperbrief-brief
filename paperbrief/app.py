"""App factory. All state a route needs is on `app.state`; routes reach it through `paperbrief.deps`."""
import importlib
import pkgutil

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from paperbrief import boundaries as boundary_factories
from paperbrief import routes
from paperbrief.boundaries import Boundaries
from paperbrief.collector import Collector
from paperbrief.config import STATIC_DIR, Settings
from paperbrief.db import init_db
from paperbrief.guard import add_origin_guard
from paperbrief.reports import ReportWorker, http_for, recover_interrupted


def create_app(settings: Settings, boundaries: Boundaries | None = None) -> FastAPI:
    """`boundaries=None` picks offline fixtures when `settings.offline`, else the live clients."""
    if boundaries is None:
        boundaries = boundary_factories.offline(settings) if settings.offline else boundary_factories.live(settings)
    init_db(settings)
    recover_interrupted(settings, boundaries)
    app = FastAPI(title="PaperBrief")
    app.state.settings = settings
    add_origin_guard(app, settings.port)
    app.state.boundaries = boundaries
    # the one collector and the one report worker are made here, not on first request, so two first requests cannot make two
    app.state.collector = Collector(settings, boundaries)
    app.state.report_worker = ReportWorker(settings, boundaries, lambda: http_for(app))
    # Every module in paperbrief/routes/ that defines `router` is registered: a feature adds a file, edits nothing here.
    for mod in pkgutil.iter_modules(routes.__path__):
        app.include_router(importlib.import_module(f"{routes.__name__}.{mod.name}").router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
