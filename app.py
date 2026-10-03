import base64
import binascii
import json
import logging
import os
import random
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

import evaluator
from adapters import BotError, open_conversation, validate

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chatbot_compare")

ROOT = os.path.dirname(__file__)
STATIC_DIR = os.path.join(ROOT, "static")
BOTS_FILE = os.path.join(ROOT, "bots.json")
ARENA_FILE = os.path.join(ROOT, "runs", "arena.json")
ELO_START, ELO_K = 1000, 32
ARENA_TTL_S = float(os.environ.get("ARENA_TTL", "1800"))  # an idle, unvoted battle is closed after this
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")  # set it whenever the app is reachable from other machines
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

app = FastAPI(title="Chatbot Compare")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
evaluator.load_runs()


@app.middleware("http")
async def guard(request: Request, call_next):
    """Optional password (HTTP Basic, any user name) and a JSON-only rule for changes: a web page on another
    site can't send a JSON request here without a CORS preflight, which this app never grants."""
    if APP_PASSWORD and request.url.path != "/api/health":
        password = ""
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "basic":
            try:
                password = base64.b64decode(value).decode().partition(":")[2]
            except (binascii.Error, UnicodeDecodeError):
                pass
        if not secrets.compare_digest(password.encode(), APP_PASSWORD.encode()):
            return JSONResponse({"detail": "Login required"}, status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="Chatbot Compare"'})
    if request.method in UNSAFE_METHODS and not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse({"detail": "Send requests as application/json"}, status_code=415)
    return await call_next(request)


# Added last so it runs first: rejects requests for other host names (DNS rebinding).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


def load_bots():
    with open(BOTS_FILE) as f:
        bots = [b for b in json.load(f)["bots"] if b.get("enabled", True)]
    valid = []
    for b in bots:
        try:
            validate(b)
            valid.append(b)
        except BotError as e:
            log.warning("Ignoring bot in bots.json: %s", e)
    return valid


def find_bots(ids):
    bots = {b["id"]: b for b in load_bots()}
    missing = [i for i in ids if i not in bots]
    if missing:
        raise HTTPException(400, f"Unknown bot(s): {', '.join(missing)}")
    return [bots[i] for i in ids]


def public(bot):
    return {k: bot.get(k) for k in ("id", "label", "type", "description")}


@app.get("/api/health")
def health():
    return {"status": "ok", "runs": len(evaluator.list_runs())}


@app.get("/api/bots")
def bots():
    return {"bots": [public(b) for b in load_bots()]}


@app.post("/api/bots/{bot_id}/ping")
def ping(bot_id: str):
    conv = open_conversation(find_bots([bot_id])[0])
    try:
        reply = conv.send("Hi")
        return {"ok": True, "reply": reply.text[:200], "latency_ms": reply.latency_ms}
    except BotError as e:
        return {"ok": False, "error": str(e)}
    finally:
        conv.close()


# ---------- Evaluation runs ----------

class RunRequest(BaseModel):
    bots: list[str]
    suite: str
    judge: bool = True


@app.get("/api/suites")
def suites():
    return {"suites": evaluator.list_suites()}


@app.get("/api/suites/{suite_id}")
def suite(suite_id: str):
    try:
        return evaluator.load_suite(suite_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "No such suite")


@app.post("/api/runs")
def start_run(req: RunRequest):
    if not 2 <= len(set(req.bots)) <= 4:
        raise HTTPException(400, "Pick 2 to 4 different bots")
    try:
        evaluator.load_suite(req.suite)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "No such suite")
    try:
        run = evaluator.start_run(find_bots(list(dict.fromkeys(req.bots))), req.suite, req.judge)
    except ValueError as e:  # e.g. a bot with no matching profile
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:  # e.g. a profile's data file has moved
        raise HTTPException(400, f"Missing file: {e.filename}")
    return {"id": run["id"]}


@app.get("/api/runs")
def runs():
    return {"runs": evaluator.list_runs()}


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    return r


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    evaluator.delete_run(run_id)
    return {"ok": True}


# ---------- Arena: blind side-by-side, you vote ----------
# battle_id -> {"bots": [bot_a, bot_b], "convs": [...], "voted": bool, "last_used": monotonic seconds}
battles: dict[str, dict] = {}
arena_lock = threading.Lock()


