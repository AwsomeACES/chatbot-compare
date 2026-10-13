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

A plain hash chain can be recomputed by anyone who can write the file, and cutting lines off its end leaves a valid
chain. So each line also carries an HMAC with a secret key kept outside the project (AUDIT_KEY, else a key file
created in AUDIT_KEY_DIR, default ~/.config/chatbot-compare, readable by this OS user only), and the latest entry's
seq and hash are kept there too ("audit.head"). Rewriting the chain then needs the key, and a shortened log no
longer reaches the head. Someone who can log in as this OS user can still read the key, so the head is also
published off this machine (anchor()): after every sign-off and nightly run it goes to AUDIT_ANCHOR_WEBHOOK (default
REGRESSION_WEBHOOK, a team chat channel) and/or AUDIT_ANCHOR_S3 (s3://bucket/prefix; give the bucket Object Lock so
nobody can change what was written). verify_against(seq, hash) then checks the log against a head copied from there.
"""

import contextvars
import fcntl
import functools
import getpass
import hashlib
import hmac
import secrets
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
KEY_DIR = os.path.expanduser(os.environ.get("AUDIT_KEY_DIR", "~/.config/chatbot-compare"))
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
_words = lambda s: re.sub(r"\s+", " ", s).strip().lower()

# Names and street addresses have no fixed shape, so only the clear cases are matched: a capitalised name right after
# "my name is" / "customer" / a title (Mr, Mrs, Dr, Shri...), and an address with a street word and a 6-digit PIN
# code, or a PIN code labelled as one. The value is the named group "v" when there is one.
_NAME = (r"(?i:\b(?:(?:my|his|her|their|the customer'?s?|customer)\s+name\s+is|name\s*:|customer\s*:?)\s+"
         r"|\b(?:mr|mrs|ms|miss|dr|shri|smt)\.?\s+)"
         r"(?P<v>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
_STREET = r"(?:road|rd|street|st|nagar|colony|lane|marg|sector|layout|block|apartments?|society|flat|floor|main|cross)"
_ADDRESS = (r"\b\d{1,4}[A-Za-z]?[,/ ]+[A-Za-z0-9 .,'/-]{2,80}?\b" + _STREET + r"\b[A-Za-z0-9 .,'/-]{0,80}?\b[1-9]\d{5}\b"
            r"|\b(?:pin\s*code|pincode|pin)\s*[:-]?\s*(?P<v>[1-9]\d{5})\b")

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
    ("address", re.compile(_ADDRESS, re.I), _words, None),
    ("name", re.compile(_NAME), _words, None),
]
LABELS = {"email": "email address", "upi": "UPI id", "card": "card number", "aadhaar": "Aadhaar number",
          "pan": "PAN", "phone": "phone number", "address": "address", "name": "name", "person": "name"}
TEXT_MATCHED = {"name", "address", "person"}  # known when the value appears anywhere in the store data or test case


_NER = None  # the spaCy pipeline, loaded on first use; False when it isn't installed or PII_NER=off


def _ner():
    """spaCy's small English model, for names with no cue around them ("Meera called earlier"). Optional: without it
    (pip install spacy && python -m spacy download en_core_web_sm), only the patterns above find names."""
    global _NER
    if _NER is None:
        _NER = False
        if os.environ.get("PII_NER", "auto").lower() not in ("off", "0", "false", "no"):
            try:
                import spacy
                _NER = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "tagger", "attribute_ruler"])
            except (ImportError, OSError):
                pass
    return _NER or None


def _person_names(text):
    """(start, end) of each person's name spaCy finds."""
    nlp = _ner()
    if nlp is None or not text:
        return []
    out = []
    for e in nlp(text.replace("\u2019", "'").replace("\u2018", "'")).ents:  # same length: offsets still match text
        name = re.sub(r"['\u2019]s$", "", e.text)  # "Rahul Sharma's" is Rahul Sharma
        if e.label_ == "PERSON" and name[:1].isupper() and len(name) > 2 and not name.isupper():
            out.append((e.start_char, e.start_char + len(name)))
    return out


def find_pii(text):
    """[(kind, start, end, normalised value)] for everything in text shaped like personal data."""
    found, taken = [], []
    for kind, pattern, norm, valid in PII:
        for m in pattern.finditer(text or ""):
            g = "v" if "v" in pattern.groupindex and m.group("v") else 0
            start, end = m.start(g), m.end(g)
            if any(start < e and s < end for s, e in taken) or (valid and not valid(m.group(g))):
                continue
            taken.append((start, end))
            found.append((kind, start, end, norm(m.group(g))))
    for start, end in _person_names(text):
        if not any(start < e and s < end for s, e in taken):
            taken.append((start, end))
            found.append(("person", start, end, _words(text[start:end])))
    return sorted(found, key=lambda f: f[1])


