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
        rows.append(safe({k: v for k, v in row.items() if k in allow}))
    return rows, {"canary_records": canaries, "ignored_fields": True}
