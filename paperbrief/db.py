"""SQLite store. Schema versioned with `PRAGMA user_version`; migrations only add (ADR-0001).

Add a migration as `paperbrief/migrations/NNNN_name.sql`. The number must be higher than every migration that exists
and unique across parallel branches (tickets use ranges, e.g. 0120_...; the loader rejects a duplicate number).
Never drop or rewrite existing rows or columns. Reports stay one JSON column, so a new report format needs no migration.
"""
import re
import sqlite3
from pathlib import Path

from paperbrief.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DB_NAME = "paperbrief.db"
BUSY_TIMEOUT = 30  # seconds a writer waits for another one (collector, report worker, requests) before "database is locked"


def load_migrations(folder: Path) -> list[tuple[int, str]]:
    found: dict[int, str] = {}
    for path in sorted(folder.glob("*.sql")):
        m = re.match(r"(\d+)_", path.name)
        if not m:
            raise RuntimeError(f"migration name must start with NNNN_: {path.name}")
        version = int(m.group(1))
        if version in found:
            raise RuntimeError(f"duplicate migration number {version}: renumber {path.name}")
        found[version] = path.read_text(encoding="utf-8")
    return sorted(found.items())


def migrate(conn: sqlite3.Connection, folder: Path = MIGRATIONS_DIR) -> None:
    migrations = load_migrations(folder)
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    latest = migrations[-1][0] if migrations else 0
    if current > latest:
        raise RuntimeError(f"database is version {current}, this app only knows up to {latest}")
    for version, sql in migrations:
        if version <= current:
            continue
        try:  # each migration is atomic together with its version bump
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def init_db(settings: Settings) -> None:
    """Create the data dir and bring the database up to date. Called once by `create_app`."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.data_dir / DB_NAME, timeout=BUSY_TIMEOUT)
    try:
        migrate(conn)
    finally:
        conn.close()


def connect(settings: Settings) -> sqlite3.Connection:
    """One short-lived connection per request (see `deps.get_db`)."""
    # FastAPI enters/exits a sync dependency and runs the endpoint on different threadpool threads; the
    # connection is never shared between requests, so cross-thread use is safe.
    conn = sqlite3.connect(settings.data_dir / DB_NAME, timeout=BUSY_TIMEOUT, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
