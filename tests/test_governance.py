"""AI governance: personal-data masking, the audit log, run seals, release gate, sign-off and retention (no network)."""

import json
from datetime import datetime

import pytest

import compliance
import evaluator
import governance
import review
from adapters import Reply


def aadhaar(first11):
    """A valid Aadhaar-shaped number: 11 digits plus the Verhoeff check digit."""
    return next(first11 + str(d) for d in range(10) if governance._verhoeff(first11 + str(d)))


# ---------- Personal data ----------

def test_finds_each_kind_and_checks_card_and_aadhaar_digits():
    a = aadhaar("23456789012")
    text = (f"Mail a.b@shop.co.in or pay to ravi@okicici. Card 4111 1111 1111 1111, not 4111 1111 1111 1112. "
            f"Aadhaar {a[:4]} {a[4:8]} {a[8:]}, PAN ABCPE1234F, call +91-98765 43210 or 9123456780. Order ORD9876543210.")
    kinds = [k for k, *_ in governance.find_pii(text)]
    assert kinds == ["email", "upi", "card", "aadhaar", "pan", "phone", "phone"]


def test_a_card_number_is_not_also_reported_as_aadhaar_or_phone():
    assert [k for k, *_ in governance.find_pii("4111111111111111")] == ["card"]


def test_redact_masks_only_values_not_in_the_test_data():
    known = governance.known_values("Store data: customer phone 9876543210, email customer@example.com")
    text = "Your number +91 98765 43210 is on file. Another customer's is 9123456780, mail them at x@y.com."
    masked, counts = governance.redact(text, known)
    assert "98765 43210" in masked and "9123456780" not in masked and "x@y.com" not in masked
    assert "[phone number]" in masked and "[email address]" in masked
    assert counts == {"phone": 1, "email": 1}


def test_outbound_skips_local_judges_and_follows_the_policy(monkeypatch):
    prompt = "CHATBOT: call 9123456780"
    assert governance.outbound(prompt, set(), "http://localhost:11434/v1") == (prompt, {})
    assert governance.outbound(prompt, set(), "https://api.example.com/v1")[1] == {"phone": 1}
    monkeypatch.setattr(governance, "load_policy", lambda: {"data": {"pii": "flag"}})
    assert governance.outbound(prompt, set(), "https://api.example.com/v1") == (prompt, {})


def test_the_judge_sees_store_data_but_not_unknown_personal_data(monkeypatch):
    sent = []

    def structured(system, prompt, schema, name):
        sent.append(prompt)
        return {"correctness": 5, "helpfulness": 5, "tone": 5, "hallucinated": False, "grounded": True,
                "passed": True, "reason": "ok"}

    monkeypatch.setattr(evaluator.llm.JUDGE, "structured", structured)
    monkeypatch.setattr(evaluator.llm.JUDGE, "base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    turns = [{"user": "My number is 9876543210, what's my order?", "bot": "Order for 9876543210 ships today. "
              "Also, 9123456780 ordered the same TV."}]
    verdict = evaluator.judge("Customer phone 9876543210", "Answer the order", turns)
    assert "9876543210" in sent[0] and "9123456780" not in sent[0]
    assert verdict["masked"] == {"phone": 1}


def test_a_result_counts_personal_data_the_bot_made_up(monkeypatch):
    class Conv:
        def send(self, m):
            return Reply(text="Sure, call our customer 9123456780.", latency_ms=5)

        def close(self):
            pass

    monkeypatch.setattr(evaluator, "open_conversation", lambda cfg: Conv())
    suite = {"profiles": {"p": {"context": "Phone 9876543210", "vars": {}}},
             "cases": [{"id": "c", "category": "guardrails", "turns": ["Hi"]}]}
    r = evaluator._run_case(suite, suite["cases"][0], {"id": "b", "profile": "p"}, use_judge=False)
    assert r["pii"] == {"phone": 1}


# ---------- Audit log ----------

def test_the_audit_log_chain_detects_edits_and_removals(audit_log):
    for i in range(3):
        governance.record("test.action", f"t{i}", by="tester", n=i)
    assert governance.verify_log() | {"head": None} == {"ok": True, "entries": 3, "first_bad": None, "problem": None,
                                                         "head": None, "keyed": True}
    assert [e["seq"] for e in governance.read_log()] == [3, 2, 1]
    lines = audit_log.read_text().splitlines()

    edited = json.loads(lines[1])
    edited["details"]["n"] = 99
    audit_log.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n")
    v = governance.verify_log()
    assert not v["ok"] and v["first_bad"] == 2 and "edited" in v["problem"]

    audit_log.write_text("\n".join([lines[0], lines[2]]) + "\n")
    v = governance.verify_log()
    assert not v["ok"] and "removed" in v["problem"]


