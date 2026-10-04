"""App factory. All state a route needs is on `app.state`; routes reach it through `paperbrief.deps`."""
import importlib
import pkgutil

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from paperbrief import boundaries as boundary_factories
from paperbrief import routes
from paperbrief.boundaries import Boundaries
from paperbrief.config import STATIC_DIR, Settings
from paperbrief.db import init_db


def create_app(settings: Settings, boundaries: Boundaries | None = None) -> FastAPI:
    """`boundaries=None` picks offline fixtures when `settings.offline`, else the live clients."""
    if boundaries is None:
        boundaries = boundary_factories.offline(settings) if settings.offline else boundary_factories.live(settings)
    init_db(settings)
    app = FastAPI(title="PaperBrief")
    app.state.settings = settings
    app.state.boundaries = boundaries
    # Every module in paperbrief/routes/ that defines `router` is registered: a feature adds a file, edits nothing here.
    for mod in pkgutil.iter_modules(routes.__path__):
        app.include_router(importlib.import_module(f"{routes.__name__}.{mod.name}").router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
