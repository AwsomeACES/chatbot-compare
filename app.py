import base64
import binascii
import itertools
import json
import math
import logging
import os
import random
import re
import secrets
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

import compliance
import evaluator
import export
import governance
import prices
import quickbot
import review
from adapters import BotError, bot_key_allowed, open_conversation, validate

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chatbot_compare")

ROOT = os.path.dirname(__file__)
STATIC_DIR = os.path.join(ROOT, "static")
BOTS_FILE = os.path.join(ROOT, "bots.json")
ARENA_FILE = os.path.join(ROOT, "runs", "arena.json")
BATTLES_FILE = os.path.join(ROOT, "runs", "arena_battles.json")
RATING_BASE = 1000  # Bradley-Terry strengths shown on the Elo scale: +400 = 10x the odds of winning
ARENA_TTL_S = float(os.environ.get("ARENA_TTL", "1800"))  # an idle battle's bot sessions are closed after this
BATTLE_KEEP_S = 24 * 3600  # an unvoted battle can still be voted on (from its saved transcript) for this long
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")  # set it whenever the app is reachable from other machines
# Per-person logins, "name:password,name2:password2": the user name is then proven, so the audit log's actor and a
# sign-off's reviewer are who logged in. With only APP_PASSWORD, any user name is accepted (and recorded as typed).
APP_USERS = dict(u.split(":", 1) for u in os.environ.get("APP_USERS", "").split(",") if ":" in u)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

app = FastAPI(title="Chatbot Compare")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
evaluator.load_runs()


