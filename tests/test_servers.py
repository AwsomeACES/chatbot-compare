"""servers.py: starting and stopping the bot servers listed in bots.json (a real local process, no network)."""

import json
import socket
import sys

import servers


def free_port():
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def test_up_starts_what_is_down_and_down_stops_only_that(tmp_path, monkeypatch):
    port = free_port()
    monkeypatch.setattr(servers, "PIDS_FILE", str(tmp_path / "servers.pids"))
    monkeypatch.setattr(servers, "LOGS", str(tmp_path / "logs"))
    monkeypatch.setenv("TEST_GREETING", "hello")
    cfg = tmp_path / "bots.json"
    cfg.write_text(json.dumps({"servers": [
        {"name": "web", "port": port, "dir": str(tmp_path), "env": {"GREETING": "$TEST_GREETING", "EMPTY": "$NOT_SET_X"},
         "cmd": [sys.executable, "-m", "http.server", str(port), "--bind", "localhost"]},
        {"name": "gone", "port": free_port(), "dir": str(tmp_path / "missing"), "cmd": ["true"]}]}))
    monkeypatch.setattr(servers, "BOTS_FILE", str(cfg))
    monkeypatch.setattr(servers, "servers", lambda path=None: json.loads(cfg.read_text())["servers"])
    try:
        servers.up()
        started = json.loads((tmp_path / "servers.pids").read_text())
        assert list(started) == ["web"] and servers.is_up(port)  # the missing folder is reported, not started
        servers.up()  # already up: left alone, nothing new to stop
        assert json.loads((tmp_path / "servers.pids").read_text()) == {}
        (tmp_path / "servers.pids").write_text(json.dumps(started))
    finally:
        servers.down()
    import time
    for _ in range(50):
        if not servers.is_up(port):
            break
        time.sleep(0.1)
    assert not servers.is_up(port)
    assert servers.expand("$NOT_SET_X/a") == "/a" and servers.expand("~/x").endswith("/x")


def test_the_shipped_servers_are_well_formed():
    for s in servers.servers():
        assert {"name", "port", "cmd"} <= set(s) and isinstance(s["cmd"], list), s
