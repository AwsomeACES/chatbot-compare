import json
import sqlite3
from .config import RUNTIME

def connect():
    db = sqlite3.connect(RUNTIME / 'studio.db', timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT PRIMARY KEY, body TEXT)')
    return db

def save(kind, value):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO records VALUES (?, ?, ?)', (kind, value['id'], json.dumps(value)))

def get(kind, ident):
    with connect() as db:
        row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, str(ident))).fetchone()
    return json.loads(row[0]) if row else None

def all_records(kind):
    with connect() as db:
        rows = db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
    return [json.loads(row[0]) for row in rows]

def delete(kind, ident):
    with connect() as db:
        db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, str(ident)))
