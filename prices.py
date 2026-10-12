"""Model prices from LiteLLM's public catalogue, kept as dated snapshots so a run's cost never changes after the fact.

Prices in bots.json ("pricing" on a bot, "judge_pricing" for the judge) always win: the catalogue holds list prices,
so a free tier or a negotiated rate must be written there. The catalogue only fills in a model with no price of its
own, looked up by the bot's "model" field (the API's model id, e.g. "gpt-5-mini") or by the judge's model id.

Update the snapshot from the dashboard (Costs > Update prices) or: .venv/bin/python prices.py
Each update is saved as runs/prices/litellm-YYYY-MM-DD.json; a run copies the prices it uses into itself when it
starts, so a later update changes only new runs.
"""

import glob
import json
import os
import sys
import time

import httpx2

ROOT = os.path.dirname(os.path.abspath(__file__))
PRICES_DIR = os.path.join(ROOT, "runs", "prices")
CATALOG_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
PER_MILLION = 1_000_000
FIELDS = {"input": "input_cost_per_token", "output": "output_cost_per_token",
          "cache_read": "cache_read_input_token_cost", "cache_write": "cache_creation_input_token_cost"}


def _number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def parse(raw):
    """LiteLLM's catalogue -> {model: {input, output, cache_read?, cache_write?}} in USD per million tokens,
    chat models only, skipping entries without both an input and an output price."""
    out = {}
    for name, v in (raw or {}).items():
        if not isinstance(v, dict) or v.get("mode") != "chat" or name == "sample_spec":
            continue
        price = {k: round(n * PER_MILLION, 6) for k, f in FIELDS.items() if (n := _number(v.get(f))) is not None}
        if "input" in price and "output" in price:
            out[name] = price
    return out


def update(fetch=None):
    """Download the catalogue and save it as today's snapshot. Returns {"date", "models", "path"}."""
    fetch = fetch or (lambda url: httpx2.get(url, timeout=60, follow_redirects=True))
    r = fetch(CATALOG_URL)
    if r.status_code >= 400:
        raise RuntimeError(f"Could not download the LiteLLM price catalogue: HTTP {r.status_code}")
    models = parse(r.json())
    if not models:
        raise RuntimeError("The LiteLLM price catalogue had no chat model prices")
    date = time.strftime("%Y-%m-%d")
    os.makedirs(PRICES_DIR, exist_ok=True)
    path = os.path.join(PRICES_DIR, f"litellm-{date}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"source": "LiteLLM", "url": CATALOG_URL, "date": date, "models": models}, f)
    os.replace(tmp, path)
    return {"date": date, "models": len(models), "path": path}


def latest():
    """The newest saved snapshot, or None when prices were never downloaded."""
    paths = sorted(glob.glob(os.path.join(PRICES_DIR, "litellm-*.json")))
    for path in reversed(paths):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def lookup(model, snapshot):
    """The catalogue price of one model id, with its source, or None. Matches the id exactly, then a provider-
    prefixed id ending in it ("gemini/gemini-2.5-flash" for "gemini-2.5-flash"), shortest first."""
    if not model or not snapshot:
        return None
    models, want = snapshot.get("models") or {}, model.strip().lower()
    names = {k.lower(): k for k in models}
    key = names.get(want) or next((names[k] for k in sorted(names, key=len) if k.endswith("/" + want)), None)
    if not key:
        return None
    return {**models[key], "source": f"LiteLLM list price ({snapshot.get('date')}, {key}), USD per million tokens"}


if __name__ == "__main__":
    try:
        info = update()
    except (RuntimeError, httpx2.HTTPError, ValueError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"Saved {info['models']} model prices to {info['path']}")
