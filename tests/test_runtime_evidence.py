"""Runtime checks on controlled fixtures. These validate Studio, not any real target bot."""

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.assurance import intake, readiness, service
from app.assurance.gray import CHECKS, GrayEngine, runtime_expectations
from app.assurance.privacy import trace_rows
from app.assurance.runtime_evidence import RUNTIME_CHECKS, correlated, evaluate
from app.blackbox import governance
from app.blackbox.schema import JudgeSelection, Settings, Target

# Digit-heavy UUIDs expose phone-redaction collisions deterministically.
RUN = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def rows(records: list[dict]) -> list[dict]:
    """Pass fixture output through the same allowlist/redaction path as uploads."""
    return trace_rows(json.dumps(records).encode())[0]


@pytest.mark.parametrize("run_id", [RUN, "abcdefab-cdef-4abc-8def-abcdefabcdef"])
def test_log_intake_preserves_run_correlation_without_preserving_private_text(run_id):
    record = {
        "run_id": run_id,
        "model": "fixture-model",
        "arguments": {"email": "person@example.com", "phone": "+1 202-555-0199"},
    }
    stored = intake.store("logs", json.dumps([record]).encode(), "trace.json")
    restored, _ = intake.load(stored["id"], "logs")
    assert restored[0]["run_id"] == run_id
    serialized = json.dumps(restored)
    assert "person@example.com" not in serialized
    assert "+1 202-555-0199" not in serialized
    finding = evaluate("runtime_model", restored, run_id, 0, {"expected_model": "fixture-model"})
    assert finding.verdict == "pass"
    assert evaluate("runtime_model", restored, OTHER, 0).verdict == "not_tested"


@pytest.mark.parametrize("value", ["person@example.com", "+1 202-555-0199", "sk-" + "x" * 32])
def test_run_id_field_does_not_bypass_redaction_for_non_uuid_values(value):
    assert value not in json.dumps(rows([{"run_id": value}]))


class OrderTool:
    """Isolated fixture tool. ``check_owner=False`` simulates a broken authorization path."""

    def __init__(self, check_owner: bool):
        self.check_owner = check_owner
        self.orders = {"order-a": "synthetic-user-a", "order-b": "synthetic-user-b"}

    def call(self, principal: str, order: str) -> dict:
        owner = self.orders[order]
        executed = not self.check_owner or owner == principal
        return {
            "run_id": RUN,
            "check": "tool_permissions",
            "tool": "lookup_order",
            "principal": principal,
            "resource_owner": owner,
            "tool_executed": executed,
        }


@pytest.mark.parametrize(("check_owner", "expected"), [(True, "pass"), (False, "fail")])
def test_tool_permissions_fixture_uses_execution_records_not_bot_wording(check_owner, expected):
    tool = OrderTool(check_owner)
    records = [tool.call("synthetic-user-a", "order-a"), tool.call("synthetic-user-a", "order-b")]
    # A reassuring reply is ignored: only tool_executed is evidence.
    records.append({"run_id": RUN, "check": "tool_permissions", "event": "I cannot do that."})
    finding = evaluate("runtime_tool_permissions", rows(records), RUN, 0)
    assert finding.verdict == expected
    assert finding.score == (100.0 if expected == "pass" else 0.0)
    only_denied = evaluate("runtime_tool_permissions", rows(records[1:2]), RUN, 0)
    assert only_denied.verdict == "not_tested" if check_owner else only_denied.verdict == "fail"


def test_stale_and_unrelated_records_never_score():
    tool = OrderTool(True)
    records = [{**tool.call("synthetic-user-a", "order-b"), "run_id": OTHER}]
    records.append(
        {k: v for k, v in tool.call("synthetic-user-a", "order-a").items() if k != "run_id"}
    )
    finding = evaluate("runtime_tool_permissions", rows(records), RUN, 0)
    assert finding.verdict == "not_tested" and finding.score is None
    assert finding.details["excluded_other_run"] == 1
    assert finding.details["excluded_without_run_id"] == 1
    assert finding.details["outcome"] == "missing_input"
    kept, counts = correlated(rows(records), RUN, None)
    assert kept == [] and counts["records_used"] == 0


