"""Offline assurance contracts: no provider requests or uploaded-code execution."""

import asyncio
import io
import itertools
import json
import stat
import uuid
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.assurance import intake, sandbox, service
from app.assurance.combine import combine
from app.assurance.gray import GrayEngine, log_finding, private_settings
from app.assurance.models import Assessment, Evidence, Finding, missing
from app.assurance.privacy import CANARY_MARKER, CANARY_PHONE, CANARY_SECRET, trace_rows
from app.assurance.white import CHECKS, WhiteEngine, parse
from app.blackbox import governance, judge, studio_engine
from app.blackbox.cost_summary import money, totals
from app.blackbox.runner import aggregate, make_run
from app.blackbox.schema import JudgeSelection, Settings, Target


def config(**kw):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        judges=[JudgeSelection(model="fixture", local=True)],
        simple_mode=True,
        consent=True,
        judge_consent=True,
        auto_local_fallback=False,
        **kw,
    )


def finding(mode="black", verdict="pass", **kw):
    return Finding(
        mode=mode,
        category="guardrails",
        test_id="fixture",
        verdict=verdict,
        evidence=[
            Evidence(kind="transcript" if mode == "black" else "code", excerpt="Fixture evidence")
        ],
        explanation="Fixture",
        checked="Fixture check",
        consequence="Fixture consequence",
        fix="Fixture fix",
        **kw,
    )


def zipped(name="bot.py", content=b"print('never execute me')", mode=0):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        item = zipfile.ZipInfo(name)
        item.external_attr = mode << 16
        archive.writestr(item, content)
    return data.getvalue()


@pytest.mark.parametrize(
    "modes",
    [list(m) for n in (1, 2, 3) for m in itertools.combinations(("black", "gray", "white"), n)],
)
def test_only_selected_engines_run_and_all_checks_accounted(monkeypatch, modes):
    called = []

    async def black(self, plan):
        called.append("black")
        await asyncio.sleep(0)
        return [
            finding("black", score=90).model_copy(
                update={"test_id": row["test"], "category": row["category"], "bot": row["bot"]}
            )
            for row in plan
        ]

    async def gray(self, plan):
        called.append("gray")
        return [
            missing("gray", row["bot"], row["category"], row["test"], "Missing fixture input")
            for row in plan
        ]

    async def white(self, plan):
        called.append("white")
        return [
            missing("white", row["bot"], row["category"], row["test"], "Missing fixture tool")
            for row in plan
        ]

    monkeypatch.setattr("app.assurance.black.BlackEngine.run", black)
    monkeypatch.setattr(GrayEngine, "run", gray)
    monkeypatch.setattr(WhiteEngine, "run", white)
    request = Assessment(settings=config(), modes=modes, ownership_confirmed=True)

    async def execute():
        started = service.start(request)
        await service.TASKS[started["id"]]
        return db.get("assurance", started["id"])

    run = asyncio.run(execute())
    assert set(called) == set(modes)
    assert run["status"] == "completed"
    assert set(f["mode"] for f in run["findings"]) == set(modes)
    assert len(run["findings"]) == len(run["planned_checks"])
    assert all(f["explanation"] != "Pending execution." for f in run["findings"])
    assert governance.verify(run)["valid"] is True


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [finding(verdict="fail", score=0), finding("white", "fail", control=False)],
            "Confirmed risk",
        ),
        (
            [finding(verdict="fail", score=0), finding("white", "exists", control=True)],
            "Control exists but isn't working",
        ),
        ([finding(score=100), finding("gray", "exists", control=True)], "Defended"),
        ([finding(score=100)], "Passed, code not checked"),
        ([finding("white", "exists", control=True)], "Not tested"),
    ],
)
def test_combiner_requires_behavior_evidence(rows, expected):
    assert (
        combine(rows, list(dict.fromkeys(r.mode for r in rows)))["categories"][0]["label"]
        == expected
    )


def test_not_tested_cannot_have_a_score_or_evidence_free_pass():
    assert missing("black", 0, "bias", "test", "Quota failed").score is None
    with pytest.raises(ValueError):
        Finding(
            mode="white",
            category="pii",
            test_id="missing",
            verdict="pass",
            explanation="No evidence",
            checked="x",
            consequence="y",
            fix="z",
        )


@pytest.mark.parametrize(
    "name",
    [
        "../escape.py",
        "/escape.py",
        "C:/escape.py",
        "folder/../../escape.py",
        "foo:stream",
        "a\\..\\escape.py",
    ],
)
def test_archive_traversal_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        intake.unpack(zipped(name), tmp_path)


