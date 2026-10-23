"""Source findings distinguish scanner candidates from verified evidence."""

from copy import deepcopy

import pytest

from app.assurance.white import parse


def output(data):
    return {
        "data": data,
        "version": "fixture-1",
        "image_id": "sha256:fixture",
        "ruleset": "fixture-1",
        "database_snapshot": {"scope_sha256": "fixture"},
    }


def secret_finding(tmp_path, code, rule="generic-api-key"):
    (tmp_path / "provider.py").write_text(code, encoding="utf-8")
    return parse(
        "hardcoded_secrets",
        output([{"File": "/source/provider.py", "StartLine": 1, "RuleID": rule}]),
        tmp_path,
        0,
    )


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-8",
        "claude-haiku-4-7",
        "mistral-small-latest",
        "claude-sonnet-4.6",
    ],
)
def test_model_name_match_is_reviewable_not_a_confirmed_key(tmp_path, model):
    result = secret_finding(tmp_path, f'    api_model = "{model}"')
    assert result.verdict == "not_tested"
    assert result.score is None
    assert result.review
    assert "not confirmed exposed keys" in result.explanation
    assert result.details["raw_finding_count"] == 1
    assert result.details["model_context_matches"] == 1
    assert result.details["potential_credentials"] == 0
    assert result.details["raw_findings"][0]["rule_id"] == "generic-api-key"
    assert result.evidence[0].file == "provider.py"
    assert result.evidence[0].line == 1


@pytest.mark.parametrize(
    "secret",
    [
        "sk-" + "syntheticOnly" * 3 + "1234",
        "AIza" + "syntheticOnly" * 3 + "1234",
        "AQ." + "syntheticOnly" * 3 + "1234",
        "UnfamiliarCredentialFixture12345678",
    ],
)
def test_real_credential_shapes_still_alert_even_in_model_field(tmp_path, secret):
    result = secret_finding(tmp_path, f'api_model = "{secret}"')
    assert result.verdict == "fail"
    assert result.severity == "Critical"
    assert secret not in result.model_dump_json()
    assert result.details["potential_credentials"] == 1


def test_provider_specific_secret_rule_is_never_qualified_by_model_context(tmp_path):
    result = secret_finding(tmp_path, 'api_model = "fixture-model-123"', "openai-api-key")
    assert result.verdict == "fail"


def test_second_assignment_on_model_line_does_not_hide_a_key(tmp_path):
    result = secret_finding(
        tmp_path, 'api_model = "fixture-model-1"; api_key = "CredentialFixture12345678"'
    )
    assert result.verdict == "fail"


def test_credential_variable_is_not_reclassified_as_a_model(tmp_path):
    result = secret_finding(tmp_path, 'api_key = "fixture-model-123"')
    assert result.verdict == "fail"


def test_scanner_metadata_is_retained_but_secret_fields_are_never_stored(tmp_path):
    secret = "UnfamiliarCredentialFixture12345678"
    (tmp_path / "provider.py").write_text(f'api_key = "{secret}"', encoding="utf-8")
    report = output(
        [
            {
                "File": "/source/provider.py",
                "StartLine": 1,
                "EndLine": 1,
                "StartColumn": 12,
                "EndColumn": 46,
                "RuleID": "generic-api-key",
                "Description": "Generic API Key",
                "Fingerprint": "provider.py:generic-api-key:1",
                "Secret": secret,
                "Match": f'api_key = "{secret}"',
            }
        ]
    )
    original = deepcopy(report)
    result = parse("hardcoded_secrets", report, tmp_path, 0)
    assert report == original
    assert secret not in result.model_dump_json()
    retained = result.details["raw_findings"][0]
    assert retained["scanner_metadata"]["Fingerprint"] == "provider.py:generic-api-key:1"
    assert retained["scanner_metadata"]["EndColumn"] == 46
    assert retained["secret"] == retained["match"] == "[REDACTED]"


def test_source_expressions_are_not_executed(tmp_path):
    marker = tmp_path / "must-not-exist"
    result = secret_finding(
        tmp_path, f"api_model = __import__('pathlib').Path({str(marker)!r}).touch()"
    )
    assert not marker.exists()
    assert result.verdict == "fail"


def test_mixed_model_and_key_matches_keep_secret_failure_and_both_originals(tmp_path):
    secret = "sk-" + "fixtureOnly" * 4
    (tmp_path / "provider.py").write_text(
        f'api_model = "fixture-model-123"\napi_key = "{secret}"\n', encoding="utf-8"
    )
    report = output(
        [
            {"File": "/source/provider.py", "StartLine": line, "RuleID": "generic-api-key"}
            for line in (1, 2)
        ]
    )
    original = deepcopy(report)
    result = parse("hardcoded_secrets", report, tmp_path, 0)
    assert report == original
    assert result.verdict == "fail"
    assert result.details["raw_finding_count"] == 2
    assert result.details["potential_credentials"] == 1
    assert len(result.evidence) == 2
    assert secret not in result.model_dump_json()