@functools.lru_cache(maxsize=64)
def _known(text):
    return frozenset((k, v) for k, _, _, v in find_pii(text))


def known_values(*texts):
    """The personal-data values in these texts (store data, test case): synthetic, safe to send to a judge. Also holds
    each text itself ("_text"), so a name or address counts as known when it appears there in any form."""
    out = set()
    for t in texts:
        if t:
            out |= _known(t) | {("_text", _words(t))}
    return out


def is_known(kind, value, known):
    if (kind, value) in known:
        return True
    texts = [t for k, t in known if k == "_text"]
    if kind == "person":
        # A name the model found with no cue around it: when any word of it is in the store data or test case it is a
        # product or brand ("Pulse Max" next to "Pulse Pro"), not a person, and the judge must see it as written.
        return any(re.search(rf"\b{re.escape(w)}\b", t) for w in value.split() for t in texts)
    return kind in TEXT_MATCHED and any(value in t for t in texts)


def unknown_pii(text, known):
    """{kind: count} of personal data in text that isn't in known."""
    out = {}
    for kind, _, _, value in find_pii(text):
        if not is_known(kind, value, known):
            out[kind] = out.get(kind, 0) + 1
    return out


def redact(text, known):
    """text with unknown personal data replaced by a typed placeholder such as [phone number], and {kind: count}."""
    parts, counts, pos = [], {}, 0
    for kind, start, end, value in find_pii(text):
        if is_known(kind, value, known):
            continue
        parts += [text[pos:start], f"[{LABELS[kind]}]"]
        counts[kind] = counts.get(kind, 0) + 1
        pos = end
    return "".join(parts) + text[pos:], counts


def is_local(base_url):
    host = (urlparse(base_url or "").hostname or "").lower()
    # Only this machine. A "*.local" (mDNS) name is another machine on the network, so it needs consent too.
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


CLOUD_BOT_TYPES = {"claude_bedrock"}  # bots this app reaches through a cloud API, with no URL of their own


def remote_bots(bots):
    """The bots a run would send test messages to over the network (not on this machine)."""
    return [b.get("label") or b["id"] for b in bots
            if b.get("type") in CLOUD_BOT_TYPES or not is_local(b.get("base_url") or b.get("url") or "")]


def remote_judges(endpoints):
    """The judge models that would receive conversations (with personal data masked) over the network."""
    return [m for ep in endpoints if not is_local(ep.base_url) for m in ep.models]


class ConsentError(ValueError):
    pass


def check_consent(bots, judge_endpoints, consent):
    """What a run may do, as the person starting it allowed. consent: {"send_to_bots": bool, "share_with_judge": bool}
    from the dashboard, or None for a script the operator started (regress.py, nightly.sh), which is recorded as such.
    Sending test messages to a bot that isn't on this machine, and sharing conversations with a judge that isn't,
    each need their own yes. Returns the record saved on the run; raises ConsentError naming what's missing."""
    rbots, rjudges = remote_bots(bots), remote_judges(judge_endpoints)
    record = {"remote_bots": rbots, "remote_judges": rjudges, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "by": current_actor()}
    if consent is None:
        return {**record, "send_to_bots": None, "share_with_judge": None, "given_by": "script"}
    missing = []
    if rbots and not consent.get("send_to_bots"):
        missing.append(f"send test messages to {', '.join(rbots)} (not on this machine)")
    if rjudges and not consent.get("share_with_judge"):
        missing.append(f"share the conversations with the AI judge ({', '.join(rjudges)}; personal data is masked first)")
    if missing:
        raise ConsentError("Allow this run to " + " and to ".join(missing) + ".")
    return {**record, "send_to_bots": bool(consent.get("send_to_bots")),
            "share_with_judge": bool(consent.get("share_with_judge")), "given_by": "dashboard"}


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
    return sha256({k: v for k, v in entry.items() if k not in ("hash", "mac")})


def _audit_key(create=False):
    """The secret the log's HMACs use: AUDIT_KEY, else KEY_DIR/audit.key (made on first use, mode 600)."""
    if os.environ.get("AUDIT_KEY"):
        return os.environ["AUDIT_KEY"].encode()
    path = os.path.join(KEY_DIR, "audit.key")
    try:
        with open(path, "rb") as f:
            return f.read().strip()
    except FileNotFoundError:
        if not create:
            return None
    os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(secrets.token_hex(32).encode())
    return _audit_key()


