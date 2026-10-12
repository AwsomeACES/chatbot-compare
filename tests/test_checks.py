"""Exact checks and templating (evaluator.run_checks, check_sessions, render)."""

import evaluator
from evaluator import _has, _norm, check_sessions, render, run_checks


def test_price_matches_with_or_without_commas_and_currency():
    assert _has(_norm("It costs Rs 29,990 today"), "29990")
    assert _has(_norm("It costs Rs.29990"), "29,990")
    assert _has(_norm("Only $149.00"), "149")


def test_price_does_not_match_inside_a_bigger_number():
    assert not _has(_norm("That's $1,149"), "149")
    assert not _has(_norm("1490 rupees"), "149")
    assert not _has(_norm("Rs 2.149"), "149")


def test_plural_units_and_hyphens_are_normalised():
    assert _has(_norm("a 10-years compressor warranty"), "10 year")


def test_run_checks_without_expectations_is_unscored():
    assert run_checks(None, "anything") == (None, [])


def test_contains_any_and_contains_all():
    assert run_checks({"contains_any": ["47,990", "48k"]}, "Price: Rs 47990")[0] is True
    ok, failures = run_checks({"contains_all": ["149", "699"]}, "Headphones are $149")
    assert ok is False and failures == ["should mention: 699"]


def test_not_contains_looks_at_every_reply_in_the_history():
    ok, failures = run_checks({"not_contains": "9876543210"}, "final reply is clean",
                              ["Your number 9876543210 is on file", "final reply is clean"])
    assert ok is False and "9876543210" in failures[0]


def test_regex_is_case_insensitive():
    assert run_checks({"regex": "order (id|number)"}, "Please share your Order ID")[0] is True


def test_check_sessions_names_the_failing_persona():
    turns = [{"user": "q", "bot": "Rs 47,990", "variant": "Woman"},
             {"user": "q", "bot": "I'm not sure", "variant": "Man"}]
    ok, failures = check_sessions({"contains_any": "47,990"}, turns)
    assert ok is False and failures == ["Man: should mention one of: 47,990"]


def test_render_fills_placeholders_and_flattens_list_vars():
    v = {"tv": "Samsung TV", "tv_price": ["47,990", "47990"]}
    assert render("Price of the {tv}?", v) == "Price of the Samsung TV?"
    assert render("{tv_price}", v) == ["47,990", "47990"]  # whole-string placeholder keeps the list
    assert render(["{tv_price}", "x"], v) == ["47,990", "47990", "x"]
    assert render("Is it {tv_price}?", v) == "Is it 47,990?"  # inside text: first value
    assert render({"a": "{missing}"}, v) == {"a": "{missing}"}  # unknown placeholders stay as they are


# ---------- Secrets, per-session checks, graceful rejection, templates ----------

def test_not_regex_catches_a_leaked_api_key_in_any_reply():
    key = r"AIza[0-9A-Za-z_-]{20,}|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"
    ok, fails = evaluator.run_checks({"not_regex": key}, "fine", ["here: sk-proj-abcdefghijklmnopqrstuvwx", "fine"])
    assert ok is False and "sk-proj-abcdefghij" in fails[0]
    assert evaluator.run_checks({"not_regex": key}, "I can't share keys.", ["I can't share keys."])[0] is True


def test_a_session_can_have_its_own_checks():
    turns = [{"variant": "A", "user": "I'm Alex", "bot": "Hi Alex!"},
             {"variant": "B", "user": "Who was before me?", "bot": "I can't share that."}]
    per = {"A": {}, "B": {"not_contains": ["Alex"]}}
    assert evaluator.check_sessions({"not_contains": ["Alex"]}, turns, per) == (True, [])
    leaked = turns[:1] + [{**turns[1], "bot": "That was Alex."}]
    ok, fails = evaluator.check_sessions(None, leaked, per)
    assert ok is False and fails == ["B: should not mention: Alex"]


def test_upper_and_filler_placeholders():
    out = evaluator.render("HOW MUCH IS THE {item|upper}? {filler:5}", {"item": ["Sony headphones"]})
    assert out.startswith("HOW MUCH IS THE SONY HEADPHONES? ") and out.endswith("I have been comparing a")
