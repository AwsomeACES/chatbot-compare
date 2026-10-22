"""Start and stop the chatbot servers a run needs, as listed under "servers" in bots.json.

Each server: {"name", "port", "dir", "cmd": [...], "env": {...}, "health": {"path", "expect"}, "note"}. "dir" may
start with ~ and may be relative to this project; "$NAME" in dir, cmd and env is filled from the environment (and this
project's .env), with $COMPARE_DIR = this project. A server already answering on its port is left alone. With "health",
it counts as up only when GET <path> on its port returns 200 with "expect" in the body: another app holding the port
(a different project's dev server on 8000, say) is reported as such instead of passing for the bot.

  servers.py up     start every server that isn't running; remember the ones it started (runs/servers.pids)
  servers.py down   stop only the servers "up" started
  servers.py status which servers answer

nightly.sh runs "up" before the regression check and "down" after it, so the same file drives a laptop, a VM or a
container: add a server here instead of editing the script.
"""

import json
import os
import urllib.error
import urllib.request
import re
import signal
import socket
import subprocess
import sys
import time

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
BOTS_FILE = os.path.join(HERE, "bots.json")
# Which servers "up" started, for "down" to stop. nightly.sh uses its own file, so it stops only what it started,
# never servers someone brought up by hand (a long run may still need them).
PIDS_FILE = os.environ.get("SERVERS_PIDS_FILE") or os.path.join(HERE, "runs", "servers.pids")
LOGS = os.path.join(HERE, "runs", "bot-logs")
STARTUP_S = 60


def servers(path=BOTS_FILE):
    with open(path) as f:
        return json.load(f).get("servers", [])


def expand(value):
    """~ and $NAME filled in; a $NAME that isn't set becomes empty, as in the shell."""
    if not isinstance(value, str):
        return value
    return re.sub(r"\$\{?\w+\}?", "", os.path.expandvars(os.path.expanduser(value)))


def is_up(port, host="localhost"):
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex((host, int(port))) == 0


def is_ours(server, host="localhost"):
    """The app answering on the server's port is this server (no "health": any app on the port counts)."""
    health = server.get("health")
    if not health:
        return True
    try:
        with urllib.request.urlopen(f"http://{host}:{server['port']}{health['path']}", timeout=5) as r:
            return r.status == 200 and health.get("expect", "") in r.read(65536).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return False


def state(server):
    """"up", "down", or "other": something else holds the port."""
    if not is_up(server["port"]):
        return "down"
    return "up" if is_ours(server) else "other"


def start(server, wait_s=STARTUP_S):
    """Start one server unless it is up. Returns its pid when this call started it, else None."""
    name, port = server["name"], server["port"]
    now = state(server)
    if now == "up":
        print(f"{name}: already up on :{port}")
        return None
    if now == "other":
        print(f"{name}: port {port} is held by another app, not started (stop that app or move {name} to a free port)")
        return None
    folder = os.path.join(HERE, expand(server.get("dir", ".")))
    if not os.path.isdir(folder):
        print(f"{name}: {folder} not found, not started")
        return None
    env = {**os.environ, **{k: str(expand(v)) for k, v in server.get("env", {}).items()}}
    os.makedirs(LOGS, exist_ok=True)
    log = open(os.path.join(LOGS, f"{name}.log"), "ab")
    try:
        proc = subprocess.Popen([expand(c) for c in server["cmd"]], cwd=folder, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        print(f"{name}: could not start: {e}")
        return None
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if is_up(port) and is_ours(server):
            print(f"{name} started on :{port}")
            return proc.pid
        if proc.poll() is not None:
            break
        time.sleep(1)
    print(f"{name} did not come up on :{port} (see runs/bot-logs/{name}.log)")
    return proc.pid if proc.poll() is None else None


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # running, as another user
        return True


def started_before():
    """The servers an earlier "up" started that are still running (a second "up" must not forget them)."""
    try:
        with open(PIDS_FILE) as f:
            return {name: pid for name, pid in json.load(f).items() if alive(pid)}
    except (OSError, ValueError, AttributeError):
        return {}


def up():
    started = started_before()
    for server in servers():
        pid = start(server)
        if pid:
            started[server["name"]] = pid
    os.makedirs(os.path.dirname(PIDS_FILE), exist_ok=True)
    with open(PIDS_FILE, "w") as f:
        json.dump(started, f)


def down():
    started = started_before()
    if not os.path.exists(PIDS_FILE):
        return
    for name, pid in started.items():
        try:
            os.killpg(pid, signal.SIGTERM)  # its own process group: also stops the workers it spawned
            print(f"{name} stopped")
        except ProcessLookupError:
            pass
    os.remove(PIDS_FILE)


def status():
    for server in servers():
        now = state(server)
        print(f"{server['name']:<12} :{server['port']:<6} {'held by another app' if now == 'other' else now}")


if __name__ == "__main__":
    load_dotenv(os.path.join(HERE, ".env"))
    os.environ.setdefault("COMPARE_DIR", HERE)
    commands = {"up": up, "down": down, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"Usage: {sys.argv[0]} {'|'.join(commands)}")
    commands[sys.argv[1]]()