def _mac(key, entry_hash):
    return hmac.new(key, entry_hash.encode(), hashlib.sha256).hexdigest()


def _head_path():
    return os.path.join(KEY_DIR, "audit.head")


def _read_head():
    try:
        with open(_head_path()) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


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
            key = _audit_key(create=True)
            entry["mac"] = _mac(key, entry["hash"])
            f.seek(0, os.SEEK_END)
            f.write((canonical(entry) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())
            head = {"file": os.path.abspath(AUDIT_FILE), "seq": entry["seq"], "hash": entry["hash"]}
            tmp = _head_path() + ".tmp"
            with open(tmp, "w") as h:
                json.dump({**head, "mac": _mac(key, canonical(head))}, h)
            os.replace(tmp, _head_path())
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
    """Walks the hash chain and checks each line's HMAC, then that the log still reaches the recorded head.
    {"ok", "entries", "first_bad": seq or None, "problem", "head"}. Lines written before HMACs existed are accepted
    without one, but once a line has one every later line must."""
    key, keyed = _audit_key(), False
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
            keyed = keyed or "mac" in e
            problem = ("its hash doesn't match its contents (edited)" if e.get("hash") != _entry_hash(e)
                       else "it doesn't follow the previous entry (an entry was removed or reordered)"
                       if e.get("prev") != prev or e.get("seq") != seq + 1
                       else "it has no HMAC although earlier entries do (rewritten)" if keyed and "mac" not in e
                       else "its HMAC doesn't match (rewritten without the audit key)"
                       if "mac" in e and key and not hmac.compare_digest(e["mac"], _mac(key, e["hash"])) else None)
            if problem:
                return {"ok": False, "entries": n, "first_bad": e.get("seq", seq + 1),
                        "problem": f"entry {e.get('seq', '?')}: {problem}"}
            prev, seq = e["hash"], e["seq"]
    head = _read_head()
    if head and key and head.get("file") == os.path.abspath(AUDIT_FILE):
        signed = {k: head.get(k) for k in ("file", "seq", "hash")}
        if not hmac.compare_digest(str(head.get("mac")), _mac(key, canonical(signed))):
            return {"ok": False, "entries": n, "first_bad": None, "problem": "the recorded head was edited"}
        if seq < head["seq"]:
            return {"ok": False, "entries": n, "first_bad": seq + 1,
                    "problem": f"the log ends at entry {seq} but entry {head['seq']} was written (entries cut off)"}
        if seq == head["seq"] and prev != head["hash"]:
            return {"ok": False, "entries": n, "first_bad": seq, "problem": "the last entry isn't the one recorded"}
    return {"ok": True, "entries": n, "first_bad": None, "problem": None, "head": prev, "keyed": bool(key and keyed)}


def verify_against(seq, head_hash):
    """Is entry seq still the one whose hash was published? Catches a log rewritten by someone who had the key."""
    for e in read_log():
        if e.get("seq") == seq:
            ok = e.get("hash") == head_hash
            return {"ok": ok, "problem": None if ok else f"entry {seq} differs from the published head (log rewritten)"}
    return {"ok": False, "problem": f"entry {seq} is missing (log cut off or rewritten)"}


def _post_anchor(url, text):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).close()


def _put_anchor_s3(target, record):
    import boto3
    bucket, _, prefix = target.removeprefix("s3://").partition("/")
    key = f"{prefix.rstrip('/') + '/' if prefix else ''}audit-head-{record['seq']:08d}-{record['hash'][:16]}.json"
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=canonical(record).encode(), ContentType="application/json")
    return f"s3://{bucket}/{key}"


def latest_s3_anchor(target=None):
    """The newest head written to AUDIT_ANCHOR_S3 ({"seq", "hash", ...}), or None when none is configured or found."""
    target = target or os.environ.get("AUDIT_ANCHOR_S3")
    if not target:
        return None
    import boto3
    bucket, _, prefix = target.removeprefix("s3://").partition("/")
    prefix = (prefix.rstrip("/") + "/" if prefix else "") + "audit-head-"
    s3, keys, token = boto3.client("s3"), [], None
    while True:
        page = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, **({"ContinuationToken": token} if token else {}))
        keys += [o["Key"] for o in page.get("Contents", [])]
        token = page.get("NextContinuationToken")
        if not token:
            break
    if not keys:
        return None
    key = max(keys)  # zero-padded seq: the newest sorts last
    return {**json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read()), "key": f"s3://{bucket}/{key}"}