def test_archive_links_size_and_entry_limits(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        intake.unpack(zipped("link", b"../../target", stat.S_IFLNK | 0o777), tmp_path)
    monkeypatch.setitem(intake.LIMITS, "file_bytes", 3)
    with pytest.raises(ValueError):
        intake.unpack(zipped(content=b"too long"), tmp_path)


def test_archive_expansion_ratio_and_duplicate_names(tmp_path):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.txt", b"a" * 100000)
    with pytest.raises(ValueError):
        intake.unpack(raw.getvalue(), tmp_path)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("A.py", "x")
        archive.writestr("a.py", "y")
    with pytest.raises(ValueError):
        intake.unpack(raw.getvalue(), tmp_path)


def test_sandbox_command_is_networkless_read_only_and_bounded(tmp_path):
    args = sandbox.command("gitleaks", tmp_path, "fixture", "sha256:fixture")
    for flag in (
        "--read-only",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=512m",
        "--cpus=1",
        "--pids-limit=64",
        "--pull=never",
    ):
        assert flag in args
    assert "docker.sock" not in " ".join(args)
    assert all("readonly" in args[i + 1] for i, arg in enumerate(args) if arg == "--mount")


def test_missing_input_or_tool_is_never_pass(monkeypatch):
    engine = WhiteEngine()
    results = asyncio.run(engine.run(engine.plan({})))
    assert len(results) == len(CHECKS)
    assert all(f.verdict == "not_tested" and f.explanation for f in results)
    record = intake.store("code", zipped(), "source.zip")
    monkeypatch.setattr(
        sandbox, "scan", AsyncMock(side_effect=sandbox.ToolUnavailable("Docker not installed"))
    )
    results = asyncio.run(engine.run(engine.plan({"code": record["id"]})))
    assert all(f.verdict == "not_tested" for f in results)
    assert "Docker" in results[0].explanation


def test_secret_excerpts_masked_to_last_four(tmp_path):
    secret = "sk-" + "syntheticOnly" * 3 + "1234"
    (tmp_path / "bot.py").write_text(f'API_KEY = "{secret}"')
    result = parse(
        "hardcoded_secrets",
        {
            "data": [{"File": "/source/bot.py", "StartLine": 1}],
            "version": "8.24.2",
            "image_id": "sha256:test",
            "ruleset": "v1",
        },
        tmp_path,
        0,
    )
    assert result.severity == "Critical"
    assert secret not in result.model_dump_json()
    assert "1234" in result.model_dump_json()


def test_logs_redacted_before_analysis_and_canaries_correlated():
    record = {
        "test_marker": CANARY_MARKER,
        "tool": "search",
        "arguments": {"phone": CANARY_PHONE},
        "secret": CANARY_SECRET,
        "email": "person@example.org",
        "unknown": "private body",
    }
    rows, metadata = trace_rows(json.dumps([record]).encode())
    text = json.dumps(rows)
    assert (
        CANARY_PHONE not in text and CANARY_SECRET not in text and "person@example.org" not in text
    )
    assert "unknown" not in text
    finding = log_finding("canary_logging", rows, metadata, config().targets[0], 0)
    assert finding.verdict == "fail"
    assert finding.evidence and CANARY_PHONE not in finding.model_dump_json()
    absent = log_finding("canary_logging", rows, {}, config().targets[0], 0)
    assert absent.verdict == "not_tested"


def test_private_inputs_require_local_judge_unless_explicit_opt_in(monkeypatch):
    cfg = config()
    cfg.judges = [JudgeSelection(model="cloud", url="https://example.org/v1/chat/completions")]
    monkeypatch.setattr(
        "app.assurance.gray.local_fallbacks",
        AsyncMock(return_value=[JudgeSelection(model="gemma-fixture", local=True)]),
    )
    selected = asyncio.run(private_settings(cfg, False))
    assert all(j.local and not j.fallback for j in selected.judges)
    assert asyncio.run(private_settings(cfg, True)).judges[0].model == "cloud"


def test_ownership_required_and_all_inputs_have_explicit_missing_findings():
    with pytest.raises(ValueError):
        Assessment(settings=config(), modes=["white"])
    plan = GrayEngine(config(), str(uuid.uuid4()), False, asyncio.Event()).plan({})
    results = asyncio.run(GrayEngine(config(), str(uuid.uuid4()), False, asyncio.Event()).run(plan))
    assert len(results) == len(plan)
    assert all(f.verdict == "not_tested" and "Missing" in f.explanation for f in results)


def test_review_requires_reason_keeps_original_and_hash_chain():
    ident = str(uuid.uuid4())
    result = finding(verdict="fail", score=10, severity="High").model_dump()
    run = {
        "id": ident,
        "config": {},
        "protocol_snapshot": {},
        "modes": ["black"],
        "status": "completed",
        "findings": [result],
        "audit": [],
        "input_hashes": [],
    }
    governance.append(run, "start")
    service.checkpoint(run)
    headers = {"X-Studio-Request": "1"}
    client = TestClient(blackbox_app.app)
    body = {
        "bot": 0,
        "mode": "black",
        "test_id": "fixture",
        "false_positive": True,
        "reason": "too short",
    }
    assert (
        client.post(f"/api/assurance/runs/{ident}/review", json=body, headers=headers).status_code
        == 422
    )
    body["reason"] = "Checked manually against the exact transcript."
    assert (
        client.post(f"/api/assurance/runs/{ident}/review", json=body, headers=headers).status_code
        == 200
    )
    saved = db.get("assurance", ident)
    assert saved["findings"][0]["original_finding"]["score"] == 10
    assert saved["findings"][0]["overridden"]
    assert any(e["event"] == "finding_review" and e["old"]["score"] == 10 for e in saved["audit"])
    assert governance.verify(saved)["valid"]


def test_empty_cost_is_unknown_and_tiny_cost_is_visible():
    assert totals([])["cost_micro_usd"] is None
    assert money(None) == "Unknown"
    assert money(5) == "<$0.0001"
    assert money(0, local=True) == "$0 (local)"


def test_public_legacy_start_cannot_bypass_ownership_confirmation():
    client = TestClient(blackbox_app.app)
    response = client.post(
        "/api/studio/runs", json=config().model_dump(mode="json"), headers={"X-Studio-Request": "1"}
    )
    assert response.status_code == 422 and "ownership" in response.json()["detail"]


def test_invalid_source_zip_returns_actionable_422():
    response = TestClient(blackbox_app.app).post(
        "/api/assurance/inputs/code",
        files={"file": ("invalid.zip", b"not a zip")},
        headers={"X-Studio-Request": "1"},
    )
    assert response.status_code == 422


def test_low_confidence_below_half_coverage(monkeypatch):
    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    run = make_run(config())
    run["cases"][0]["results"][0].update(status="passed", score=100)
    aggregate(run)
    assert run["studio"]["bots"][0]["categories"][0]["low_confidence"]


def test_quota_falls_back_once_and_resume_reuses_cached_bot(monkeypatch):
    called = []

    async def evaluate(cfg, case, observation):
        called.append(cfg.judge_model)
        if cfg.judge_model == "cloud":
            raise ValueError("Daily quota exhausted")
        return {"score": 90, "reason": "Exact fixture reply", "evidence": ["fixture reply"]}

    monkeypatch.setattr(judge, "evaluate", evaluate)
    cfg = config()
    cfg.judges = [
        JudgeSelection(model="cloud"),
        JudgeSelection(model="local", local=True, fallback=True),
    ]

    async def run():
        for i in range(2):
            result = await studio_engine.panel(
                cfg, {"id": str(i)}, {"transcript": [{"output": "fixture reply"}]}
            )
            assert result["panel_complete"] and result["score"] == 90

    asyncio.run(run())
    assert called == ["cloud", "local", "local"]


def test_each_extracted_rule_gets_its_own_planned_check():
    record = intake.store(
        "system_prompt",
        b"You must protect private data. You should only discuss shop support.",
        "prompt.txt",
    )
    engine = GrayEngine(config(), str(uuid.uuid4()), False, asyncio.Event())
    plan = engine.plan({"system_prompt": record["id"]})
    rules = [r for r in plan if r.get("base_test") == "declared_behavior"]
    assert len(rules) == 2 and rules[0]["test"] != rules[1]["test"]
    assert record["unlocks"] == 3


def test_canary_from_another_run_cannot_score_this_run():
    other_id, this_id = str(uuid.uuid4()), str(uuid.uuid4())
    raw = json.dumps(
        [{"event": f"{CANARY_MARKER} run_id={other_id}", "arguments": CANARY_PHONE}]
    ).encode()
    rows, metadata = trace_rows(raw)
    assert (
        log_finding("canary_logging", rows, metadata, config().targets[0], 0, this_id).verdict
        == "not_tested"
    )
    assert (
        log_finding("canary_logging", rows, metadata, config().targets[0], 0, other_id).verdict
        == "fail"
    )


def test_tampered_finding_fails_anchored_state_integrity():
    run = {
        "id": str(uuid.uuid4()),
        "config": {},
        "modes": ["black"],
        "findings": [finding(score=90).model_dump()],
        "audit": [],
    }
    service.checkpoint(run)
    assert service.integrity(run)["valid"]
    run["findings"][0]["score"] = 100
    assert service.integrity(run)["valid"] is False


def test_resume_can_judge_saved_reply_when_target_is_offline(monkeypatch):
    from app.blackbox import runner
    from app.blackbox.execution_cache import observation_key, write

    cfg = config(repeat_counts={c["category"]: 1 for c in studio_engine.settings_file()["cases"]})
    run = make_run(cfg)
    case = run["cases"][0]
    write(
        run["id"],
        "bot",
        observation_key(cfg, 0, case),
        {
            "transcript": [
                {"input": t, "output": "Saved answer", "seconds": 0.1} for t in case["turns"]
            ],
            "error": None,
        },
    )
    monkeypatch.setattr(
        studio_engine,
        "panel",
        AsyncMock(
            return_value={"score": 90, "reason": "Saved answer", "evidence": ["Saved answer"]}
        ),
    )
    monkeypatch.setattr(runner, "summarize", lambda r: {})
    monkeypatch.setattr(runner, "save", lambda *a: None)

    class Offline:
        def __init__(self, *args):
            self.kind = "rest"

        async def detect(self):
            raise ValueError("Backend offline")

        async def conversation(self, case):
            raise AssertionError("Must not replay an existing bot response")

        async def close(self):
            pass

    asyncio.run(runner.execute(run, cfg, Offline))
    assert case["results"][0]["score"] == 90
    assert case["results"][0]["transcript"][0]["output"] == "Saved answer"
