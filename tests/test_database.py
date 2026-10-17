"""The WAL optimization must preserve commits, rollback and thread isolation."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import database as db


@pytest.fixture
def database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "RUNTIME", tmp_path)
    yield tmp_path / "studio.db"
    db.close()


def test_committed_rows_are_visible_on_independent_connections(database):
    db.save("fixture", {"id": "one", "value": 1})
    with db.connect() as first, db.connect() as second:
        assert first is not second
        assert second.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
        assert first.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert first.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_failed_transaction_rolls_back(database):
    db.save("fixture", {"id": "one", "value": 1})
    with pytest.raises(RuntimeError), db.connect() as connection:
        connection.execute("UPDATE records SET body=?", ('{"id":"one","value":2}',))
        raise RuntimeError("Roll back this write")
    assert db.get("fixture", "one")["value"] == 1


def test_concurrent_transactions_are_isolated(database):
    def save(index):
        db.save("fixture", {"id": str(index), "value": index})
        return db.get("fixture", str(index))["value"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(save, range(20))) == list(range(20))
    assert len(db.all_records("fixture")) == 20


def test_close_releases_files_and_reopen_preserves_records(database):
    db.save("fixture", {"id": "one", "value": 1})
    db.close()
    moved = database.with_name("moved.db")
    database.rename(moved)
    moved.rename(database)
    assert db.get("fixture", "one")["value"] == 1
    db.save("fixture", {"id": "two", "value": 2})
    assert len(db.all_records("fixture")) == 2


def test_reuses_idle_connection_without_reusing_active_transaction(database):
    with db.connect() as first:
        first.execute("SELECT 1")
    with db.connect() as reused:
        assert reused is first
        with db.connect() as nested:
            assert nested is not reused


def test_shutdown_waits_for_active_transaction_to_finish(database):
    with db.connect() as active:
        active.execute("INSERT INTO records VALUES (?, ?, ?)", ("fixture", "one", "{}"))
        db.close()
        assert active.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        active.execute("SELECT 1")
    with db.connect() as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_history_projection_preserves_types_without_loading_transcripts(database, monkeypatch):
    db.save(
        "run",
        {
            "id": "one",
            "targets": [{"name": "Bot"}],
            "progress": 0,
            "transcript": "private evidence" * 10000,
        },
    )
    db.save("other", {"id": "unrelated"})
    db.save("run", {"id": "two", "targets": [], "progress": 100})
    monkeypatch.setattr(db, "all_records", lambda *args: pytest.fail("Full history decode"))
    summaries = db.record_summaries("run", ("id", "targets", "progress", "missing"))
    assert summaries == [
        {"id": "two", "targets": [], "progress": 100, "missing": None},
        {"id": "one", "targets": [{"name": "Bot"}], "progress": 0, "missing": None},
    ]
    with pytest.raises(ValueError):
        db.record_summaries("run", ("unsafe.path",))