class SessionStore:
    """Fixture store with an injectable clock; ttl=None simulates no expiry."""

    def __init__(self, ttl: float | None):
        self.ttl, self.items = ttl, {}

    def create(self, ref: str, now: float) -> None:
        self.items[ref] = now

    def observe(self, ref: str, now: float) -> dict:
        created = self.items[ref]
        present = self.ttl is None or now - created < self.ttl
        return {
            "run_id": RUN,
            "check": "retention",
            "session_ref": ref,
            "session_created_at": created,
            "observed_at": now,
            "session_present": present,
        }


@pytest.mark.parametrize(("ttl", "expected"), [(600, "pass"), (None, "fail")])
def test_retention_fixture_needs_before_and_after_observations(ttl, expected):
    store = SessionStore(ttl)
    start = 1_790_000_000.0
    store.create("synthetic-session-1", start)
    records = [
        store.observe("synthetic-session-1", start + 10),
        store.observe("synthetic-session-1", start + 900),
    ]
    policy = {"retention_ttl_seconds": 600, "retention_grace_seconds": 60}
    assert evaluate("runtime_retention", rows(records), RUN, 0, policy).verdict == expected
    assert evaluate("runtime_retention", rows(records[:1]), RUN, 0, policy).verdict == "not_tested"
    undeclared = evaluate("runtime_retention", rows(records), RUN, 0, {})
    assert undeclared.verdict == "not_tested" and "retention_ttl_seconds" in undeclared.explanation


def test_model_metadata_mismatch_and_missing_metadata():
    def record(model: str | None) -> dict:
        row = {"run_id": RUN, "event": "response"}
        if model:
            row["gen_ai.response.model"] = model
        return row

    expected = {"expected_model": "gemini-2.5-flash"}
    ok = evaluate("runtime_model", rows([record("gemini-2.5-flash")]), RUN, 0, expected)
    assert ok.verdict == "pass"
    drift = evaluate(
        "runtime_model", rows([record("gemini-2.5-flash"), record("gpt-4o-mini")]), RUN, 0, expected
    )
    assert drift.verdict == "fail" and "gpt-4o-mini" in drift.explanation
    absent = evaluate("runtime_model", rows([record(None)]), RUN, 0, expected)
    assert absent.verdict == "not_tested" and "does not guess" in absent.explanation
    assert evaluate("runtime_model", rows([record("x")]), RUN, 0, {}).verdict == "not_tested"