def close_battle(battle):
    for c in battle["convs"]:
        try:
            c.close()
        except Exception:
            log.exception("Could not close an arena conversation")


def purge_battles(now=None):
    """Close battles nobody voted on, so they don't hold bot sessions (or a one-chat-at-a-time bot) forever."""
    now = time.monotonic() if now is None else now
    for bid, battle in list(battles.items()):
        if battle["voted"] or now - battle["last_used"] > ARENA_TTL_S:
            if not battle["voted"]:
                close_battle(battle)
            battles.pop(bid, None)


def load_arena():
    try:
        with open(ARENA_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"ratings": {}, "votes": []}


def save_arena(data):
    tmp = ARENA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, ARENA_FILE)


class BattleRequest(BaseModel):
    message: str
    battle_id: str | None = None
    bots: list[str] | None = None  # pool to draw two from; default all bots


class VoteRequest(BaseModel):
    battle_id: str
    winner: str  # "a", "b", "tie", "both_bad"


@app.post("/api/arena/message")
def arena_message(req: BattleRequest):
    if not req.message.strip():
        raise HTTPException(400, "Type a message")
    purge_battles()
    battle = battles.get(req.battle_id) if req.battle_id else None
    if battle is None or battle["voted"]:
        pool = find_bots(req.bots) if req.bots else load_bots()
        if len(pool) < 2:
            raise HTTPException(400, "Need at least 2 bots for the arena")
        pair = random.sample(pool, 2)
        battle = {"bots": pair, "convs": [open_conversation(b) for b in pair], "voted": False}
        req.battle_id = uuid.uuid4().hex
        battles[req.battle_id] = battle
    battle["last_used"] = time.monotonic()

    def send(conv):
        try:
            r = conv.send(req.message)
            return {"text": r.text, "latency_ms": r.latency_ms, "error": None}
        except BotError as e:
            return {"text": "", "latency_ms": None, "error": str(e)}
        except Exception as e:
            log.exception("Arena message failed")
            return {"text": "", "latency_ms": None, "error": f"{type(e).__name__}: {e}"}

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(send, battle["convs"])
    return {"battle_id": req.battle_id, "a": a, "b": b}


@app.post("/api/arena/vote")
def arena_vote(req: VoteRequest):
    battle = battles.get(req.battle_id)
    if battle is None:
        raise HTTPException(404, "Battle not found (the server may have restarted)")
    if battle["voted"]:
        raise HTTPException(400, "Already voted")
    if req.winner not in ("a", "b", "tie", "both_bad"):
        raise HTTPException(400, "winner must be a, b, tie or both_bad")
    battle["voted"] = True
    close_battle(battle)
    a, b = (bot["id"] for bot in battle["bots"])

    with arena_lock:
        data = load_arena()
        ratings = data["ratings"]
        for bot in battle["bots"]:
            ratings.setdefault(bot["id"], {"elo": ELO_START, "wins": 0, "losses": 0, "ties": 0, "label": bot["label"]})
        ra, rb = ratings[a], ratings[b]
        expected_a = 1 / (1 + 10 ** ((rb["elo"] - ra["elo"]) / 400))
        score_a = {"a": 1.0, "b": 0.0}.get(req.winner, 0.5)
        ra["elo"] = round(ra["elo"] + ELO_K * (score_a - expected_a), 1)
        rb["elo"] = round(rb["elo"] + ELO_K * ((1 - score_a) - (1 - expected_a)), 1)
        if req.winner == "a":
            ra["wins"] += 1; rb["losses"] += 1
        elif req.winner == "b":
            rb["wins"] += 1; ra["losses"] += 1
        else:
            ra["ties"] += 1; rb["ties"] += 1
        data["votes"].append({"a": a, "b": b, "winner": req.winner})
        save_arena(data)
    return {"a": public(battle["bots"][0]), "b": public(battle["bots"][1])}


@app.get("/api/arena/leaderboard")
def leaderboard():
    data = load_arena()
    rows = [{"id": k, **v, "battles": v["wins"] + v["losses"] + v["ties"]} for k, v in data["ratings"].items()]
    return {"rows": sorted(rows, key=lambda r: r["elo"], reverse=True), "votes": len(data["votes"])}


@app.post("/api/arena/reset")
def arena_reset():
    with arena_lock:
        save_arena({"ratings": {}, "votes": []})
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
