"""Fixture shutdown must release files and sockets owned by descendants."""

import errno
import json
import os
import socket
import subprocess
import sys
import time

from scripts.process_cleanup import stop_process_tree


def test_shutdown_releases_descendant_database_and_listening_socket(tmp_path):
    database = tmp_path / "child.db"
    ready = tmp_path / "ready.json"
    child = """
import json, os, socket, sqlite3, sys, time
from pathlib import Path
db = sqlite3.connect(sys.argv[1])
db.execute('CREATE TABLE fixture (value INTEGER)')
db.commit()
listener = socket.socket()
listener.bind(('127.0.0.1', 0))
listener.listen()
Path(sys.argv[2]).write_text(json.dumps({'port': listener.getsockname()[1]}))
while True:
    time.sleep(1)
"""
    parent = """
import subprocess, sys
child = subprocess.Popen([sys.executable, '-c', sys.argv[1], *sys.argv[2:]])
child.wait()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", parent, child, str(database), str(ready)],
        start_new_session=os.name != "nt",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None, "Fixture server exited before readiness"
            time.sleep(0.02)
        assert ready.exists(), "Fixture descendant did not become ready"
        # Wait for the ready file's JSON write to finish, independently of polling.
        port = None
        while time.monotonic() < deadline:
            try:
                port = json.loads(ready.read_text())["port"]
                break
            except json.JSONDecodeError:
                time.sleep(0.01)
        assert port is not None
        stop_process_tree(process)
        assert process.poll() is not None
        # POSIX permits renaming open files; the socket check also proves that
        # the descendant is gone on those platforms. Windows checks both locks.
        # A parent wait() does not reap grandchildren. The OS can finish
        # releasing their handles just after the parent's exit notification.
        # A permanently orphaned server still fails this bounded assertion.
        release_deadline = time.monotonic() + 5
        while True:
            try:
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", port))
                break
            except OSError as error:
                if error.errno != errno.EADDRINUSE or time.monotonic() >= release_deadline:
                    raise
                time.sleep(0.01)
        moved = database.with_name("released.db")
        while True:
            try:
                database.rename(moved)
                break
            except PermissionError:
                if time.monotonic() >= release_deadline:
                    raise
                time.sleep(0.01)
        moved.unlink()
        stop_process_tree(process)  # Repeated cleanup is safe.
    finally:
        stop_process_tree(process)
