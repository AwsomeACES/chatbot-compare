"""AI governance foundations: the policy file, personal-data masking, a tamper-evident audit log and run provenance.

This module has no dependency on the evaluator, so the evaluator, the server and the CLI scripts can all use it.
The parts that need run results (release gate, sign-off, model cards, risk register, retention) are in
compliance.py.

governance.json (versioned with the code; see the README's "AI governance" section):
  release_gate  the minimum a bot must reach before it can be signed off for release
  models        the approved judge models and bot LLMs (the model inventory)
  data          pii: "redact" (mask unknown personal data before it is sent to a cloud judge), "flag" (send as is,
                but record it) or "off"; retention_days for saved runs
  owners, risks the accountable people and the risk register

Personal data: a value that already appears in the store data or the test case is synthetic test data, so it is
sent as is (the judge needs it to see e.g. that a bot leaked another customer's phone number). Anything shaped like
personal data that appears only in a bot's reply (an email, phone, card, Aadhaar, PAN or UPI id the bot produced on
its own, possibly from a real database) is "unknown": it is counted on the result, and masked before the
conversation goes to a judge that isn't on this machine.

Audit log (runs/audit.jsonl): one JSON line per action (run started / finished / deleted, baseline set, judge label,
sign-off, purge...). Each line holds the SHA-256 of the previous line, so editing or deleting a past line breaks the
chain, which verify_log() reports. Each finished run is sealed with the hash of its results, so a run file edited
after the fact shows up as modified.
"""

import contextvars
import fcntl
import functools
import getpass
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
POLICY_FILE = os.path.join(ROOT, "governance.json")
AUDIT_FILE = os.path.join(ROOT, "runs", "audit.jsonl")
_lock = threading.Lock()

# Who is acting: the server sets it per request (the HTTP Basic user name); scripts default to the OS user.
actor = contextvars.ContextVar("actor", default=None)


def current_actor():
    a = actor.get()
    if a:
        return a
    try:
        return f"{getpass.getuser()} (cli)"
    except (KeyError, OSError):
        return "unknown (cli)"


# ---------- Policy ----------

DEFAULT_POLICY = {"version": 0, "release_gate": {}, "models": {}, "data": {"pii": "redact"}, "owners": {}, "risks": []}


def load_policy():
    try:
        with open(POLICY_FILE) as f:
            return {**DEFAULT_POLICY, **json.load(f)}
    except FileNotFoundError:
        return dict(DEFAULT_POLICY)


def file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256(data):
    return hashlib.sha256((data if isinstance(data, str) else canonical(data)).encode()).hexdigest()


# ---------- Personal data ----------

def _luhn(digits):
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


_VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
               [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
               [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
               [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
               [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
               [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _verhoeff(digits):
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(d)]]
    return c == 0


_digits = lambda s: re.sub(r"\D", "", s)

# Checked in this order; a span already taken by an earlier kind isn't matched again (a card number contains
# Aadhaar-shaped and phone-shaped runs of digits).
PII = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b", re.I), str.lower, None),
    ("upi", re.compile(r"\b[\w.-]{2,}@[a-z]{2,}\b", re.I), str.lower, None),
    ("card", re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])"), _digits, lambda v: _luhn(_digits(v))),
    ("aadhaar", re.compile(r"(?<![\d-])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\d-])"), _digits,
     lambda v: _verhoeff(_digits(v))),
    ("pan", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b"), str.upper, None),
    ("phone", re.compile(r"(?<![\w-])(?:\+?91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?![\d-])"),
     lambda v: _digits(v)[-10:], None),
]
LABELS = {"email": "email address", "upi": "UPI id", "card": "card number", "aadhaar": "Aadhaar number",
          "pan": "PAN", "phone": "phone number"}


def find_pii(text):
    """[(kind, start, end, normalised value)] for everything in text shaped like personal data."""
    found, taken = [], []
    for kind, pattern, norm, valid in PII:
        for m in pattern.finditer(text or ""):
            if any(m.start() < e and s < m.end() for s, e in taken) or (valid and not valid(m.group())):
                continue
            taken.append((m.start(), m.end()))
            found.append((kind, m.start(), m.end(), norm(m.group())))
    return sorted(found, key=lambda f: f[1])


@functools.lru_cache(maxsize=64)
def _known(text):
    return frozenset((k, v) for k, _, _, v in find_pii(text))


def known_values(*texts):
    """The personal-data values in these texts (store data, test case): synthetic, safe to send to a judge."""
    out = set()
    for t in texts:
        if t:
            out |= _known(t)
    return out


def unknown_pii(text, known):
    """{kind: count} of personal data in text that isn't in known."""
    out = {}
    for kind, _, _, value in find_pii(text):
        if (kind, value) not in known:
            out[kind] = out.get(kind, 0) + 1
    return out


def redact(text, known):
    """text with unknown personal data replaced by a typed placeholder such as [phone number], and {kind: count}."""
    parts, counts, pos = [], {}, 0
    for kind, start, end, value in find_pii(text):
        if (kind, value) in known:
            continue
        parts += [text[pos:start], f"[{LABELS[kind]}]"]
        counts[kind] = counts.get(kind, 0) + 1
        pos = end
    return "".join(parts) + text[pos:], counts


def is_local(base_url):
    host = (urlparse(base_url or "").hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def pii_mode(policy=None):
    mode = ((policy or load_policy()).get("data") or {}).get("pii", "redact")
    return mode if mode in ("redact", "flag", "off") else "redact"


def outbound(prompt, known, base_url):
    """What may leave this machine for the judge at base_url: (prompt, {kind: count} masked)."""
    if pii_mode() != "redact" or is_local(base_url):
        return prompt, {}
    return redact(prompt, known)


def add_counts(total, counts):
    for k, n in (counts or {}).items():
        total[k] = total.get(k, 0) + n
    return total


# ---------- Audit log ----------

def _last_entry(f):
    f.seek(0, os.SEEK_END)
    size = f.tell()
    if not size:
        return None
    block = min(size, 65536)
    while True:  # read backwards until a whole last line is in hand
        f.seek(size - block)
        lines = f.read(block).splitlines()
        if len(lines) > 1 or block == size:
            return json.loads(lines[-1]) if lines and lines[-1].strip() else None
        block = min(size, block * 4)


def _entry_hash(entry):
    return sha256({k: v for k, v in entry.items() if k != "hash"})


def record(action, target=None, by=None, **details):
    """Append one action to the audit log. Safe across threads and processes (regress.py, rejudge.py)."""
    os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
    with _lock, open(AUDIT_FILE, "a+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            last = _last_entry(f)
            entry = {"seq": (last["seq"] + 1) if last else 1,
                     "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "actor": by or current_actor(), "action": action, "target": target,
                     "details": details, "prev": last["hash"] if last else None}
            entry["hash"] = _entry_hash(entry)
            f.seek(0, os.SEEK_END)
            f.write((canonical(entry) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return entry


def read_log(limit=None, target=None, action=None):
    """Entries, newest first."""
    try:
        with open(AUDIT_FILE, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []
    rows = [r for r in rows if (target is None or r.get("target") == target)
            and (action is None or r.get("action") == action)]
    rows.reverse()
    return rows[:limit] if limit else rows


def verify_log():
    """Walks the hash chain. {"ok", "entries", "first_bad": seq or None, "problem"}."""
    prev, seq, n = None, 0, 0
    try:
        f = open(AUDIT_FILE, encoding="utf-8")
    except FileNotFoundError:
        return {"ok": True, "entries": 0, "first_bad": None, "problem": None}
    with f:
        for n, line in enumerate(f, 1):
            try:
                e = json.loads(line)
            except ValueError:
                return {"ok": False, "entries": n, "first_bad": seq + 1, "problem": f"line {n} is not valid JSON"}
            problem = ("its hash doesn't match its contents (edited)" if e.get("hash") != _entry_hash(e)
                       else "it doesn't follow the previous entry (an entry was removed or reordered)"
                       if e.get("prev") != prev or e.get("seq") != seq + 1 else None)
            if problem:
                return {"ok": False, "entries": n, "first_bad": e.get("seq", seq + 1),
                        "problem": f"entry {e.get('seq', '?')}: {problem}"}
            prev, seq = e["hash"], e["seq"]
    return {"ok": True, "entries": n, "first_bad": None, "problem": None, "head": prev}


# ---------- Provenance ----------

def seal(run):
    """The hash of what a run measured (its results and comparisons). Recorded when the run finishes."""
    return sha256({"results": sorted((canonical(r) for r in run.get("results", []))),
                   "comparisons": sorted(canonical(c) for c in run.get("comparisons") or [])})


def sealed_hash(run_id):
    """The hash the audit log last recorded for this run, or None."""
    for e in read_log(target=run_id):
        if e["action"] in ("run.finish", "run.rejudge") and e["details"].get("results_sha256"):
            return e["details"]["results_sha256"]
    return None


def integrity(run):
    """Is a finished run still what it was when it was recorded? "intact", "modified" or "unsealed"."""
    recorded = sealed_hash(run["id"])
    if recorded is None:
        return "unsealed"
    return "intact" if recorded == seal(run) else "modified"


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def provenance(bot_configs, suite_path):
    """Everything needed to say later exactly what produced a run."""
    commit = _git("rev-parse", "HEAD")
    policy = load_policy()
    return {"git_commit": commit or None, "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no"))
            if commit else None,
            "suite_sha256": file_sha256(suite_path), "bots_sha256": sha256(bot_configs),
            "policy_version": policy.get("version"), "policy_sha256": file_sha256(POLICY_FILE),
            "started_by": current_actor()}
