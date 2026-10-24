"""Context-aware export redaction (T-024) and export parity (T-020).

The exemption for public structured identifiers must stay an exemption. Most of this file is
deliberately negative: it proves that putting a credential, an email address, a telephone number
or a national identifier next to — or inside a field named for — a public identifier does not get
it past redaction.
"""

import json

import pytest

from app.assurance import privacy
from app.blackbox import governance

PHONE = "+1 202-555-0199"  # Fictional NANP 555-01xx range.
EMAIL = "someone@example.com"
SSN = "123-45-6789"
KEY = "sk-aaaaaaaaaaaaaaaaaaaaaaaa"

PRESERVED = [
    ("UUID", "550e8400-e29b-41d4-a716-446655440000"),
    ("uppercase UUID", "550E8400-E29B-41D4-A716-446655440000"),
    ("CVE with seven digits", "CVE-2024-1234567"),
    ("CVE with four digits", "CVE-2021-4034"),
    ("GitHub advisory", "GHSA-abcd-efgh-ijkl"),
    ("OSV advisory", "OSV-2024-1234"),
    ("Python advisory", "PYSEC-2024-48"),
    ("Ubuntu advisory", "USN-2024-1"),
    ("weakness class", "CWE-1234"),
    ("ISO instant", "2026-10-23T20:15:30Z"),
    ("ISO instant with offset", "2026-10-23T20:15:30.123456+05:30"),
]


# --- the exemption works ---------------------------------------------------------------------


@pytest.mark.parametrize("label,identifier", PRESERVED, ids=[p[0] for p in PRESERVED])
def test_public_identifiers_survive_redaction(label, identifier):
    text = f"Finding references {identifier} in the dependency report."
    assert governance.redact(text) == text, f"{label} was masked"


def test_a_long_advisory_number_is_not_treated_as_a_telephone_number():
    """The generic rule matches any 10-15 digit run, which is why the exemption exists."""
    digits = "CVE-2024-1234567"
    assert "REDACTED" not in governance.redact(digits)
    # Proof the generic rule really would have caught it without the exemption.
    assert "REDACTED phone" in governance.redact("reference 2024 1234567 890")


def test_identifiers_survive_inside_nested_structures():
    payload = {
        "findings": [{"id": "CVE-2024-1234567", "seen_at": "2026-10-23T20:15:30Z"}],
        "run": "550e8400-e29b-41d4-a716-446655440000",
    }
    assert governance.redact(payload) == payload


# --- the exemption is not a bypass -----------------------------------------------------------


@pytest.mark.parametrize(
    "secret,marker",
    [(PHONE, "phone"), (EMAIL, "email"), (SSN, "ssn"), (KEY, "credential")],
)
def test_sensitive_values_beside_an_identifier_are_still_redacted(secret, marker):
    text = f"CVE-2024-1234567 reported by {secret} on 2026-10-23T20:15:30Z"
    cleaned = governance.redact(text)
    assert secret not in cleaned
    assert f"[REDACTED {marker}]" in cleaned
    assert "CVE-2024-1234567" in cleaned, "the identifier should still be readable"
    assert "2026-10-23T20:15:30Z" in cleaned


def test_a_telephone_number_between_two_identifiers_is_redacted():
    text = f"CVE-2024-1234567 {PHONE} GHSA-abcd-efgh-ijkl"
    cleaned = governance.redact(text)
    assert PHONE not in cleaned
    assert cleaned.startswith("CVE-2024-1234567")
    assert cleaned.endswith("GHSA-abcd-efgh-ijkl")


def test_an_identifier_prefix_does_not_exempt_a_following_contact_detail():
    """A near-miss shape must not open a hole: only exact identifier tokens are exempt."""
    for text in (
        f"CVE-{PHONE}",
        f"GHSA-{PHONE}",
        f"CWE-{PHONE}",
        f"OSV-{PHONE}",
        f"not-a-uuid-{PHONE}",
    ):
        assert PHONE not in governance.redact(text), f"{text!r} leaked a telephone number"


def test_malformed_identifier_shapes_are_not_exempt():
    """Shapes that only resemble an identifier get the ordinary treatment."""
    assert "REDACTED" in governance.redact("CVE-24-1234567890123")
    assert "REDACTED" in governance.redact("GHSA-2024-5551234567")
    assert "REDACTED" in governance.redact("not-a-uuid 5505 5512 3456 78")