def test_a_rehashed_chain_or_a_cut_off_tail_is_caught(audit_log):
    for i in range(3):
        governance.record("test.action", f"t{i}", by="tester", n=i)
    lines = [json.loads(x) for x in audit_log.read_text().splitlines()]

    # rewrite entry 3 and recompute its hash, as anyone could with a plain hash chain
    forged = {k: v for k, v in lines[2].items() if k not in ("hash", "mac")} | {"actor": "someone else"}
    forged["hash"] = governance._entry_hash(forged)
    audit_log.write_text("\n".join(json.dumps(x) for x in [lines[0], lines[1], forged | {"mac": lines[2]["mac"]}]) + "\n")
    v = governance.verify_log()
    assert not v["ok"] and "HMAC" in v["problem"]

    audit_log.write_text("\n".join(json.dumps(x) for x in lines[:2]) + "\n")  # last entry removed: chain still valid
    v = governance.verify_log()
    assert not v["ok"] and "cut off" in v["problem"]


def test_a_run_is_sealed_and_a_later_edit_shows():
    run = {"id": "r1", "results": [{"case_id": "c", "bot_id": "a", "checks": True}], "comparisons": []}
    assert governance.integrity(run) == "unsealed"
    governance.record("run.finish", "r1", results_sha256=governance.seal(run))
    assert governance.integrity(run) == "intact"
    run["results"][0]["checks"] = False
    assert governance.integrity(run) == "modified"


# ---------- Release gate and sign-off ----------

POLICY = {"version": 7, "release_gate": {
    "require_judge": True, "min_scores": {"safety": 90, "accuracy": 50}, "max_failed_cases": {"guardrails": 0},
    "max_critical_regressions": 0, "approved_models_only": True,
    "warn": {"max_unknown_pii": 0, "min_review_labels": 50}},
    "models": {"bot_llms": ["Gemini *"], "judges": ["gemini-*"]}, "data": {"pii": "redact", "retention_days": 30}}
JUDGE = {"correctness": 5, "helpfulness": 5, "tone": 5, "hallucinated": False, "passed": True, "reason": "",
         "model": "gemini-2.5-flash"}


def res(bot, case, category="products", passed=True, **extra):
    return {"case_id": case, "bot_id": bot, "category": category, "repeat": 0, "error": None, "unsupported": False,
            "checks": passed, "check_failures": [], "judge": dict(JUDGE),
            "turns": [{"user": "q", "bot": "a", "latency_ms": 1000}], **extra}


def make_run(run_id="r", created="2026-10-10T00:00:00", leaky=False, llm="Gemini 3.6 Flash"):
    results = [res("good", f"p{i}") for i in range(5)] + [res("good", "g1", "guardrails")]
    results += [res("leaky", f"p{i}") for i in range(5)]
    results += [res("leaky", "g1", "guardrails", passed=not leaky, **({"pii": {"phone": 1}} if leaky else {}))]
    run = {"id": run_id, "created_at": created, "suite": "s", "suite_name": "S", "suite_sha256": "x", "status": "done",
           "progress": {"done": 12, "total": 12}, "judge": True,
           "judge_model": "gemini-2.5-flash", "bots": [{"id": "good", "label": "Good"}, {"id": "leaky", "label": "Leaky"}],
           "bot_configs": [{"id": "good", "label": "Good", "llm": llm}, {"id": "leaky", "label": "Leaky", "llm": llm}],
           "results": results, "comparisons": []}
    run["summary"] = evaluator.summarise(run, {"cases": [{"category": "products"}, {"category": "guardrails"}]})
    return run


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(governance, "load_policy", lambda: POLICY)
    monkeypatch.setattr(governance, "POLICY_FILE", str(tmp_path / "governance.json"))
    monkeypatch.setattr(compliance, "SIGNOFFS_FILE", str(tmp_path / "signoffs.json"))
    monkeypatch.setattr(evaluator, "BASELINES_FILE", str(tmp_path / "baselines.json"))
    monkeypatch.setattr(review, "LABELS_FILE", str(tmp_path / "labels.json"))
    monkeypatch.setattr(evaluator, "RUNS_DIR", str(tmp_path))
    runs = {}
    monkeypatch.setattr(evaluator, "_runs", runs)
    monkeypatch.setattr(evaluator, "get_run", runs.get)
    monkeypatch.setattr(evaluator, "load_runs", lambda only_new=False: None)

    def add(run, sealed=True):
        runs[run["id"]] = run
        (tmp_path / f"{run['id']}.json").write_text(json.dumps(run))
        if sealed:
            governance.record("run.finish", run["id"], results_sha256=governance.seal(run))
        return run
    return add


def verdicts(result):
    return {b["id"]: b for b in result["bots"]}


def rule(bot, rule_id):
    return next(r for r in bot["rules"] if r["id"] == rule_id)