def anchor(reason, post=None, put=None):
    """Publish the log's current head off this machine. Returns {"seq", "hash", "sent": [where]} or None when the log is
    empty or broken (a broken log is reported, not anchored). Failures to publish are returned in "errors", never
    raised: the action that triggered it has already happened."""
    v = verify_log()
    if not v["ok"] or not v.get("head"):
        return None
    record = {"seq": v["entries"], "hash": v["head"], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "reason": reason, "host": os.uname().nodename}
    sent, errors = [], []
    url = os.environ.get("AUDIT_ANCHOR_WEBHOOK") or os.environ.get("REGRESSION_WEBHOOK")
    if url:
        try:
            (post or _post_anchor)(url, f"Chatbot Compare audit head #{record['seq']}: {record['hash']} ({reason}). "
                                        f"Check it with: compliance.py audit --head {record['seq']}:{record['hash']}")
            sent.append("webhook")
        except Exception as e:
            errors.append(f"webhook: {e}")
    if target := os.environ.get("AUDIT_ANCHOR_S3"):
        try:
            sent.append((put or _put_anchor_s3)(target, record))
        except Exception as e:
            errors.append(f"S3: {e}")
    return {**record, "sent": sent, **({"errors": errors} if errors else {})}


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


CODE_FILES = (".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".toml", ".cfg", ".txt")
SKIP_DIRS = {".git", ".venv", "venv", ".venv-local", "node_modules", "__pycache__", "chroma_db", "site-packages", "dist",
             "build", ".pytest_cache"}


def tree_sha256(root):
    """Hash of a source tree's code files (not its virtualenvs, caches or databases), for code with no git history,
    e.g. a bot unzipped from an archive."""
    h = hashlib.sha256()
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for name in sorted(f for f in files if f.endswith(CODE_FILES)):
            path = os.path.join(d, name)
            with open(path, "rb") as f:
                h.update(os.path.relpath(path, root).encode() + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def source_info(source):
    """Which code a bot under test ran: bots.json "source" ({"path", "sha256"?, "note"?}, or just the path).
    A git checkout: its commit, branch, uncommitted changes and how far it is from its upstream (as last fetched).
    Anything else: a hash of its code files, checked against the "sha256" pinned in bots.json. "own_code" is False when
    the code isn't the owner's version (local commits, uncommitted changes or a hash that isn't the pinned one)."""
    if isinstance(source, str):
        source = {"path": source}
    root = os.path.expanduser(source.get("path") or "")
    out = {"path": source.get("path"), **({"note": source["note"]} if source.get("note") else {})}
    if not os.path.isdir(root):
        return {**out, "missing": True, "own_code": None}
    if os.path.isdir(os.path.join(root, ".git")):
        git = lambda *a: subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, timeout=10).stdout.strip()
        try:
            counts = git("rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
            out.update(kind="git", commit=git("rev-parse", "HEAD") or None, branch=git("rev-parse", "--abbrev-ref", "HEAD"),
                       upstream=git("rev-parse", "--abbrev-ref", "@{upstream}") or None,
                       dirty=bool(git("status", "--porcelain", "--untracked-files=no")))
        except (OSError, subprocess.SubprocessError):
            return {**out, "kind": "git", "own_code": None}
        behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (None, None)
        out.update(ahead=ahead, behind=behind)
        out["own_code"] = not out["dirty"] and ahead == 0 if out["upstream"] else None
        return out
    digest = tree_sha256(root)
    pinned = source.get("sha256")
    return {**out, "kind": "files", "sha256": digest, "pinned": pinned,
            "own_code": (digest == pinned) if pinned else None}


def provenance(bot_configs, suite_path):
    """Everything needed to say later exactly what produced a run, including the code each bot ran."""
    commit = _git("rev-parse", "HEAD")
    policy = load_policy()
    sources = {}
    for b in bot_configs:
        if b.get("source"):
            try:
                sources[b["id"]] = source_info(b["source"])
            except OSError as e:
                sources[b["id"]] = {"path": str(b["source"]), "error": str(e), "own_code": None}
    return {"git_commit": commit or None, "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no"))
            if commit else None,
            "suite_sha256": file_sha256(suite_path), "bots_sha256": sha256(bot_configs),
            **({"bot_sources": sources} if sources else {}),
            "policy_version": policy.get("version"), "policy_sha256": file_sha256(POLICY_FILE),
            "started_by": current_actor()}