def test_every_redaction_rule_is_classified_as_specific_or_generic():
    """A new rule must be placed deliberately, or the exemption could silently cover it."""
    classified = set(governance.SPECIFIC_RULES) | set(governance.GENERIC_RULES)
    assert classified == set(governance.PII_PATTERNS)
    assert set(governance.GENERIC_RULES) == {"phone"}, (
        "only the generic number rule may skip identifier tokens"
    )


def test_an_email_address_containing_an_identifier_is_still_redacted():
    text = "contact cve-2024-1234567@example.com for details"
    cleaned = governance.redact(text)
    assert "@example.com" not in cleaned
    assert "[REDACTED email]" in cleaned


# --- field-scoped numeric metadata ------------------------------------------------------------


def rows(records):
    return privacy.trace_rows(json.dumps(records).encode())[0]


def test_a_numeric_metadata_field_keeps_a_bare_number():
    [row] = rows([{"event": "call", "timestamp": "1761250530123", "elapsed_ms": "12345678901"}])
    assert row["timestamp"] == "1761250530123"
    assert row["elapsed_ms"] == "12345678901"


def test_a_numeric_metadata_field_does_not_exempt_a_telephone_number():
    """The exemption checks the value shape, not only the field name."""
    [row] = rows([{"event": "call", "timestamp": PHONE, "observed_at": f"called {PHONE}"}])
    assert PHONE not in json.dumps(row)
    assert "[REDACTED phone]" in row["timestamp"]


def test_a_free_text_field_is_never_exempt():
    [row] = rows([{"event": f"support call to {PHONE} from {EMAIL}", "timestamp": "1"}])
    assert PHONE not in row["event"]
    assert EMAIL not in row["event"]


def test_a_credential_in_a_metadata_field_is_still_masked():
    [row] = rows([{"event": "call", "trace_id": KEY, "model": f"gpt-fixture {KEY}"}])
    serialized = json.dumps(row)
    assert KEY not in serialized
    assert "SECRET ending" in serialized or "REDACTED" in serialized


def test_the_canonical_run_id_is_preserved_but_other_run_id_text_is_not():
    uuid_value = "550e8400-e29b-41d4-a716-446655440000"
    [good] = rows([{"event": "call", "run_id": uuid_value}])
    assert good["run_id"] == uuid_value
    [bad] = rows([{"event": "call", "run_id": f"run for {PHONE}"}])
    assert PHONE not in bad["run_id"]


# --- export disclosure ------------------------------------------------------------------------


def saved_run():
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "status": "completed",
        "config": {"judges": [{"model": "gpt-fixture", "url": "https://api.openai.com/v1"}]},
        "targets": [{"name": "bot", "url": "http://localhost:8800", "kind": "rest"}],
        "categories": ["functional"],
        "cases": [
            {
                "id": "c1",
                "category": "functional",
                "results": [
                    {
                        "status": "passed",
                        "score": 90,
                        "reason": f"Reported by {EMAIL} about CVE-2024-1234567",
                        "transcript": [{"input": "hi", "output": "ok", "seconds": 0.1}],
                    }
                ],
            }
        ],
        "studio": {"warnings": [], "family_warnings": []},
        "progress": 100,
        "stage": "Complete",
        "audit": [],
    }


def test_export_states_the_identifier_exemption_and_its_limits():
    exported = governance.export_run(saved_run())
    privacy_block = exported["export_privacy"]
    assert privacy_block["redacted"] is True
    assert "UUIDs" in privacy_block["identifier_exemptions"]
    assert "not an adversarial filter" in privacy_block["identifier_exemptions"]
    assert "Names, postal addresses" in privacy_block["limitations"]


def test_export_does_not_claim_its_hashes_are_independently_verifiable():
    privacy_block = governance.export_run(saved_run())["export_privacy"]
    note = privacy_block["hash_verification"]
    assert "cannot be recomputed from it" in note
    assert "integrity checks rather than signatures" in note
    assert "verify only against retained source data" in privacy_block["note"]


def test_export_redacts_contact_details_while_keeping_the_finding_readable():
    exported = governance.export_run(saved_run())
    reason = exported["cases"][0]["results"][0]["reason"]
    assert EMAIL not in reason
    assert "[REDACTED email]" in reason
    assert "CVE-2024-1234567" in reason, "the advisory reference must stay readable"
    assert exported["cases"][0]["results"][0]["score"] == 90, "the original Finding is preserved"
    assert exported["cases"][0]["results"][0]["transcript"][0]["output"] == "ok"
