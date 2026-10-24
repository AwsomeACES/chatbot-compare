"""Tamper-evident audit records, integrity cards and privacy-aware export.

The SQLite anchor detects edits/truncation of a report, not an attacker replacing
both the database and its backups. Hashes are integrity checks, not signatures.
"""

import copy
import json
import re
from datetime import datetime, timezone

from .. import database as db
from ..config import ROOT
from .execution_cache import digest

ZERO = "0" * 64
PII_PATTERNS = {
    "email": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    "phone": r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\d[ .()-]?){10,15}(?!\w)",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credential": r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,})\b",
}


#: Public, non-personal identifiers whose shape cannot be a contact detail. Only these exact
#: tokens are exempt from the generic rules; the text around them is still redacted in full.
#: The generic phone rule matches any run of 10-15 digits, which otherwise masked advisory
#: numbers, UUIDs and timestamps.
STRUCTURED_IDS = re.compile(
    r"""(?ix)
    \b(?:
        [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}   # UUID
      | CVE-\d{4}-\d{4,7}                                              # CVE
      | GHSA(?:-[0-9a-z]{4,}){3}                                       # GitHub advisory
      | (?:OSV|PYSEC|GHSA|GO|RUSTSEC|DSA|DLA|RHSA|RHBA|USN|ALAS|ALSA|ELSA|SUSE-SU)
        -\d{4}-[0-9a-z]{1,8}                                           # distro / ecosystem
      | CWE-\d{1,5}                                                    # weakness class
      | \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?
        (?:Z|[+-]\d{2}:?\d{2})?                                       # ISO 8601 instant
    )\b
    """
)

#: Why an identifier exemption is not a general redaction bypass, for export disclosure.
ID_EXEMPTION_NOTE = (
    "Recognised public identifiers (UUIDs, CVE/GHSA/OSV/CWE references and ISO 8601 "
    "timestamps) are kept readable because the generic number rule would otherwise mask them. "
    "Everything around them, including contact details on the same line, is still redacted. "
    "A value deliberately formatted to look like one of these identifiers would be kept, so "
    "this is a baseline for accidental disclosure, not an adversarial filter."
)

LIMITATION_NOTE = (
    "Names, postal addresses, account handles, free-text personal details and identifiers "
    "specific to your organisation are not detected by pattern matching. Review context before "
    "sharing an export."
)


#: Rules specific enough to run over the whole string. They must go first: an identifier can be
#: a substring of an email address, and exempting it there would let the address through.
SPECIFIC_RULES = ("email", "ssn", "credential")
#: The generic rule matches any run of 10-15 digits, so it is the only one the exemption covers.
GENERIC_RULES = ("phone",)


def _apply(text: str, kinds) -> str:
    for kind in kinds:
        text = re.sub(PII_PATTERNS[kind], f"[REDACTED {kind}]", text, flags=re.I)
    return text


def redact_text(text: str) -> str:
    """Redact one string, leaving recognised public structured identifiers readable.

    Specific rules run over the whole string first, so an identifier embedded in an email
    address is redacted with it. Only the generic number rule skips identifier tokens.
    """
    text = _apply(text, SPECIFIC_RULES)
    pieces, last = [], 0
    for match in STRUCTURED_IDS.finditer(text):
        pieces.append(_apply(text[last : match.start()], GENERIC_RULES))
        pieces.append(match.group(0))
        last = match.end()
    pieces.append(_apply(text[last:], GENERIC_RULES))
    return "".join(pieces)


