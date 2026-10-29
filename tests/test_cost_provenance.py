"""Provider-specific prices and safe export of numeric cost fields (ST-06, export redaction).

Two defects from the saved VoltKart retest are covered here.

The export wrote 477 cost values as "[REDACTED phone]", and others as "7217.[REDACTED phone]",
because an exact micro-USD amount is stored as a decimal string and the generic redaction rule
masks any run of 10 to 15 digits. The integer micro-USD fields survived, so precision was lost
rather than the headline totals.

The price lookup keyed on model name alone, so one provider's published rate would be applied to
any host serving a model of that name. Google's Gemini Developer API lists Gemma 4 as free of
charge on its free tier and "not available" on the paid tier (checked 29 October 2026), which
says nothing about what a third-party host charges for the same weights.
"""

import json
import re

import pytest

from app.blackbox import governance, pricing

PHONE = "+1 202-555-0199"  # Fictional NANP 555-01xx range.

#: Every exact-amount shape found in the saved export, including the exponent form `Decimal`
#: produces for very small values.
SAVED_AMOUNTS = [
    "133316.000000000000",
    "7217.000000000000",
    "10685.400000000000",
    "0E-12",
    "0",
    "0E-11",
]


# --- the numeric fields survive redaction -----------------------------------------------------


@pytest.mark.parametrize("amount", SAVED_AMOUNTS, ids=SAVED_AMOUNTS)
def test_an_exact_cost_amount_survives_redaction(amount):
    assert governance.redact({"exact_micro_usd": amount}) == {"exact_micro_usd": amount}


def test_the_saved_cost_block_shape_survives_redaction():
    """The real nesting: role totals, breakdown lists and per-event rows."""
    costs = {
        "bot": {"exact_micro_usd": "133316.000000000000", "known_cost_micro_usd": 133316},
        "evaluation": {"exact_micro_usd": "7217.000000000000"},
        "breakdowns": {"category": [{"exact_micro_usd": "10685.400000000000"}]},
        "events": [{"cost_exact_micro_usd": "0E-12"}],
        "retries": {"exact_micro_usd": "0E-11"},
    }
    cleaned = governance.redact(json.loads(json.dumps(costs)))
    assert "REDACTED" not in json.dumps(cleaned)
    assert cleaned == costs


@pytest.mark.parametrize("field", sorted(governance.NUMERIC_COST_FIELDS))
def test_every_exempt_field_keeps_a_bare_amount(field):
    assert governance.redact({field: "1234567890123"}) == {field: "1234567890123"}


# --- the exemption is not a bypass -------------------------------------------------------------


@pytest.mark.parametrize("field", sorted(governance.NUMERIC_COST_FIELDS))
def test_a_telephone_number_in_a_cost_field_is_still_redacted(field):
    """The exemption checks the value shape, not only the field name."""
    cleaned = governance.redact({field: PHONE})
    assert PHONE not in cleaned[field]
    assert "[REDACTED phone]" in cleaned[field]


def test_a_cost_field_holding_free_text_is_not_exempt():
    cleaned = governance.redact({"exact_micro_usd": f"billed to {PHONE}"})
    assert PHONE not in cleaned["exact_micro_usd"]


def test_an_amount_shaped_value_in_another_field_is_still_redacted():
    """Only the known cost fields are exempt; a bare number elsewhere keeps the old treatment."""
    cleaned = governance.redact({"note": "133316.000000000000"})
    assert "REDACTED" in cleaned["note"]


@pytest.mark.parametrize(
    "value",
    ["+1 2025550199", "1 (202) 555-0199", "202-555-0199", "202 555 0199", "0x1234567890123"],
)
def test_a_value_with_separators_is_not_treated_as_an_amount(value):
    """An amount has no spaces, brackets, dashes or country code."""
    assert not governance.PLAIN_AMOUNT.fullmatch(value)


def test_a_similarly_named_field_is_not_exempt():
    """The allowlist is exact; a near-miss name does not inherit the exemption."""
    for field in ("phone_micro_usd_note", "micro_usd", "exact_micro_usdx"):
        assert "REDACTED" in governance.redact({field: "2025550199000"})[field]


def test_the_exempt_fields_cover_every_amount_the_cost_summary_produces():
    """A new monetary field must be classified deliberately, or an export would mangle it."""
    import inspect

    from app.blackbox import cost_summary

    source = inspect.getsource(cost_summary)
    produced = set(re.findall(r'"([a-z_]*micro_usd)"', source))
    assert produced, "no monetary field names were found to check"
    assert produced <= governance.NUMERIC_COST_FIELDS, (
        f"unclassified monetary fields: {sorted(produced - governance.NUMERIC_COST_FIELDS)}"
    )


