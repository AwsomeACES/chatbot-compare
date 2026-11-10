"""Serve the bundled synthetic demo chatbot on loopback.

Run this in a second terminal, then point Studio at it:

    python scripts/demo_bot.py                      # serves 127.0.0.1:2709
    python scripts/demo_bot.py --port 3000

In Studio, use the API link ``http://127.0.0.1:2709/chat``, set the response
field to ``answer``, switch the AI Judge off and import the demo Cases from
``GET /api/blackbox/case-set/demo``. Nothing here calls a provider, so the
demo costs nothing and needs no account.

This is a deliberately separate process. Studio's own API requires a
cross-site-request header on every write, which a target chatbot has no reason
to send, so the demo bot is served outside that boundary rather than weakening
it. It is Studio's own reviewed fixture, never a user-supplied application.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.blackbox import demo_bot  # noqa: E402

app = FastAPI(title="AI Agent Studio synthetic demo bot")


class Message(BaseModel):
    """One chat turn. ``conversation_id`` is accepted and ignored."""

    model_config = {"extra": "ignore"}
    message: str = Field(max_length=20000)


@app.get("/health")
def health() -> dict:
    return {"service": "studio-synthetic-demo", "demo": True}


@app.post("/chat")
def chat(payload: Message) -> dict:
    """Answer deterministically from the bundled synthetic fixture."""
    if not isinstance(payload.message, str):
        raise HTTPException(422, "Send a JSON body with a 'message' string.")
    return {
        "answer": demo_bot.reply(payload.message),
        "demo": True,
        "disclosure": demo_bot.DEMO_LABEL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=demo_bot.DEMO_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("The demo bot only binds loopback addresses.", file=sys.stderr)
        return 2

    import uvicorn

    print(f"Synthetic demo bot: http://{args.host}:{args.port}/chat")
    print(demo_bot.DEMO_LABEL)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
