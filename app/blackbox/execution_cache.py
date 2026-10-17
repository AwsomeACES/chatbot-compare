"""Run-scoped durable caches. Different repeats and new runs always make fresh bot calls."""

import hashlib
import json

from .. import database as db


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def initialize(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS execution_cache (run_id TEXT, kind TEXT, key TEXT, value TEXT, PRIMARY KEY(run_id,kind,key))"
    )


def read(run_id: str, kind: str, key: str) -> dict | None:
    if not run_id:
        return None
    with db.connect() as conn:
        initialize(conn)
        row = conn.execute(
            "SELECT value FROM execution_cache WHERE run_id=? AND kind=? AND key=?",
            (run_id, kind, key),
        ).fetchone()
    return json.loads(row[0]) if row else None


def write(run_id: str, kind: str, key: str, value: dict) -> None:
    if not run_id:
        return
    from .governance import scrub_secrets
    from .studio_engine import LIVE_CONFIGS

    cfg = LIVE_CONFIGS.get(run_id)
    if cfg:
        secrets = (
            cfg._used_secrets
            + [j.token.get_secret_value() for j in cfg.judges if j.token]
            + [t.token.get_secret_value() for t in cfg.targets if t.token]
        )
        value = scrub_secrets(value, secrets)
    with db.connect() as conn:
        initialize(conn)
        conn.execute(
            "INSERT OR REPLACE INTO execution_cache VALUES (?,?,?,?)",
            (run_id, kind, key, json.dumps(value)),
        )


def bot_key(bot: dict, case: dict) -> str:
    return digest(
        {
            "bot": bot,
            "case": case["id"],
            "repeat": case.get("repeat", 1),
            "prompt_hash": digest(
                {"turns": case["turns"], "parallel": case.get("parallel", False)}
            ),
        }
    )


def observation_key(config, slot: int, case: dict) -> str:
    return bot_key({"slot": slot, **config.targets[slot].model_dump(exclude={"token"})}, case)


def checkpoint_turns(case: dict, transcript: list[dict], usage: list, session_id: str = "") -> None:
    """Persist each successful turn before a later network request can fail."""
    from .metering import _context

    context = _context.get() or {}
    config = context.get("config")
    if not config or not config.simple_mode or context.get("bot_slot") not in ("A", "B", "C", "D"):
        return
    slot = "ABCD".index(context["bot_slot"])
    write(
        context["run_id"],
        "bot",
        observation_key(config, slot, case),
        {
            "transcript": transcript,
            "usage": usage,
            "error": None,
            "session_id": session_id,
            "complete": len(transcript) == len(case["turns"]),
        },
    )
