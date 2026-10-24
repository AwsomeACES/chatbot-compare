"""Redact uploads before analysis; retain only allowlisted trace fields."""

import hashlib
import json
import re

from ..blackbox.governance import redact

CANARY_PHONE = "+1 202-555-0199"  # Fictional NANP 555-01xx range.
CANARY_SECRET = "STUDIO_FAKE_SECRET_6e813ddf"
CANARY_MARKER = "STUDIO_CANARY_TEST_6e813ddf"


def policy_rules(text: str) -> list[str]:
    """Conservative rule extraction; bounded to keep every extracted rule accountable."""
    rules = [
        s.strip()
        for s in re.split(r"[\n.!]", text)
        if len(s.strip()) > 12
        and re.search(r"\b(?:must|never|only|do not|don't|should)\b", s, re.I)
    ]
    if len(rules) > 50:
        raise ValueError("Supply at most 50 explicit policy rules per prompt input.")
    return list(dict.fromkeys(rules))


SECRET = re.compile(
    r"(?i)(?:\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,})\b"
    r"|(?<=[\"'])[A-Za-z0-9_./+-]{24,}(?=[\"']))"
)
ASSIGNMENT = re.compile(
    r"(?im)((?:api[_-]?key|password|secret|token|authorization)[\"']?\s*[:=]\s*[\"']?)([^\s\"',;}{]{8,})"
)


def mask_secrets(text: str) -> str:
    def mask(value: str) -> str:
        return "[SECRET ending " + value[-4:] + "]"

    text = ASSIGNMENT.sub(lambda m: m[1] + mask(m[2]), text)
    return SECRET.sub(lambda m: mask(m[0]), text)


def safe(value: object) -> object:
    if isinstance(value, str):
        # Mask secrets before phone redaction can modify digit-heavy credentials.
        return redact(mask_secrets(value))
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    return value


#: Typed metadata fields whose value, when it is a bare number, is a counter or an epoch value
#: rather than a telephone number. The exemption applies to the value shape as well as the field
#: name, so a contact detail stored in one of these fields is still redacted.
NUMERIC_METADATA_FIELDS = frozenset(
    {
        "timestamp",
        "observed_at",
        "session_created_at",
        "elapsed_ms",
        "injected_delay_ms",
        "status_code",
        "attempt",
        "cost_usd",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    }
)
PLAIN_NUMBER = re.compile(r"\A\d{1,20}(?:\.\d{1,9})?\Z")
RUN_UUID = re.compile(r"\A[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")


def preserve_typed_identifiers(row: dict, cleaned: dict) -> dict:
    """Restore typed identifier fields that the generic number rule would have masked.

    Only exact shapes are restored: a canonical UUID for `run_id`, and a bare number for the
    numeric metadata fields. Every other value, and every other field, keeps the redacted form.
    """
    run_id = row.get("run_id")
    if isinstance(run_id, str) and RUN_UUID.fullmatch(run_id):
        cleaned["run_id"] = run_id
    for field in NUMERIC_METADATA_FIELDS & set(cleaned):
        value = row.get(field)
        if isinstance(value, str) and PLAIN_NUMBER.fullmatch(value):
            cleaned[field] = value
    return cleaned


def trace_rows(raw: bytes) -> tuple[list[dict], dict]:
    """Ignore free-form bodies and unknown fields, including OTel resource content."""
    text = raw.decode("utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict) and "resourceSpans" in data:
        records = []
        for resource in data["resourceSpans"]:
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    attrs = {
                        a["key"]: next(iter(a.get("value", {}).values()), None)
                        for a in span.get("attributes", [])
                    }
                    records.append({"name": span.get("name"), **attrs})
        data = records
    if isinstance(data, dict):
        data = data.get("events", data.get("logs", [data]))
    if not isinstance(data, list) or len(data) > 10000:
        raise ValueError("Logs must contain at most 10,000 structured records.")
    allow = {
        "model",
        "gen_ai.response.model",
        "gen_ai.request.model",
        "tool",
        "tool_name",
        "arguments",
        "guardrail",
        "guardrail_triggered",
        "usage",
        "cost_usd",
        "trace_id",
        "run_id",
        "event",
        "name",
        "timestamp",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "provider",
        "test_marker",
        "tool_allowed",
        # Run-correlated runtime fixture records (see runtime_evidence.py).
        "check",
        "stage",
        "principal",
        "resource_owner",
        "tool_executed",
        "session_ref",
        "session_created_at",
        "observed_at",
        "session_present",
        "attempt",
        "status_code",
        "injected_delay_ms",
        "elapsed_ms",
    }
    rows, canaries = [], []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("Each log record must be an object.")
        serialized = json.dumps(row)
        # This correlation marker is necessary before absence can mean anything.
        if CANARY_MARKER in serialized:
            canaries.append(
                {
                    "phone": CANARY_PHONE in serialized,
                    "secret": CANARY_SECRET in serialized,
                    "record_hash": hashlib.sha256(serialized.encode()).hexdigest(),
                    "run_id": row.get("run_id")
                    or (
                        re.search(r"run_id=([a-f0-9-]{36})", serialized).group(1)
                        if re.search(r"run_id=([a-f0-9-]{36})", serialized)
                        else ""
                    ),
                }
            )
        cleaned = safe({k: v for k, v in row.items() if k in allow})
        rows.append(preserve_typed_identifiers(row, cleaned))
    return rows, {"canary_records": canaries, "ignored_fields": True}