def test_the_gate_passes_a_good_bot_and_blocks_a_data_leak(store):
    g = verdicts(compliance.gate(store(make_run(leaky=True))))
    assert g["good"]["verdict"] == "warn"  # only warn rules fail: a Gemini judge on a Gemini bot, too few labels
    assert [r["id"] for r in g["good"]["rules"] if r["ok"] is False] == ["judge_independence", "review_labels"]
    assert g["leaky"]["verdict"] == "fail"
    assert rule(g["leaky"], "max_failed_guardrails")["ok"] is False and "g1" in rule(g["leaky"], "max_failed_guardrails")["text"]
    assert rule(g["leaky"], "unknown_pii")["ok"] is False
    assert rule(g["good"], "critical_regressions")["ok"] is None  # no baseline: not applicable


def test_the_gate_blocks_unapproved_models_and_an_edited_run(store):
    run = store(make_run(llm="GPT-5 mini"))
    run["results"][0]["judge"]["model"] = "gpt-5"
    g = verdicts(compliance.gate(run))["good"]
    assert rule(g, "approved_bot_llm")["ok"] is False and rule(g, "approved_judges")["ok"] is False
    assert rule(g, "integrity")["ok"] is False and rule(g, "integrity")["level"] == "block"


def test_a_blocked_bot_needs_an_override_with_a_reason(store):
    store(make_run(leaky=True))
    with pytest.raises(ValueError, match="blocks this bot"):
        compliance.signoff("r", "leaky", "approve", "Asha")
    with pytest.raises(ValueError, match="justification"):
        compliance.signoff("r", "leaky", "approve", "Asha", "ok", override=True)
    e = compliance.signoff("r", "leaky", "approve", "Asha", "Card leak fixed in hotfix 12, verified by hand.", True)
    assert e["override"] and e["gate_verdict"] == "fail" and e["policy_version"] == 7
    assert compliance.signoff("r", "good", "approve", "Asha")["override"] is False
    with pytest.raises(ValueError, match="reviewer"):
        compliance.signoff("r", "good", "reject", " ")
    status = compliance.release_status()
    assert status["leaky"]["decision"] == "approve" and status["good"]["reviewer"] == "Asha"
    actions = [(e["action"], e["details"].get("bot")) for e in governance.read_log()]
    assert ("signoff", "leaky") in actions and ("signoff", "good") in actions


def test_an_edited_run_cannot_be_approved_even_with_an_override(store):
    run = store(make_run())
    run["results"][0]["checks"] = False
    with pytest.raises(ValueError, match="changed after"):
        compliance.signoff("r", "good", "approve", "Asha", "x" * 40, override=True)


# ---------- Retention ----------

def test_retention_keeps_baselines_and_signed_off_runs(store):
    for rid in ("old-plain", "old-base", "old-signed", "new"):
        store(make_run(rid, "2026-10-10T00:00:00" if rid == "new" else "2026-08-01T00:00:00"))
    evaluator.set_baseline("old-base")
    compliance.signoff("old-signed", "good", "reject", "Asha", "not ready")
    now = datetime(2026, 10, 12)
    assert compliance.purge(dry_run=True, now=now)["runs"] == ["old-plain"]
    assert "old-plain" in evaluator._runs
    r = compliance.purge(now=now)
    assert r["runs"] == ["old-plain"] and r["kept"] == 2 and "old-plain" not in evaluator._runs
    assert governance.read_log(action="retention.purge")[0]["details"]["runs"] == ["old-plain"]
    assert governance.read_log(action="run.delete")[0]["target"] == "old-plain"


# ---------- Risk register and report ----------

def test_report_has_release_status_risks_and_model_cards(store, monkeypatch):
    store(make_run(leaky=True))
    monkeypatch.setattr(compliance, "configured_bots", lambda: [{"id": "good", "label": "Good", "llm": "Gemini 3.6 Flash",
                                                                 "profile": "voltkart"},
                                                                {"id": "leaky", "label": "Leaky", "llm": "Gemini 3.6 Flash",
                                                                 "profile": "voltkart"}])
    policy = {**POLICY, "risks": [{"id": "R2", "title": "Leaks", "metric": "category:guardrails", "min": 100},
                                  {"id": "R11", "title": "AI disclosure", "metric": "manual"}]}
    monkeypatch.setattr(governance, "load_policy", lambda: policy)
    ov = compliance.overview()
    r2 = ov["risks"][0]["status"]
    assert r2["good"]["status"] == "ok" and r2["leaky"]["status"] == "breach"
    assert ov["risks"][1]["status"]["good"]["status"] == "manual"
    assert ov["bots"][1]["card"]["limitations"]
    md = compliance.report_markdown(ov)
    assert "## Risk register" in md and "### Leaky" in md and "FAIL" in md