def dependency(name="fixture", version="1.2.3", vulnerable=True):
    return {
        "package": {"name": name, "version": version, "ecosystem": "PyPI"},
        "vulnerabilities": [{"id": "GHSA-fixture"}] if vulnerable else [],
    }


def dependency_finding(tmp_path, *packages):
    return parse(
        "dependency_vulnerabilities",
        output(
            {
                "results": [
                    {
                        "source": {"path": "/source/requirements.txt", "type": "lockfile"},
                        "packages": list(packages),
                    }
                ]
            }
        ),
        tmp_path,
        0,
    )


@pytest.mark.parametrize(
    "version",
    ["0.0.0", "v0.0.0", "0.0.0+unknown", "", None, "unknown", ">=1.0", "*", "1.x", "1.2.X"],
)
def test_unresolved_version_candidates_are_not_installed_vulnerabilities(tmp_path, version):
    result = dependency_finding(tmp_path, dependency(version=version))
    assert result.verdict == "not_tested"
    assert result.score is None
    assert "not confirmed installed vulnerabilities" in result.explanation
    assert "lockfile" in result.fix
    assert result.details["raw_finding_count"] == 1
    assert result.details["raw_findings"][0]["id"] == "GHSA-fixture"
    assert result.details["raw_findings"][0]["package"]["version"] == version
    assert result.details["raw_findings"][0]["version_status"] == "unresolved"
    assert not result.details["installed_versions_verified"]
    assert result.details["database_snapshot"] == {"scope_sha256": "fixture"}
    assert result.evidence


def test_unresolved_package_without_advisories_cannot_be_a_pass(tmp_path):
    result = dependency_finding(tmp_path, dependency(version="0.0.0", vulnerable=False))
    assert result.verdict == "not_tested"
    assert result.details["raw_finding_count"] == 0
    assert len(result.details["unresolved_packages"]) == 1


def test_reported_exact_vulnerable_version_still_flags(tmp_path):
    result = dependency_finding(tmp_path, dependency())
    assert result.verdict == "fail"
    assert result.details["exact_version_advisories"] == 1
    assert "scanner-reported exact" in result.explanation
    assert "does not verify" in result.explanation


def test_reported_exact_unaffected_version_passes_only_the_scanner_scope(tmp_path):
    result = dependency_finding(tmp_path, dependency(vulnerable=False))
    assert result.verdict == "pass"
    assert "other risks may remain" in result.explanation
    assert not result.details["installed_versions_verified"]


def test_mixed_version_evidence_keeps_exact_failure_and_unresolved_candidates(tmp_path):
    result = dependency_finding(
        tmp_path, dependency("locked"), dependency("unresolved", version="0.0.0")
    )
    assert result.verdict == "fail"
    assert result.review
    assert result.details["raw_finding_count"] == 2
    assert result.details["exact_version_advisories"] == 1
    assert len(result.details["unresolved_packages"]) == 1
    assert "not confirmed installed vulnerabilities" in result.explanation


def test_empty_package_inventory_is_not_a_successful_dependency_scan(tmp_path):
    assert dependency_finding(tmp_path).verdict == "not_tested"


def test_out_of_bounds_secret_line_is_rejected(tmp_path):
    (tmp_path / "provider.py").write_text("# fixture\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid source line"):
        parse(
            "hardcoded_secrets",
            output([{"File": "/source/provider.py", "StartLine": 100}]),
            tmp_path,
            0,
        )


@pytest.mark.parametrize(
    "line",
    [
        '    "opus": {"label": "Claude Opus 5", "provider": "anthropic", "api_model": "claude-opus-5",',
        '                        "api_model": "gemini-2.5-flash-lite", "tier": "Pro"},',
    ],
)
def test_model_name_in_mapping_entry_is_reviewable_not_a_confirmed_key(tmp_path, line):
    result = secret_finding(tmp_path, line)
    assert result.verdict == "not_tested" and result.review
    assert result.details["model_context_matches"] == 1


@pytest.mark.parametrize(
    "line",
    [
        '"x": {"api_model": "claude-opus-5", "api_key": "Cred12345678abcd"},',
        '"api_model": "claude-opus-5", "note": "sk-abcdefghijkl"',
        '"api_model": "claude-opus-5", "x": "Q8fj2KsLm09xYzPq"',
        '"api_model": "claude-opus-5"}; key = "Cred12345678"',
        '"api_key": "claude-opus-5",',
    ],
)
def test_mapping_entry_with_other_opaque_values_keeps_the_alert(tmp_path, line):
    assert secret_finding(tmp_path, line).verdict == "fail"
