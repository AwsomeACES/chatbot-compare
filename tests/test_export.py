"""CSV and printable report exports (no network)."""

import csv
import io

import evaluator
import export

J = {"correctness": 2, "helpfulness": 3, "tone": 5, "hallucinated": True, "passed": False, "reason": "Invented a courier.",
     "model": "gemini-2.5-flash"}


def run():
    results = [
        {"case_id": "price", "bot_id": "a", "category": "products", "repeat": 0, "at": "2026-10-12T10:00:00",
         "error": None, "unsupported": False, "checks": True, "check_failures": [], "rubric": "States 100.",
         "judge": {**J, "passed": True, "hallucinated": False, "reason": "ok"},
         "turns": [{"user": "Price of TV-A?", "bot": "Rs 100", "latency_ms": 900}]},
        {"case_id": "courier", "bot_id": "a", "category": "hallucination", "repeat": 0, "error": None,
         "unsupported": False, "checks": False, "check_failures": ["should not mention: BlueDart"], "rubric": "No courier.",
         "judge": J, "pii": {"phone": 1}, "turns": [{"user": "Which courier?", "bot": "BlueDart, call 9123456780", "latency_ms": 1500}]},
        {"case_id": "quota", "bot_id": "a", "category": "products", "repeat": 0, "error": "HTTP 429: quota",
         "blocked": True, "unsupported": False, "checks": None, "check_failures": [], "judge": None, "turns": []},
        {"case_id": "ticket", "bot_id": "a", "category": "after-sales", "repeat": 0, "error": None, "unsupported": True,
         "checks": None, "check_failures": [], "judge": None, "turns": []},
        {"case_id": "crash", "bot_id": "a", "category": "orders", "repeat": 0, "error": "HTTP 500: boom",
         "unsupported": False, "checks": None, "check_failures": [], "judge": None, "turns": []},
    ]
    r = {"id": "r1", "created_at": "2026-10-12T09:59:00", "suite": "nope", "suite_name": "T", "status": "running",
         "judge": True, "judge_model": "gemini-2.5-flash", "bots": [{"id": "a", "label": "Bot A"}],
         "bot_configs": [{"id": "a", "label": "Bot A", "llm": "Gemini 2.5 Flash", "model": "gemini-2.5-flash"}],
         "results": results}
    r["summary"] = evaluator.summarise(r, {"cases": [{"category": c} for c in ("products", "hallucination", "after-sales", "orders")]})
    return r


def test_outcomes_separate_errors_blocked_and_unsupported():
    assert run()["summary"]["bots"][0]["outcomes"] == {"pass": 1, "fail": 1, "error": 1, "blocked": 1,
                                                       "not supported": 1, "not graded": 0}


def test_csv_has_one_row_per_conversation_with_the_report_fields():
    rows = list(csv.DictReader(io.StringIO(export.csv_text(run()).lstrip("﻿"))))
    assert len(rows) == 5
    c = next(r for r in rows if r["case_id"] == "courier")
    assert c["outcome"] == "fail" and c["prompt"] == "Which courier?" and c["expected"] == "No courier."
    assert c["actual_response"].startswith("BlueDart") and c["evaluation_method"] == "exact checks + AI judge"
    assert "should not mention: BlueDart" in c["failure_reason"] and "Invented a courier" in c["failure_reason"]
    assert c["llm"] == "Gemini 2.5 Flash" and c["judge_model"] == "gemini-2.5-flash" and c["personal_data_in_reply"] == "phone 1"
    assert c["executed_at"] == "2026-10-12T09:59:00"  # older results without their own time: the run's
    p = next(r for r in rows if r["case_id"] == "price")
    assert p["outcome"] == "pass" and p["failure_reason"] == "" and p["executed_at"] == "2026-10-12T10:00:00"
    assert {r["case_id"]: r["outcome"] for r in rows}["crash"] == "error"


def test_report_lists_failures_first_and_escapes_bot_text():
    r = run()
    r["results"][1]["turns"][0]["bot"] = "<script>alert(1)</script>"
    html = export.report_html(r)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html
    assert html.index("did not pass") < html.index("courier") < html.index("Cases that passed")


def test_csv_has_bot_and_judge_tokens_and_estimated_cost():
    r = run()
    r["bot_configs"][0]["pricing"] = {"input": 2.0, "output": 10.0, "source": "list price"}
    r["judge_pricing"] = [{"model": "gemini-*", "input": 0, "output": 0, "source": "free tier"}]
    r["results"][0]["turns"][0]["usage"] = {"input_tokens": 1000, "output_tokens": 100}
    r["results"][0]["judge"]["usage"] = {"input_tokens": 1500, "output_tokens": 50}
    row = next(x for x in csv.DictReader(io.StringIO(export.csv_text(r).lstrip("﻿"))) if x["case_id"] == "price")
    assert (row["bot_input_tokens"], row["bot_output_tokens"], row["bot_total_tokens"]) == ("1000", "100", "1100")
    assert row["bot_cost_usd_estimate"] == "0.003" and row["bot_pricing_source"] == "list price"
    assert row["judge_tokens"] == "1550" and row["judge_cost_usd_estimate"] == "0.0" and row["judge_pricing_source"] == "free tier"
    other = next(x for x in csv.DictReader(io.StringIO(export.csv_text(r).lstrip("﻿"))) if x["case_id"] == "courier")
    assert other["bot_total_tokens"] == "" and other["judge_tokens"] == ""  # nothing reported: empty, not zero
