"""FastAPI dependencies. Use these in routes instead of reaching into `request.app.state`."""
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from paperbrief.boundaries import Boundaries
from paperbrief.config import Settings
from paperbrief.db import connect


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_boundaries(request: Request) -> Boundaries:
    return request.app.state.boundaries


SettingsDep = Annotated[Settings, Depends(get_settings)]
BoundariesDep = Annotated[Boundaries, Depends(get_boundaries)]


def get_db(settings: SettingsDep) -> Iterator[sqlite3.Connection]:
    """One short-lived connection per request; commit explicitly when writing."""
    conn = connect(settings)
    try:
        yield conn
    finally:
        conn.close()


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
