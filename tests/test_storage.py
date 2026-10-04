"""Seam: the SQLite store under the data dir, opened by create_app (ADR-0001: PRAGMA user_version, additive-only)."""
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperbrief.app import create_app
from paperbrief.config import Settings
from paperbrief.db import migrate
from tests.fakes import fake_boundaries


def test_app_creates_data_dir_and_database_outside_repo(make_client, tmp_path: Path):
    res = make_client().get("/api/health")
    assert res.status_code == 200
    assert res.json()["db_version"] >= 1
    assert (tmp_path / "data" / "paperbrief.db").is_file()


def test_reopening_keeps_existing_rows(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    create_app(settings, fake_boundaries())
    with sqlite3.connect(settings.data_dir / "paperbrief.db") as conn:
        conn.execute("INSERT INTO papers (arxiv_id, published_day, title) VALUES ('2610.00001', '2026-10-02', 'kept')")
    client = TestClient(create_app(settings, fake_boundaries()))
    assert client.get("/api/health").status_code == 200
    with sqlite3.connect(settings.data_dir / "paperbrief.db") as conn:
        assert conn.execute("SELECT title FROM papers").fetchall() == [("kept",)]


def write_migrations(folder: Path, scripts: dict[str, str]) -> Path:
    folder.mkdir(exist_ok=True)
    for name, sql in scripts.items():
        (folder / name).write_text(sql, encoding="utf-8")
    return folder


def test_older_user_version_db_upgrades_without_losing_rows(tmp_path: Path):
    v1 = {"0001_init.sql": "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL);"}
    v2 = {**v1, "0002_add_tag.sql": "ALTER TABLE notes ADD COLUMN tag TEXT NOT NULL DEFAULT '';"}
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        migrate(conn, write_migrations(tmp_path / "m1", v1))
        conn.execute("INSERT INTO notes (body) VALUES ('first'), ('second')")
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (1,)
        migrate(conn, write_migrations(tmp_path / "m2", v2))
        assert conn.execute("PRAGMA user_version").fetchone() == (2,)
        assert conn.execute("SELECT body, tag FROM notes ORDER BY id").fetchall() == [("first", ""), ("second", "")]


def test_failed_migration_rolls_back_and_keeps_version(tmp_path: Path):
    good = {"0001_init.sql": "CREATE TABLE notes (id INTEGER PRIMARY KEY);"}
    bad = {**good, "0002_broken.sql": "ALTER TABLE notes ADD COLUMN a TEXT; ALTER TABLE missing ADD COLUMN b TEXT;"}
    with sqlite3.connect(tmp_path / "db") as conn:
        migrate(conn, write_migrations(tmp_path / "m1", good))
        with pytest.raises(sqlite3.Error):
            migrate(conn, write_migrations(tmp_path / "m2", bad))
        assert conn.execute("PRAGMA user_version").fetchone() == (1,)
        assert [r[1] for r in conn.execute("PRAGMA table_info(notes)")] == ["id"]


def test_database_newer_than_the_app_is_refused(tmp_path: Path):
    with sqlite3.connect(tmp_path / "db") as conn:
        conn.execute("PRAGMA user_version = 99")
        with pytest.raises(RuntimeError):
            migrate(conn, write_migrations(tmp_path / "m", {"0001_init.sql": "CREATE TABLE a (x);"}))


def test_connections_wait_up_to_30_seconds_for_a_lock_instead_of_failing_after_5(tmp_path: Path):
    """The collector, the report worker and the requests all write; a short busy timeout shows up as "database is locked"."""
    from paperbrief.db import connect, init_db

    settings = Settings(data_dir=tmp_path / "data")
    init_db(settings)
    conn = connect(settings)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
    finally:
        conn.close()


def test_request_connection_is_usable_across_threads(tmp_path: Path):
    """FastAPI opens a sync dependency, runs the endpoint and closes it on different threadpool threads."""
    import threading

    from paperbrief.db import connect, init_db

    settings = Settings(data_dir=tmp_path / "data")
    init_db(settings)
    conn = connect(settings)
    errors: list[Exception] = []

    def use() -> None:
        try:
            conn.execute("SELECT 1").fetchone()
            conn.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=use)
    t.start()
    t.join()
    assert errors == []