def test_the_head_is_published_off_the_machine_and_a_rewrite_is_caught_against_it(audit_log, monkeypatch):
    for i in range(3):
        governance.record("test.action", f"t{i}", by="tester", n=i)
    monkeypatch.setenv("AUDIT_ANCHOR_WEBHOOK", "https://chat.example/hook")
    monkeypatch.setenv("AUDIT_ANCHOR_S3", "s3://evidence/chatbot-compare")
    posted, stored = [], []
    a = governance.anchor("test", post=lambda url, text: posted.append(text),
                          put=lambda target, rec: stored.append(rec) or "s3://evidence/x")
    assert a["seq"] == 3 and a["sent"] == ["webhook", "s3://evidence/x"] and a["hash"] in posted[0]
    assert stored[0]["hash"] == a["hash"] and governance.verify_against(3, a["hash"])["ok"]

    # someone with the key rewrites the whole log: it verifies on its own, but not against the published head
    audit_log.unlink()
    for i in range(3):
        governance.record("test.action", f"t{i}", by="someone else", n=i)
    assert governance.verify_log()["ok"]
    assert not governance.verify_against(3, a["hash"])["ok"]
    failing = governance.anchor("x", post=lambda *_: (_ for _ in ()).throw(OSError("down")), put=lambda *_: "s3://ok")
    assert failing["errors"] == ["webhook: down"] and failing["sent"] == ["s3://ok"]


def test_a_run_records_which_code_each_bot_ran_and_the_gate_flags_local_changes(tmp_path):
    import subprocess
    git = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    upstream, bot = tmp_path / "upstream.git", tmp_path / "bot"
    git("init", "-q", "--bare", str(upstream), cwd=tmp_path)
    git("clone", "-q", str(upstream), str(bot), cwd=tmp_path)
    (bot / "app.py").write_text("print('owner')\n")
    for args in (["add", "."], ["-c", "user.email=o@x", "-c", "user.name=o", "commit", "-qm", "owner"], ["push", "-q", "origin", "HEAD"]):
        git(*args, cwd=bot)
    git("branch", "-q", "--set-upstream-to", "origin/" + subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=bot,
        capture_output=True, text=True).stdout.strip(), cwd=bot)
    assert governance.source_info(str(bot))["own_code"] is True

    (bot / "app.py").write_text("print('ours')\n")  # the tester's change
    info = governance.source_info(str(bot))
    assert info["dirty"] and info["own_code"] is False

    plain = tmp_path / "unzipped"
    plain.mkdir()
    (plain / "main.py").write_text("x = 1\n")
    pin = governance.tree_sha256(str(plain))
    assert governance.source_info({"path": str(plain), "sha256": pin})["own_code"] is True
    (plain / "main.py").write_text("x = 2\n")
    assert governance.source_info({"path": str(plain), "sha256": pin})["own_code"] is False

    run = make_run()
    run["provenance"] = governance.provenance([{"id": "good", "source": str(bot)},
                                               {"id": "leaky", "source": {"path": str(plain), "sha256": pin}}], __file__)
    rules = {b["id"]: {r["id"]: r for r in b["rules"]} for b in compliance.gate(run)["bots"]}
    assert rules["good"]["bot_source"]["ok"] is False and "uncommitted changes" in rules["good"]["bot_source"]["text"]
    assert rules["leaky"]["bot_source"]["ok"] is False and "pinned hash" in rules["leaky"]["bot_source"]["text"]


def test_a_profile_review_sheet_lists_excused_skills_and_facts():
    sheet = compliance.profile_sheet("store_support", "hussain")
    assert "Status: **unreviewed**" in sheet and "order_verification" in sheet and "order-wrong-phone" in sheet
    assert "| `headphones_price` | 26,990 |" in sheet and "review-profile store_support hussain" in sheet


def test_a_run_whose_judge_failed_names_no_winner_and_fails_the_gate(store):
    run = make_run()
    for r in run["results"]:  # the judge model was retired mid-run: every verdict is an error
        r["judge"], r["judge_error"] = None, "moonshotai/kimi-k3: HTTP 410: end of life"
    run["summary"] = evaluator.summarise(run, {"cases": [{"category": "products"}, {"category": "guardrails"}]})
    assert run["summary"]["winner"] is None and run["summary"]["judge_incomplete"] == ["Good", "Leaky"]
    g = verdicts(compliance.gate(store(run)))
    assert rule(g["good"], "judge")["ok"] is False and g["good"]["verdict"] == "fail"
    assert "0% of answered cases" in rule(g["good"], "judge")["text"]


def test_the_gate_accepts_a_judge_that_graded_every_answered_case(store):
    g = verdicts(compliance.gate(store(make_run())))
    assert rule(g["good"], "judge")["ok"] is True and "100%" in rule(g["good"], "judge")["text"]
