"""Thread-owned SQLite leases: durable transactions without repeated WAL setup."""

import atexit
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from .config import RUNTIME


@dataclass
class Lease:
    connection: sqlite3.Connection
    busy: bool = True
    retiring: bool = False


_pools: dict[tuple[str, int], list[Lease]] = {}
_pool_lock = threading.Lock()


def acquire(path: str) -> Lease:
    """A connection is never leased concurrently or across request threads."""
    key = (path, threading.get_ident())
    with _pool_lock:
        entries = _pools.setdefault(key, [])
        for lease in entries:
            if not lease.busy:
                lease.busy = True
                return lease
        # Disabling the SQLite thread guard only permits shutdown cleanup from
        # another thread. Operations remain owned by the lease's thread above.
        connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT PRIMARY KEY, body TEXT)"
            )
            connection.commit()
        except BaseException:
            connection.close()
            raise
        lease = Lease(connection)
        entries.append(lease)
        return lease


def close() -> None:
    """Close idle handles; active leases finish their transaction before closing."""
    with _pool_lock:
        for entries in _pools.values():
            for lease in entries:
                lease.retiring = True
                if not lease.busy:
                    lease.connection.close()
        _pools.clear()


atexit.register(close)


@contextmanager
def connect():
    path = str((RUNTIME / "studio.db").resolve())
    lease = acquire(path)
    try:
        with lease.connection:
            yield lease.connection
    finally:
        with _pool_lock:
            lease.busy = False
            if lease.retiring:
                lease.connection.close()


def save(kind, value):
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
            (kind, value["id"], json.dumps(value)),
        )


def get(kind, ident):
    with connect() as db:
        row = db.execute(
            "SELECT body FROM records WHERE kind=? AND id=?", (kind, str(ident))
        ).fetchone()
    return json.loads(row[0]) if row else None


def all_records(kind):
    with connect() as db:
        rows = db.execute(
            "SELECT body FROM records WHERE kind=? ORDER BY rowid DESC", (kind,)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def record_summaries(kind: str, fields: tuple[str, ...]) -> list[dict]:
    """Read history metadata without decoding every transcript and audit log."""
    if not fields or any(not field.isidentifier() for field in fields):
        raise ValueError("Summary fields must be simple JSON property names.")
    projection = ", ".join("?, json_extract(body, ?)" for _ in fields)
    parameters = [value for field in fields for value in (field, f"$.{field}")]
    with connect() as connection:
        rows = connection.execute(
            f"SELECT json_object({projection}) FROM records WHERE kind=? ORDER BY rowid DESC",
            [*parameters, kind],
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def delete(kind, ident):
    with connect() as db:
        db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, str(ident)))


class RevisionConflict(Exception):
    """The stored record changed since the caller read it."""


class RecordMissing(Exception):
    pass


def update(kind, ident, mutate, expected_revision=None):
    """Atomic read-modify-write guarded by an integer `revision` field.

    `mutate(record, connection)` edits the decoded record in place; related rows (such as audit
    anchors) written on `connection` commit or roll back with it. The write happens inside one immediate
    transaction, so concurrent writers serialize and a stale `expected_revision` fails clearly.
    """
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT body FROM records WHERE kind=? AND id=?", (kind, str(ident))
        ).fetchone()
        if not row:
            raise RecordMissing(str(ident))
        record = json.loads(row[0])
        if expected_revision is not None and record.get("revision", 0) != expected_revision:
            raise RevisionConflict(
                f"Revision {expected_revision} is stale; current revision is {record.get('revision', 0)}."
            )
        result = mutate(record, db)
        record["revision"] = record.get("revision", 0) + 1
        db.execute(
            "UPDATE records SET body=? WHERE kind=? AND id=?",
            (json.dumps(record), kind, str(ident)),
        )
    return record if result is None else result
