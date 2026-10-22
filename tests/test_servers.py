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
        servers.up()  # already up: left alone, and still remembered so "down" stops it
        assert json.loads((tmp_path / "servers.pids").read_text()) == started
    finally:
        servers.down()
    import time
    for _ in range(50):
        if not servers.is_up(port):
            break
        time.sleep(0.1)
    assert not servers.is_up(port)
    assert servers.expand("$NOT_SET_X/a") == "/a" and servers.expand("~/x").endswith("/x")


def test_another_app_on_the_port_is_reported_not_taken_for_the_bot(tmp_path, monkeypatch, capsys):
    import subprocess
    import time
    port = free_port()
    other = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "localhost"], cwd=tmp_path,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if servers.is_up(port):
                break
            time.sleep(0.1)
        (tmp_path / "api").mkdir()
        (tmp_path / "api" / "models").write_text('{"store_name": "VoltKart"}')
        bot = {"name": "bot", "port": port, "dir": str(tmp_path), "cmd": ["false"],
               "health": {"path": "/api/models", "expect": "store_name"}}
        assert servers.state(bot) == "up"  # the health page names the bot
        wrong = {**bot, "health": {"path": "/api/models", "expect": "reliance-digital-ai"}}
        assert servers.state(wrong) == "other" and servers.state({**bot, "health": {"path": "/nope"}}) == "other"
        assert servers.start(wrong) is None and "held by another app" in capsys.readouterr().out
        assert servers.state({**bot, "port": free_port()}) == "down"
    finally:
        other.terminate()
        other.wait()


def test_the_shipped_servers_are_well_formed():
    for s in servers.servers():
        assert {"name", "port", "cmd", "health"} <= set(s) and isinstance(s["cmd"], list), s
        assert s["health"]["path"].startswith("/") and s["health"]["expect"], s