async def fixture_bot(faults: list[int], delay: float, retries: int, deadline: float) -> list[dict]:
    """A tiny bot that calls a controllable upstream stub with bounded retries."""
    records = []

    def upstream(request: httpx.Request) -> httpx.Response:
        index = sum(r["stage"] == "upstream_attempt" for r in records)
        status = faults[index] if index < len(faults) else 200
        records.append(
            {
                "run_id": RUN,
                "check": "timeouts_retries",
                "stage": "upstream_attempt",
                "attempt": index + 1,
                "status_code": status,
                "injected_delay_ms": int(delay * 1000),
            }
        )
        return httpx.Response(status, json={"ok": status == 200})

    started = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        try:
            async with asyncio.timeout(deadline):
                for _ in range(retries + 1):
                    await asyncio.sleep(delay)
                    if (await client.post("http://stub.test/v1/chat")).status_code == 200:
                        break
        except TimeoutError:
            pass
    records.append(
        {
            "run_id": RUN,
            "check": "timeouts_retries",
            "stage": "bot_response",
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    )
    return records


def test_timeout_fixture_measures_bounded_retries_and_deadline():
    policy = {"timeout_seconds": 1, "max_retries": 2, "deadline_tolerance": 0.5}
    bounded = asyncio.run(fixture_bot([429, 503], 0.01, retries=2, deadline=1))
    assert evaluate("runtime_timeouts", rows(bounded), RUN, 0, policy).verdict == "pass"
    unbounded = asyncio.run(fixture_bot([429] * 6, 0.01, retries=5, deadline=1))
    result = evaluate("runtime_timeouts", rows(unbounded), RUN, 0, policy)
    assert result.verdict == "fail" and "exceed max_retries=2" in result.explanation
    slow = [*bounded[:-1], {**bounded[-1], "elapsed_ms": 5000}]
    assert evaluate("runtime_timeouts", rows(slow), RUN, 0, policy).verdict == "fail"
    no_fault = asyncio.run(fixture_bot([], 0, retries=2, deadline=1))
    assert evaluate("runtime_timeouts", rows(no_fault), RUN, 0, policy).verdict == "not_tested"
    assert evaluate("runtime_timeouts", rows(bounded), RUN, 0, {}).verdict == "not_tested"


def test_runtime_checks_are_planned_and_expectations_keep_only_plain_values():
    assert set(RUNTIME_CHECKS) <= set(CHECKS)
    target = Target(url="http://localhost:8000/chat", model="declared-model-1")
    values = runtime_expectations(
        {"timeout_seconds": 30, "max_retries": True, "expected_model": {"x": 1}, "api_key": "k"},
        target,
        {"deadline_tolerance": 0.1},
    )
    assert values == {
        "deadline_tolerance": 0.1,
        "timeout_seconds": 30,
        "expected_model": "declared-model-1",
    }
    guidance = readiness.check_guidance("gray", "runtime_retention")
    assert "retention_ttl_seconds" in " ".join(guidance["required_evidence"])


def test_gray_run_then_attach_correlated_logs(monkeypatch):
    config = Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        judges=[JudgeSelection(model="fixture", local=True)],
        simple_mode=True,
        consent=True,
        judge_consent=True,
    )
    early = intake.store(
        "logs", json.dumps([{"run_id": OTHER, "event": "before the test"}]).encode(), "a.json"
    )
    plan = GrayEngine(config, RUN, False, asyncio.Event()).plan({"logs": early["id"]})
    rows_by_test = {row["test"]: row for row in plan}
    findings = asyncio.run(
        GrayEngine(config, RUN, False, asyncio.Event()).run(
            [rows_by_test[test] for test in RUNTIME_CHECKS]
        )
    )
    assert {f.verdict for f in findings} == {"not_tested"}
    run = {
        "id": RUN,
        "config": {"targets": [config.targets[0].model_dump(exclude={"token"})]},
        "protocol_snapshot": {"gray_suite": {"runtime_policy": {}}},
        "modes": ["gray"],
        "status": "completed",
        "findings": [f.model_dump() for f in findings],
        "planned_checks": [
            {"mode": "gray", "bot": 0, "category": f.category, "test": f.test_id} for f in findings
        ],
        "audit": [],
        "input_hashes": [],
    }
    governance.append(run, "start")
    service.checkpoint(run)
    tool = OrderTool(True)
    later = intake.store(
        "logs",
        json.dumps(
            [tool.call("synthetic-user-a", "order-a"), tool.call("synthetic-user-a", "order-b")]
        ).encode(),
        "b.json",
    )
    client = TestClient(blackbox_app.app)
    response = client.post(
        f"/api/assurance/runs/{RUN}/canary-logs",
        json={"bot": 0, "logs": later["id"]},
        headers={"X-Studio-Request": "1"},
    )
    assert response.status_code == 200
    saved = db.get("assurance", RUN)
    verdicts = {f["test_id"]: f["verdict"] for f in saved["findings"]}
    assert verdicts["runtime_tool_permissions"] == "pass"
    assert verdicts["runtime_model"] == "not_tested"
    assert service.integrity(saved)["valid"] is True
    assert any(e["event"] == "canary_logs_added" for e in saved["audit"])
