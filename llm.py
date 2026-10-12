"""The free models this app uses to grade and to write test cases, through any OpenAI-compatible chat API.

Default: Google's Gemini free tier (an AI Studio key in GOOGLE_API_KEY). The same code talks to a local Ollama
("http://localhost:11434/v1", no key) or Groq's free tier: set the base URL, model and key variable.

  JUDGE_BASE_URL     default https://generativelanguage.googleapis.com/v1beta/openai
  JUDGE_MODEL        default gemini-3.7-flash,gemini-3.5-flash,gemini-2.5-flash: a comma-separated list; when one
                     is overloaded or rate-limited the next is tried (free tiers often are), and each verdict
                     records which model gave it
  JUDGE_API_KEY_ENV  env var holding the key, default GOOGLE_API_KEY ("" = no key, e.g. Ollama)
  JUDGE_RPM          requests per minute to stay under (free tiers are rate-limited), default 10; 0 = no limit
  JUDGE_DAILY_LIMIT  requests a day the judge's plan allows (e.g. a free tier's daily quota); the dashboard warns
                     before a run that needs more. Unset = unknown, no warning
  JUDGE_FALLBACK_*   an optional fallback judge (off unless JUDGE_FALLBACK_MODEL is set; default base URL is the local
                     Ollama): when the main judge stays rate-limited or out of quota after its retries, the call goes to
                     it instead of failing, and the verdict records which model gave it
  SECOND_JUDGE_*     the same for the optional second judge (a different model family); off unless
                     SECOND_JUDGE_MODEL is set, default base URL is the local Ollama. E.g. Kimi on NVIDIA NIM's free
                     API: SECOND_JUDGE_BASE_URL=https://integrate.api.nvidia.com/v1,
                     SECOND_JUDGE_MODEL=moonshotai/kimi-k2.6, SECOND_JUDGE_API_KEY_ENV=NVIDIA_API_KEY

Every reply is constrained to a JSON schema (response_format json_schema), so a verdict always parses. Rate-limit
and overload errors are retried with backoff; a daily quota that stays exhausted ends as a BotError, which the
evaluator records on that case ("judge error"), and rejudge.py can fill in later.
"""

import json
import os
import threading
import time

import httpx2
from dotenv import load_dotenv

from adapters import BotError, normalize_usage
from governance import is_local

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))  # also for rejudge.py / reword.py

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
OLLAMA = "http://localhost:11434/v1"
KEY_PAGES = {"GOOGLE_API_KEY": "https://aistudio.google.com/apikey", "NVIDIA_API_KEY": "https://build.nvidia.com"}
TIMEOUT = float(os.environ.get("JUDGE_TIMEOUT", "300"))
RETRIES = 4
RETRY_STATUS = {429, 500, 502, 503, 504}


class JudgeError(BotError):
    """A judge call that failed after the API had already charged for it. spent: [{model, usage, local?}], one per
    answered call, so the tokens still count in the judge's cost."""

    def __init__(self, message, spent=()):
        super().__init__(message)
        self.spent = [s for s in spent if s and s.get("usage")]


def spent_of(data):
    """One call's spend from a structured() reply: {model, usage, local?}, or None when it reported no tokens."""
    if not isinstance(data, dict) or not data.get("_usage"):
        return None
    return {"model": data.get("_model") or "unknown", "usage": data["_usage"], **({"local": True} if data.get("_local") else {})}


def spent_from(error):
    """The tokens a failed judge call still spent ([] when none)."""
    return list(getattr(error, "spent", None) or [])