def test_the_export_discloses_the_numeric_exemption():
    run = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "status": "completed",
        "config": {"judges": []},
        "targets": [],
        "categories": [],
        "cases": [],
        "studio": {"warnings": [], "family_warnings": []},
        "progress": 100,
        "stage": "Complete",
        "audit": [],
        "costs": {"bot": {"exact_micro_usd": "133316.000000000000"}},
    }
    exported = governance.export_run(run)
    assert exported["costs"]["bot"]["exact_micro_usd"] == "133316.000000000000"
    note = exported["export_privacy"]["numeric_field_exemptions"]
    assert "exact decimal value" in note
    assert "is still redacted" in note


# --- provider and endpoint specific prices ------------------------------------------------------


def snapshot(models):
    return {"models": models, "source": "fixture", "date": "2026-10-29T00:00:00Z", "id": "x" * 24}


GOOGLE_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
THIRD_PARTY_ENDPOINT = "https://api.example-host.test/v1/chat/completions"
GEMMA = "gemma-4-26b-a4b-it"

#: What a verified Google entry looks like: free on its own endpoint, with a source and a date.
GOOGLE_FREE_GEMMA = {
    "input": "0",
    "output": "0",
    "reasoning": "0",
    "provider": "gemini",
    "source": "https://ai.google.dev/gemini-api/docs/pricing",
    "source_date": "2026-10-29",
    "note": "Free tier of the Gemini Developer API. The paid tier lists Gemma 4 as not available.",
}


def test_a_googles_free_rate_is_not_applied_to_another_host():
    """ST-06: one provider publishing a free tier says nothing about another's bill."""
    snap = snapshot({GEMMA: GOOGLE_FREE_GEMMA})
    rates, _ = pricing.price_for(
        snap, GEMMA, provider="openai-compatible", endpoint=THIRD_PARTY_ENDPOINT
    )
    assert rates is None, "a third-party endpoint must not inherit Google's rate"
    value, status = pricing.calculate({"input_tokens": 1000}, rates)
    assert value is None and status == "unknown", "an unresolved price stays Unknown, never $0"


def test_the_same_rate_is_applied_on_the_providers_own_endpoint():
    snap = snapshot({GEMMA: GOOGLE_FREE_GEMMA})
    rates, resolved = pricing.price_for(snap, GEMMA, provider="gemini", endpoint=GOOGLE_ENDPOINT)
    assert rates is GOOGLE_FREE_GEMMA
    assert resolved == GEMMA
    value, status = pricing.calculate({"input_tokens": 1000}, rates)
    assert status == "priced" and value == 0, "a published free rate is a known zero"


def test_a_price_keyed_to_an_exact_endpoint_wins():
    paid = {"input": "5", "output": "10", "provider": "openai-compatible"}
    snap = snapshot(
        {
            GEMMA: GOOGLE_FREE_GEMMA,
            f"{GEMMA}@{pricing.endpoint_identity(THIRD_PARTY_ENDPOINT)}": paid,
        }
    )
    rates, resolved = pricing.price_for(
        snap, GEMMA, provider="openai-compatible", endpoint=THIRD_PARTY_ENDPOINT
    )
    assert rates is paid
    assert resolved.endswith("api.example-host.test/v1/chat/completions")


def test_a_provider_qualified_price_is_used_before_the_plain_entry():
    paid = {"input": "5", "output": "10"}
    snap = snapshot({GEMMA: GOOGLE_FREE_GEMMA, f"gemini/{GEMMA}": paid})
    rates, resolved = pricing.price_for(snap, GEMMA, provider="gemini", endpoint=GOOGLE_ENDPOINT)
    assert rates is paid and resolved == f"gemini/{GEMMA}"


def test_an_owner_override_applies_to_their_own_endpoint():
    """An owner must be able to price their own third-party host."""
    override = {"input": "5", "output": "10", "provider": "gemini", "override": True}
    snap = snapshot({GEMMA: override})
    rates, _ = pricing.price_for(
        snap, GEMMA, provider="openai-compatible", endpoint=THIRD_PARTY_ENDPOINT
    )
    assert rates is override, "an explicit owner decision is not second-guessed"


def test_a_catalogue_entry_without_a_provider_still_applies():
    """Most catalogue rows name no provider; withholding them all would hide known costs."""
    rates = {"input": "1", "output": "2", "provider": "unknown"}
    assert pricing.price_for(snapshot({"m": rates}), "m", provider="openai-compatible")[0] is rates
    plain = {"input": "1", "output": "2"}
    assert pricing.price_for(snapshot({"m": plain}), "m", provider="openai-compatible")[0] is plain


def test_a_cross_provider_name_collision_is_withheld():
    openai_rate = {"input": "2.5", "output": "10", "provider": "openai"}
    snap = snapshot({"gpt-fixture": openai_rate})
    assert pricing.price_for(snap, "gpt-fixture", provider="anthropic")[0] is None
    assert pricing.price_for(snap, "gpt-fixture", provider="openai")[0] is openai_rate