@app.middleware("http")
async def guard(request: Request, call_next):
    """Optional password (HTTP Basic, any user name) and a JSON-only rule for changes: a web page on another
    site can't send a JSON request here without a CORS preflight, which this app never grants. The Basic user name
    is who the audit log says acted."""
    user = password = ""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "basic":
        try:
            user, _, password = base64.b64decode(value).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            pass
    user = user.strip()[:60]
    if APP_USERS:
        ok = user in APP_USERS and secrets.compare_digest(password.encode(), APP_USERS[user].encode())
    else:
        ok = not APP_PASSWORD or secrets.compare_digest(password.encode(), APP_PASSWORD.encode())
    governance.actor.set((f"{user} (login)" if APP_USERS else f"{user} (dashboard)") if user and ok else "dashboard")
    if not ok and request.url.path != "/api/health":
        return JSONResponse({"detail": "Login required"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Chatbot Compare"'})
    if request.method in UNSAFE_METHODS and not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse({"detail": "Send requests as application/json"}, status_code=415)
    return await call_next(request)


# Added last so it runs first: rejects requests for other host names (DNS rebinding).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


def read_bots_file():
    with open(BOTS_FILE) as f:
        return json.load(f)


def load_bots():
    """bots.json's enabled bots, then the ones added by URL (bots.quick.json)."""
    bots = [b for b in read_bots_file()["bots"] + quickbot.load() if b.get("enabled", True)]
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


def public(bot, snapshot=None):
    return {k: bot.get(k) for k in ("id", "label", "type", "description", "llm")} | {
        "app": evaluator.app_of(bot), "quick": bool(bot.get("quick")),
        "remote": bool(governance.remote_bots([bot])),  # test messages would leave this machine
        "priced": bool(evaluator.priced_config(bot, snapshot).get("pricing"))}


@app.get("/api/health")
def health():
    return {"status": "ok", "runs": len(evaluator.list_runs())}


@app.get("/api/bots")
def bots():
    """The enabled bots, and the presets from bots.json; a preset naming a disabled or unknown bot says which."""
    enabled = {b["id"]: b for b in load_bots()}
    snapshot = prices.latest()
    presets = []
    for p in read_bots_file().get("presets", []):
        missing = [i for i in p.get("bots", []) if i not in enabled]
        presets.append({**p, "missing": missing,
                        "run_type": None if missing else evaluator.run_type([enabled[i] for i in p["bots"]])})
    return {"bots": [public(b, snapshot) for b in enabled.values()], "presets": presets,
            "prices": {"date": snapshot.get("date"), "models": len(snapshot.get("models") or {})} if snapshot else None,
            "judge": {"model": evaluator.JUDGE_MODEL, "second_judge": evaluator.SECOND_JUDGE_MODEL or None,
                      "rpm": evaluator.llm.JUDGE.rpm or None, "daily_limit": evaluator.llm.JUDGE.daily_limit,
                      "fallback": evaluator.llm.JUDGE.fallback.model if evaluator.llm.JUDGE.fallback else None,
                      "second_sample": evaluator.SECOND_JUDGE_SAMPLE,
                      "remote": governance.remote_judges([evaluator.llm.JUDGE]),
                      "second_remote": governance.remote_judges([evaluator.llm.SECOND_JUDGE] if evaluator.llm.SECOND_JUDGE else []),
                      "unpriced": evaluator.unpriced([], evaluator.pinned_judge_pricing(snapshot, True), True, True)}}


class PingRequest(BaseModel):
    consent: bool = False  # needed for a bot that isn't on this machine (the "Hi" leaves it)


def require_send_consent(bots, consent):
    remote = governance.remote_bots(bots)
    if remote and not consent:
        raise HTTPException(400, f"{', '.join(remote)} {'is' if len(remote) == 1 else 'are'} not on this machine: "
                                 "allow sending it messages first")


@app.post("/api/bots/{bot_id}/ping")
def ping(bot_id: str, req: PingRequest | None = None):
    bot = find_bots([bot_id])[0]
    require_send_consent([bot], req and req.consent)
    conv = open_conversation(bot)
    try:
        reply = conv.send("Hi")
        return {"ok": True, "reply": reply.text[:200], "latency_ms": reply.latency_ms}
    except BotError as e:
        return {"ok": False, "error": str(e)}
    finally:
        conv.close()


# ---------- Adding a bot by URL ----------

class DetectRequest(BaseModel):
    url: str
    model: str = ""  # OpenAI-compatible APIs: the model id (default: the first one /models lists)
    api_key_env: str = ""  # the .env variable holding its API key, if it needs one
    send_ok: bool = False  # consent to send a test message to a URL off this machine


class QuickBotRequest(BaseModel):
    label: str
    config: dict


@app.post("/api/bots/detect")
def detect_bot(req: DetectRequest):
    """Send one test message to the URL and work out how to chat with it (see quickbot.py)."""
    if governance.remote_bots([{"id": "new", "url": req.url}]) and not req.send_ok:
        raise HTTPException(400, "This URL is not on this machine: allow sending it a test message first")
    if req.api_key_env and not (re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", req.api_key_env)
                                and bot_key_allowed(req.api_key_env)):
        raise HTTPException(400, "The API key variable must be named BOT_... (e.g. BOT_MYBOT_API_KEY, set in .env) or "
                                 "be listed in BOT_KEY_VARS, so this app's own keys are never sent to a pasted URL")
    try:
        return quickbot.detect(req.url, req.model.strip() or None, req.api_key_env or None)
    except BotError as e:
        raise HTTPException(400, str(e))


@app.post("/api/bots/quick")
def add_quick_bot(req: QuickBotRequest):
    taken = {b["id"] for b in read_bots_file()["bots"] + quickbot.load()}
    try:
        bot = quickbot.add(req.label, req.config, taken)
    except BotError as e:
        raise HTTPException(400, str(e))
    governance.record("bot.add", bot["id"], type=bot["type"], url=bot.get("url") or bot.get("base_url"))
    return public(bot)


@app.delete("/api/bots/quick/{bot_id}")
def remove_quick_bot(bot_id: str):
    try:
        quickbot.remove(bot_id)
    except KeyError:
        raise HTTPException(404, "No such bot added by URL")
    governance.record("bot.remove", bot_id)
    return {"ok": True}


# ---------- Prices (LiteLLM catalogue snapshots) ----------

@app.get("/api/prices")
def price_snapshot():
    snap = prices.latest()
    return {"date": snap.get("date"), "models": len(snap.get("models") or {}), "url": snap.get("url")} if snap else {}


@app.post("/api/prices/update")
def update_prices():
    try:
        info = prices.update()
    except (RuntimeError, ValueError, OSError) as e:
        raise HTTPException(502, str(e))
    except Exception as e:  # network errors from the HTTP client
        raise HTTPException(502, f"Could not download the price catalogue: {e}")
    governance.record("prices.update", info["date"], models=info["models"])
    return {"date": info["date"], "models": info["models"]}


# ---------- Evaluation runs ----------

class RunRequest(BaseModel):
    bots: list[str]
    suite: str
    judge: bool = True
    repeats: int = 1  # ask every case this many times; scores average over all of them
    comparative: bool = True  # after the run, the judge ranks the bots' answers side by side
    second_judge: bool = False  # a judge from another model family re-grades a sample
    rewordings: bool = False  # also ask every reworded version of the cases that have them
    cases: list[str] | None = None  # only these case ids (default: the whole suite)
    timing: bool = True  # time a few replies per bot on their own after the chats (the speed score)
    budget_usd: float | None = None  # stop starting new cases once the estimated spend reaches this
    consent: dict = {}  # {"send_to_bots": bool, "share_with_judge": bool}: needed for bots / a judge off this machine


class ResumeRequest(BaseModel):
    budget_usd: float | None = None  # a new budget for the rest of the run


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
        run = evaluator.start_run(find_bots(list(dict.fromkeys(req.bots))), req.suite, req.judge,
                                  repeats=req.repeats, comparative=req.comparative, second_judge=req.second_judge,
                                  rewordings=req.rewordings, case_ids=req.cases, budget_usd=req.budget_usd,
                                  consent=req.consent, timing=req.timing)
    except ValueError as e:  # e.g. a bot with no matching profile
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:  # e.g. a profile's data file has moved
        raise HTTPException(400, f"Missing file: {e.filename}")
    return {"id": run["id"]}


@app.get("/api/runs")
def runs():
    signed = {}
    for s in compliance.load_signoffs():
        signed.setdefault(s["run_id"], {})[s["bot_id"]] = s["decision"]  # the latest decision per bot
    return {"runs": [r | {"signoffs": signed.get(r["id"], {})} for r in evaluator.list_runs()]}


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    return r


@app.get("/api/runs/{run_id}/export.csv")
def run_csv(run_id: str):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    return Response(export.csv_text(r), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="chatbot-compare-{run_id}.csv"'})


@app.get("/api/runs/{run_id}/report.html")
def run_report(run_id: str):
    """A printable report; the browser's Save as PDF makes the PDF."""
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    return HTMLResponse(export.report_html(r))


@app.get("/api/runs/{run_id}/report.pdf")
def run_pdf(run_id: str):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    try:
        pdf = export.report_pdf(r)
    except export.PdfUnavailable as e:
        raise HTTPException(503, str(e))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="chatbot-compare-{run_id}.pdf"'})


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    try:
        evaluator.cancel_run(run_id)
    except KeyError:
        raise HTTPException(404, "No such run")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str, req: ResumeRequest | None = None):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    try:
        evaluator.resume_run(run_id, find_bots([b["id"] for b in r["bots"]]), budget_usd=req and req.budget_usd)
    except KeyError:
        raise HTTPException(404, "No such run")
    except ValueError as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError as e:
        raise HTTPException(400, f"Missing file: {e.filename}")
    return {"id": run_id}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    evaluator.delete_run(run_id)
    return {"ok": True}


# ---------- Baselines and regression alerts ----------

@app.get("/api/baselines")
def baselines():
    out = {}
    for bot_id, run_id in evaluator.load_baselines().items():
        r = evaluator.get_run(run_id)
        out[bot_id] = {"run_id": run_id, "created_at": r["created_at"] if r else None}
    return {"baselines": out}


@app.post("/api/runs/{run_id}/baseline")
def set_baseline(run_id: str):
    try:
        return {"bots": evaluator.set_baseline(run_id)}
    except KeyError:
        raise HTTPException(404, "No such run")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/runs/{run_id}/baseline")
def clear_baseline(run_id: str):
    evaluator.clear_baseline(run_id)
    return {"ok": True}


@app.get("/api/runs/{run_id}/regressions")
def run_regressions(run_id: str):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    return evaluator.regressions(r)


# ---------- Judge review: humans check the AI judge ----------

class LabelRequest(BaseModel):
    id: str
    passed: bool  # should the conversation pass
    hallucinated: bool  # did the bot invent a fact
    note: str = ""


@app.get("/api/review")
def review_queue(run_id: str | None = None, include_labeled: bool = False, limit: int = 100):
    if run_id and evaluator.get_run(run_id) is None:
        raise HTTPException(404, "No such run")
    return review.queue(run_id, include_labeled, max(1, min(limit, 500)))


@app.post("/api/review/label")
def review_label(req: LabelRequest):
    try:
        review.label(req.id, req.passed, req.hallucinated, req.note)
    except KeyError:
        raise HTTPException(404, "No such conversation")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return review.stats()


@app.delete("/api/review/label")
def review_unlabel(id: str):
    review.unlabel(id)
    return review.stats()


# ---------- Governance: release gate, sign-off, audit trail, risk register, model cards ----------

class SignoffRequest(BaseModel):
    bot_id: str
    decision: str  # "approve" or "reject"
    reviewer: str
    note: str = ""
    override: bool = False  # approve although the release gate blocks it (needs a justification in note)


class PurgeRequest(BaseModel):
    dry_run: bool = True


@app.get("/api/governance")
def governance_overview():
    return compliance.overview()


@app.get("/api/governance/report.md")
def governance_report():
    return PlainTextResponse(compliance.report_markdown(), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="ai-governance-report.md"'})


@app.post("/api/governance/purge")
def governance_purge(req: PurgeRequest):
    return compliance.purge(dry_run=req.dry_run)


@app.get("/api/runs/{run_id}/gate")
def run_gate(run_id: str):
    r = evaluator.get_run(run_id)
    if r is None:
        raise HTTPException(404, "No such run")
    return compliance.gate(r) | {"signoffs": compliance.signoffs_for(run_id)}


@app.post("/api/runs/{run_id}/signoff")
def run_signoff(run_id: str, req: SignoffRequest):
    if APP_USERS and req.reviewer.strip().lower() != governance.current_actor().removesuffix(" (login)").lower():
        raise HTTPException(403, "Sign off under your own login: the reviewer must be the user you logged in as")
    try:
        return compliance.signoff(run_id, req.bot_id, req.decision, req.reviewer, req.note, req.override)
    except KeyError:
        raise HTTPException(404, "No such run or bot")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/audit")
def audit(limit: int = 100, target: str | None = None):
    return {"verify": governance.verify_log(),
            "entries": governance.read_log(max(1, min(limit, 1000)), target=target)}


# ---------- Arena: blind side-by-side, you vote ----------
# Live battles: battle_id -> {"bots": [bot_a, bot_b], "convs": [...], "voted": bool, "last_used": monotonic seconds}.
# Every battle is also saved to BATTLES_FILE (bot ids and transcript), so a vote still counts after a restart.
battles: dict[str, dict] = {}
arena_lock = threading.Lock()  # the saved votes and battles files
battles_lock = threading.Lock()  # the live battles dict


def close_battle(battle):
    for c in battle["convs"]:
        try:
            c.close()
        except Exception:
            log.exception("Could not close an arena conversation")


def purge_battles(now=None):
    """Close battles nobody voted on, so they don't hold bot sessions (or a one-chat-at-a-time bot) forever."""
    now = time.monotonic() if now is None else now
    with battles_lock:
        done = [(bid, b) for bid, b in battles.items() if b["voted"] or now - b["last_used"] > ARENA_TTL_S]
        for bid, _ in done:
            battles.pop(bid, None)
    for _, battle in done:
        if not battle["voted"]:
            with battle["lock"]:  # not while a message to it is still under way
                close_battle(battle)


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def load_arena():
    return _read_json(ARENA_FILE, {"votes": []})


def save_arena(data):
    _write_json(ARENA_FILE, data)


def load_saved_battles():
    """Saved battles still open for a vote; older unvoted ones are dropped."""
    saved = _read_json(BATTLES_FILE, {})
    return {k: v for k, v in saved.items() if time.time() - v.get("created", 0) < BATTLE_KEEP_S}


def save_battle(bid, battle=None):
    """Store (or, with battle=None, forget) one battle's transcript."""
    with arena_lock:
        saved = load_saved_battles()
        if battle is None:
            saved.pop(bid, None)
        else:
            saved[bid] = battle
        _write_json(BATTLES_FILE, saved)


def pick_pair(pool, votes, rng=random):
    """The pair of bots with the fewest votes so far (random among equals), in random order, so every pair gets
    about the same number of battles and no bot is always shown as A."""
    played = Counter(frozenset((v["a"], v["b"])) for v in votes)
    pairs = list(itertools.combinations(pool, 2))
    fewest = min(played[frozenset((a["id"], b["id"]))] for a, b in pairs)
    pair = list(rng.choice([p for p in pairs if played[frozenset((p[0]["id"], p[1]["id"]))] == fewest]))
    rng.shuffle(pair)
    return pair


def bradley_terry(votes, iterations=300):
    """Ratings from all votes at once (Bradley-Terry, fitted by minorization-maximization), so unlike Elo they don't
    depend on vote order. A tie or "both bad" is half a win each. Every bot also plays one virtual tie against a
    fixed 1000-rated opponent, which keeps an unbeaten bot's rating finite and anchors the scale."""
    wins, games = Counter(), Counter()
    for v in votes:
        score_a = {"a": 1.0, "b": 0.0}.get(v["winner"], 0.5)
        wins[v["a"]] += score_a
        wins[v["b"]] += 1 - score_a
        games[frozenset((v["a"], v["b"]))] += 1
    players = sorted({v[k] for v in votes for k in ("a", "b")})
    strength = dict.fromkeys(players, 1.0)
    for _ in range(iterations):
        new = {}
        for i in players:
            denom = 1 / (strength[i] + 1)  # the virtual opponent, strength 1
            for pair, n in games.items():
                if i in pair:
                    (j,) = pair - {i}
                    denom += n / (strength[i] + strength[j])
            new[i] = (wins[i] + 0.5) / denom
        strength = new
    return {i: round(RATING_BASE + 400 * math.log10(strength[i]), 1) for i in players}


class BattleRequest(BaseModel):
    message: str
    battle_id: str | None = None
    bots: list[str] | None = None  # pool to draw two from; default all bots
    consent: bool = False  # needed when a bot in the pool isn't on this machine


class VoteRequest(BaseModel):
    battle_id: str
    winner: str  # "a", "b", "tie", "both_bad"


@app.post("/api/arena/message")
def arena_message(req: BattleRequest):
    if not req.message.strip():
        raise HTTPException(400, "Type a message")
    purge_battles()
    with battles_lock:
        battle = battles.get(req.battle_id) if req.battle_id else None
    if battle is None and req.battle_id and req.battle_id in load_saved_battles():
        raise HTTPException(409, "This chat can't continue: the bots' sessions were closed (the server restarted or "
                                 "it sat idle). Vote on what you've seen, or send again to start a new battle.")
    if battle is None or battle["voted"]:
        pool = find_bots(req.bots) if req.bots else load_bots()
        if len(pool) < 2:
            raise HTTPException(400, "Need at least 2 bots for the arena")
        require_send_consent(pool, req.consent)
        pair = pick_pair(pool, load_arena()["votes"])
        battle = {"bots": pair, "convs": [open_conversation(b) for b in pair], "voted": False, "log": [],
                  "created": time.time(), "lock": threading.Lock(), "last_used": time.monotonic()}
        req.battle_id = uuid.uuid4().hex
        with battles_lock:
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

    with battle["lock"]:  # one message at a time per battle, so the two transcripts stay in step
        if battle["voted"]:
            raise HTTPException(409, "This battle was just voted on; send again to start a new one")
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.map(send, battle["convs"])
        battle["log"].append({"user": req.message, "a": a, "b": b})
        save_battle(req.battle_id, {"bots": [x["id"] for x in battle["bots"]],
                                    "labels": [x["label"] for x in battle["bots"]],
                                    "log": battle["log"], "created": battle["created"]})
    return {"battle_id": req.battle_id, "a": a, "b": b}


@app.get("/api/arena/battle/{battle_id}")
def arena_battle(battle_id: str):
    """A saved, unvoted battle's transcript (bot names stay hidden), so the page can show it again after a reload."""
    saved = load_saved_battles().get(battle_id)
    if saved is None:
        raise HTTPException(404, "Battle not found")
    return {"battle_id": battle_id, "log": saved["log"], "live": battle_id in battles}


@app.post("/api/arena/vote")
def arena_vote(req: VoteRequest):
    if req.winner not in ("a", "b", "tie", "both_bad"):
        raise HTTPException(400, "winner must be a, b, tie or both_bad")
    # Checked and recorded under one lock, so two votes sent at once can't both count.
    with battles_lock:
        battle = battles.get(req.battle_id)
        if battle is not None and battle["voted"]:
            raise HTTPException(400, "Already voted")
        if battle is not None:
            battle["voted"] = True
    with arena_lock:
        saved_all = load_saved_battles()
        saved = saved_all.pop(req.battle_id, None)
        if battle is None and saved is None:
            raise HTTPException(404, "Battle not found, already voted on, or more than a day old")
        if battle is not None:
            ids, labels = [b["id"] for b in battle["bots"]], [b["label"] for b in battle["bots"]]
        else:
            ids, labels = saved["bots"], saved["labels"]
        _write_json(BATTLES_FILE, saved_all)
        data = load_arena()
        data["votes"].append({"a": ids[0], "b": ids[1], "winner": req.winner, "labels": dict(zip(ids, labels)),
                              "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": governance.current_actor()})
        save_arena(data)
    if battle is not None:
        with battle["lock"]:
            close_battle(battle)
    return {"a": {"id": ids[0], "label": labels[0]}, "b": {"id": ids[1], "label": labels[1]}}


@app.get("/api/arena/leaderboard")
def leaderboard():
    data = load_arena()
    votes = data["votes"]
    labels = {k: v.get("label", k) for k, v in data.get("ratings", {}).items()}  # files saved before labels on votes
    labels.update({b["id"]: b["label"] for b in load_bots()})
    for v in votes:
        labels.update(v.get("labels", {}))
    ratings = bradley_terry(votes)
    rows = []
    for bot_id, rating in ratings.items():
        mine = [v for v in votes if bot_id in (v["a"], v["b"])]
        won = sum(1 for v in mine if (v["winner"] == "a") == (v["a"] == bot_id) and v["winner"] in ("a", "b"))
        tied = sum(1 for v in mine if v["winner"] not in ("a", "b"))
        rows.append({"id": bot_id, "label": labels.get(bot_id, bot_id), "rating": rating, "wins": won,
                     "losses": len(mine) - won - tied, "ties": tied, "battles": len(mine)})
    pairs = Counter(" vs ".join(sorted((labels.get(v["a"], v["a"]), labels.get(v["b"], v["b"])))) for v in votes)
    return {"rows": sorted(rows, key=lambda r: r["rating"], reverse=True), "votes": len(votes),
            "pairs": [{"pair": k, "battles": n} for k, n in sorted(pairs.items())]}


@app.post("/api/arena/reset")
def arena_reset():
    with arena_lock:
        votes = len(load_arena()["votes"])
        save_arena({"votes": []})
    governance.record("arena.reset", None, votes=votes)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