class Endpoint:
    """One model behind an OpenAI-compatible API, with its own request pacing."""

    def __init__(self, base_url, model, api_key_env="", rpm=0, fallback=None, daily_limit=None):
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.base_url, self.model, self.api_key_env = base_url.rstrip("/"), ",".join(self.models), api_key_env
        self.rpm, self.daily_limit = rpm, daily_limit
        self.fallback = fallback  # another Endpoint, asked when this one stays rate-limited or out of quota
        self.interval = 60 / rpm if rpm else 0
        self._next = 0.0
        self._lock = threading.Lock()

    def __bool__(self):
        return bool(self.model)

    def _wait_turn(self):
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        time.sleep(start - now)

    def _headers(self):
        if not self.api_key_env:
            return {}
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            page = KEY_PAGES.get(self.api_key_env)
            raise BotError(f"Set {self.api_key_env} in .env for the judge ({self.model})"
                           + (f"; a free key comes from {page}" if page else ""))
        return {"Authorization": f"Bearer {key}"}

    def structured(self, system, prompt, schema, name):
        """The model's reply to one prompt, as a dict matching schema, plus "_model": the model that answered and
        "_usage": the tokens the API reported for this call ({input_tokens, output_tokens}; left out when none) and
        "_local": true when the model runs on this machine (no API charge).
        A retryable error (overloaded, rate-limited) moves on to the next model in the list, then backs off."""
        body = {"temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}}
        headers = self._headers()
        tries = (RETRIES + 1) * len(self.models)
        retryable = False
        for attempt in range(tries):
            model = body["model"] = self.models[attempt % len(self.models)]
            self._wait_turn()
            try:
                r = httpx2.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=TIMEOUT)
            except httpx2.HTTPError as e:
                error = f"Could not reach {self.base_url}: {e}"
            else:
                if r.status_code < 400:
                    meta = {"_model": model, **({"_usage": u} if (u := self._usage(r)) else {}),
                            **({"_local": True} if is_local(self.base_url) else {})}
                    try:
                        return {**self._parse(r, model), **meta}
                    except BotError as e:  # answered (and charged) but unusable
                        raise JudgeError(str(e), [spent_of(meta)]) from e
                error = f"{model}: HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in RETRY_STATUS:
                    raise BotError(error)
                retryable = True
            if attempt < tries - 1 and (attempt + 1) % len(self.models) == 0:  # every model failed this round
                time.sleep(min(60, 5 * 2 ** (attempt // len(self.models))))
        if retryable and self.fallback:  # out of quota or overloaded for good: grade with the fallback instead
            return self.fallback.structured(system, prompt, schema, name)
        raise BotError(error)

    @staticmethod
    def _usage(r):
        try:
            return normalize_usage(r.json().get("usage"))
        except (ValueError, AttributeError):
            return None

    def _parse(self, r, model):
        try:
            text = r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise BotError(f"{model} returned an unexpected response: {r.text[:200]}") from e
        text = text.strip()
        if text.startswith("```"):  # some models wrap JSON in a code fence despite the schema
            text = text.strip("`").removeprefix("json").strip()
        try:
            return json.loads(text)
        except ValueError as e:
            raise BotError(f"{model} did not return valid JSON: {text[:200]}") from e


def _endpoint(prefix, base_url, model, key_env, rpm, fallback=None):
    daily = os.environ.get(f"{prefix}_DAILY_LIMIT", "").strip()
    return Endpoint(os.environ.get(f"{prefix}_BASE_URL", base_url), os.environ.get(f"{prefix}_MODEL", model),
                    os.environ.get(f"{prefix}_API_KEY_ENV", key_env), float(os.environ.get(f"{prefix}_RPM", rpm)),
                    fallback=fallback, daily_limit=int(daily) if daily else None)


_FALLBACK = _endpoint("JUDGE_FALLBACK", OLLAMA, "", "", "0")
JUDGE = _endpoint("JUDGE", GEMINI, "gemini-3.7-flash,gemini-3.5-flash,gemini-2.5-flash", "GOOGLE_API_KEY", "10",
                  fallback=_FALLBACK or None)
SECOND_JUDGE = _endpoint("SECOND_JUDGE", OLLAMA, "", "", "0")