def redact(value: object) -> object:
    """PII regex baseline; names/addresses need contextual review before sharing.

    Public structured identifiers survive (see STRUCTURED_IDS); credentials, email addresses,
    telephone numbers and national identifiers around them do not.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(x) for x in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


def scrub_secrets(value: object, secrets: list[str]) -> object:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [scrub_secrets(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: scrub_secrets(v, secrets) for k, v in value.items()}
    return value


def initialize(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_chain (run_id TEXT, sequence INTEGER, hash TEXT, body TEXT, PRIMARY KEY(run_id,sequence))"
    )


def append(run: dict, event: str, **details) -> None:
    reserved = {"sequence", "run_id", "at", "config_hash", "suite_version", "previous_hash", "hash"}
    if reserved.intersection(details):
        raise ValueError("Audit details cannot overwrite chain metadata")
    events = run.setdefault("audit", [])
    # Old unchained records stay explicitly legacy; never silently bless them.
    previous = events[-1].get("hash", ZERO) if events else ZERO
    entry = {
        "sequence": len(events),
        "run_id": run.get("id", "unpersisted"),
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "config_hash": digest(run.get("config", {})),
        "suite_version": run.get("protocol_snapshot", {}).get("protocol_version", "legacy"),
        "previous_hash": previous,
        **copy.deepcopy(details),
    }
    # Passwords must be scrubbed BEFORE hashing. PII redaction is an export step.
    from .studio_engine import LIVE_CONFIGS

    cfg = LIVE_CONFIGS.get(run.get("id"))
    if cfg:
        secrets = list(cfg._used_secrets)
        secrets += [j.token.get_secret_value() for j in cfg.judges if j.token]
        secrets += [t.token.get_secret_value() for t in cfg.targets if t.token]
        entry = scrub_secrets(entry, secrets)
    entry["hash"] = digest(entry)
    if run.get("id"):
        with db.connect() as conn:
            initialize(conn)
            tail = conn.execute(
                "SELECT hash FROM audit_chain WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                (run["id"],),
            ).fetchone()
            if tail and tail[0] != previous:
                raise ValueError(
                    "Audit anchor mismatch: history was changed or another writer owns this run."
                )
            conn.execute(
                "INSERT INTO audit_chain VALUES (?,?,?,?)",
                (run["id"], entry["sequence"], entry["hash"], json.dumps(entry)),
            )
    events.append(entry)


def verify(run: dict) -> dict:
    events = run.get("audit", [])
    if not events:
        with db.connect() as conn:
            initialize(conn)
            anchored = conn.execute(
                "SELECT 1 FROM audit_chain WHERE run_id=? LIMIT 1", (run.get("id", ""),)
            ).fetchone()
        return {
            "valid": False if anchored else None,
            "reason": "Database anchor detects removed audit history"
            if anchored
            else "No audit records",
            "events": 0,
        }
    previous = ZERO
    legacy = 0
    for index, event in enumerate(events):
        if "hash" not in event:
            legacy += 1
            continue
        body = {k: v for k, v in event.items() if k != "hash"}
        if (
            event.get("sequence") != index
            or event.get("previous_hash") != previous
            or digest(body) != event["hash"]
        ):
            return {
                "valid": False,
                "reason": f"Invalid audit record {index}",
                "events": len(events),
            }
        previous = event["hash"]
    anchored = False
    if run.get("id"):
        with db.connect() as conn:
            initialize(conn)
            tail = conn.execute(
                "SELECT hash,sequence FROM audit_chain WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                (run["id"],),
            ).fetchone()
        if tail:
            anchored = True
            if tail[0] != previous or tail[1] != len(events) - 1:
                return {
                    "valid": False,
                    "reason": "Database anchor detects truncation or replacement",
                    "events": len(events),
                }
    return {
        "valid": None if legacy else True,
        "events": len(events),
        "legacy_events": legacy,
        "anchored": anchored,
        "reason": "Legacy events are unverified"
        if legacy
        else "Hash chain intact; protect database/backups against replacement",
    }


def describe(run: dict) -> dict:
    from . import judge_provenance
    from .judge_calibration import alignment_for_run

    rows = [r for c in run.get("cases", []) for r in c["results"]]
    tested = sum(r.get("score") is not None and r["status"] in ("passed", "failed") for r in rows)
    pending = sum(r.get("reason") == "Pending execution." for r in rows)
    missing_reason = sum(
        r["status"] == "not_tested" and not r.get("reason", "").strip() for r in rows
    )
    overrides = sum(bool(r.get("human_review_note")) for r in rows)
    low_agreement = [
        c["id"]
        for c in run.get("cases", [])
        if any(r.get("agreement") is False for r in c["results"])
    ]
    actual = {
        j.get("model"): j.get("provider_model", "revision not supplied")
        for r in rows
        for j in r.get("judges", [])
    }
    from .governance_routes import progress

    mapping = run.get("protocol_snapshot", {}).get("governance_mapping") or json.loads(
        (ROOT / "app/studio/governance.json").read_text(encoding="utf-8")
    )
    return {
        "audit_integrity": verify(run),
        "config_hash": digest(run.get("config", {})),
        "suite_version": run.get("protocol_snapshot", {}).get("protocol_version", "legacy"),
        "run_integrity": {
            "planned": len(rows),
            "scored": tested,
            "pending": pending,
            "not_tested": len(rows) - tested - pending,
            "accounted_for": len(rows) - pending - missing_reason,
            "complete": not pending and not missing_reason,
            "overrides": overrides,
            "low_agreement_cases": low_agreement,
            "agreement_percent": run.get("studio", {}).get("agreement_percent"),
        },
        "bot_cards": [
            {
                "name": b["name"],
                "url": b.get("url"),
                "declared_model": b.get("model") or "Unknown",
                "connection": b.get("kind"),
            }
            for b in run.get("targets", [])
        ],
        "judge_cards": [
            {
                "model": j["model"],
                "endpoint": j["url"],
                "local": j.get("local"),
                "fallback": j.get("fallback"),
                "revision": actual.get(j["model"], "No verdict / revision unavailable"),
            }
            for j in run.get("config", {}).get("judges", [])
        ],
        "warnings": run.get("studio", {}).get("warnings", []),
        # Shared bot/judge model families, kept apart from calibration and model agreement.
        "family_warnings": judge_provenance.family_warnings(run),
        # Who actually scored each Case; unavailable rather than guessed for older records.
        "judge_provenance": judge_provenance.describe(run),
        # Human-label alignment is separate from run_integrity.agreement_percent (model vs model).
        "human_alignment": alignment_for_run(run),
        "mapping": mapping,
        "timings": progress(run),
        "retention_days": run.get("config", {}).get("retention_days", 0),
        "reproduction_note": "Same protocol/config/seed, new run and fresh bot calls. Provider aliases and external bot state can change; credentials must remain available or be re-entered.",
    }


def export_run(run: dict) -> dict:
    integrity = describe(run)
    clean = redact(copy.deepcopy(run))
    clean["governance"] = redact(integrity)
    clean["export_privacy"] = {
        "redacted": True,
        "source_integrity": integrity["audit_integrity"],
        "note": "PII regex baseline (emails/phones/SSNs/key patterns); names and addresses may remain. Audit payloads are redacted, so their original hashes verify only against retained source data.",
        "identifier_exemptions": ID_EXEMPTION_NOTE,
        "limitations": LIMITATION_NOTE,
        "hash_verification": (
            "The hashes inside this redacted export cannot be recomputed from it, because "
            "redaction changed the bytes they were taken over. They remain comparable only "
            "against the retained original record in this Studio, and they are integrity "
            "checks rather than signatures."
        ),
    }
    return clean


def purge_run(ident: str) -> None:
    """Explicit delete/retention removes private evidence and caches together."""
    from .execution_cache import initialize as cache_init

    with db.connect() as conn:
        initialize(conn)
        cache_init(conn)
        conn.execute("DELETE FROM audit_chain WHERE run_id=?", (ident,))
        conn.execute("DELETE FROM execution_cache WHERE run_id=?", (ident,))


def expire_runs(active: set[str]) -> int:
    """Opt-in per-run retention; active runs and saved baselines are protected."""
    from ..config import RUNTIME
    from . import metering

    protected = {b.get("run_id") for b in db.all_records("baseline")}
    removed = 0
    for run in db.all_records("blackbox"):
        days = run.get("config", {}).get("retention_days", 0)
        if not days or run["id"] in active | protected or not run.get("finished_at"):
            continue
        if (
            datetime.now(timezone.utc) - datetime.fromisoformat(run["finished_at"])
        ).total_seconds() < days * 86400:
            continue
        purge_run(run["id"])
        from .judge_calibration import purge_source

        purge_source(run_id=run["id"])
        with db.connect() as conn:
            metering.init_db(conn)
            conn.execute("DELETE FROM usage_events WHERE run_id=?", (run["id"],))
        db.delete("blackbox", run["id"])
        (RUNTIME / "reports" / f"blackbox-{run['id']}.pdf").unlink(missing_ok=True)
        removed += 1
    return removed


def restore_journal(run: dict) -> int:
    """Recover durable events written after the last JSON checkpoint.

    Never call on normal report reads: that would hide tampering/truncation.
    """
    with db.connect() as conn:
        initialize(conn)
        rows = conn.execute(
            "SELECT body FROM audit_chain WHERE run_id=? ORDER BY sequence", (run["id"],)
        ).fetchall()
    if not rows:
        return 0
    journal = [json.loads(row[0]) for row in rows]
    existing = run.get("audit", [])
    start = journal[0]["sequence"]
    for entry in journal:
        seq = entry["sequence"]
        if seq < len(existing) and existing[seq] != entry:
            raise ValueError("Checkpoint differs from durable audit journal")
    added = len(journal) + start - len(existing)
    if added > 0:
        run["audit"] = existing[:start] + journal
    if verify(run)["valid"] is False:
        raise ValueError("Durable audit journal failed verification")
    return max(0, added)