def test_an_azure_hosted_openai_model_is_treated_as_the_same_account_family():
    rates = {"input": "2.5", "output": "10", "provider": "azure"}
    assert pricing.price_for(snapshot({"m": rates}), "m", provider="openai")[0] is rates


def test_an_unknown_model_is_unknown_not_free():
    rates, resolved = pricing.price_for(snapshot({}), "never-priced", provider="gemini")
    assert rates is None and resolved == "never-priced"
    assert pricing.calculate({"input_tokens": 10}, rates) == (None, "unknown")


def test_an_endpoint_identity_excludes_credentials_and_query():
    identity = pricing.endpoint_identity("https://user:secret@Host.Test:8443/v1/chat?key=abc#frag")
    assert identity == "https://host.test:8443/v1/chat"
    assert "secret" not in identity and "abc" not in identity


def test_an_unparseable_endpoint_yields_no_identity():
    assert pricing.endpoint_identity("") == ""
    assert pricing.endpoint_identity("not a url") == ""


# --- price provenance ---------------------------------------------------------------------------


def test_an_override_records_its_source_and_date(monkeypatch):
    from app import database as db

    original = pricing.settings()
    try:
        saved = pricing.save_settings(
            {
                "overrides": {
                    GEMMA: {
                        "input": "0",
                        "output": "0",
                        "source": "https://ai.google.dev/gemini-api/docs/pricing",
                        "source_date": "2026-10-29",
                        "provider": "gemini",
                    }
                }
            }
        )
        entry = saved["overrides"][GEMMA]
        assert entry["input"] == "0"
        assert entry["source_date"] == "2026-10-29"
        assert entry["provider"] == "gemini"
    finally:
        db.save("cost_settings", original)


def test_an_override_rejects_an_unsupported_field():
    with pytest.raises(ValueError, match="Invalid price override"):
        pricing.save_settings({"overrides": {GEMMA: {"input": "0", "discount": "50%"}}})


def test_override_metadata_must_be_short_text():
    with pytest.raises(ValueError, match="at most 500 characters"):
        pricing.save_settings({"overrides": {GEMMA: {"input": "0", "source": "x" * 501}}})


def test_a_historical_snapshot_is_not_rewritten_by_a_new_override():
    """Old runs keep their own snapshot; reconciliation is never silent."""
    old = pricing.store_snapshot({GEMMA: {"input": "9", "output": "9"}}, activate=False)
    reread = pricing.snapshot(old["id"])
    assert reread["models"][GEMMA]["input"] == "9"
    assert reread["id"] == old["id"]
    assert reread["date"] == old["date"]


# --- the verified price file ---------------------------------------------------------------------


def test_the_verified_gemma_entry_is_bound_to_googles_own_endpoint():
    """ST-06: the checked free rate must be unusable on any other host."""
    entries = pricing.verified_prices()
    keys = [key for key in entries if key.startswith(GEMMA)]
    assert keys, "no verified Gemma entry is present"
    for key in keys:
        assert "@" in key, "a verified Gemma rate must be endpoint-bound, not model-wide"
        model, identity = key.split("@", 1)
        assert identity == pricing.endpoint_identity(identity)
        assert "generativelanguage.googleapis.com" in identity


def test_every_verified_entry_records_a_source_and_a_date():
    for key, rates in pricing.verified_prices().items():
        assert rates.get("source", "").startswith("http"), f"{key} has no source URL"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rates.get("source_date", "")), key
        assert rates.get("provider"), f"{key} does not name the provider it was checked against"


def test_every_verified_rate_is_a_valid_number():
    for key, rates in pricing.verified_prices().items():
        for field in set(rates) & set(pricing.RATE_KEYS):
            assert pricing.decimal(rates[field]) >= 0, f"{key}.{field}"


def test_a_verified_entry_is_merged_below_an_owner_override():
    """An owner's own decision about their endpoint wins over a hand-checked default."""
    from app import database as db
    from app.blackbox.schema import Settings, Target

    original = pricing.settings()
    try:
        key = next(iter(pricing.verified_prices()))
        pricing.save_settings({"overrides": {key: {"input": "7", "output": "7"}}})
        config = Settings(targets=[Target(url="http://localhost:8765")])
        pinned = pricing.pin(config)
        assert pinned["models"][key]["input"] == "7"
        assert pinned["models"][key]["override"] is True
        assert "verified prices" in pinned["source"] and "saved overrides" in pinned["source"]
    finally:
        db.save("cost_settings", original)


def test_pinning_does_not_alter_the_active_catalogue_snapshot():
    """Merging verified prices must not rewrite the stored source snapshot."""
    from app.blackbox.schema import Settings, Target

    before = pricing.snapshot()
    pricing.pin(Settings(targets=[Target(url="http://localhost:8765")]))
    after = pricing.snapshot()
    assert after["id"] == before["id"]
    assert after["models"] == before["models"]
