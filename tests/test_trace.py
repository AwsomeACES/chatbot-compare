"""Gray-box / white-box trace checks (evaluator.check_trace)."""

from evaluator import check_trace, render


def turn(bot="ok", variant=None, **trace):
    t = {"user": "q", "bot": bot, "latency_ms": 1}
    if trace:
        t["trace"] = trace
    if variant:
        t["variant"] = variant
    return t


def test_no_expectations_or_nothing_observable_is_unscored():
    assert check_trace(None, [turn(route="sales_agent")]) is None
    assert check_trace({"route_any": "sales_agent"}, [turn()]) is None  # bot exposes no trace


def test_route_is_gray_box():
    assert check_trace({"route_any": ["sales_agent"]}, [turn(route="sales_agent")]) == \
        {"gray": True, "white": None, "failures": []}
    r = check_trace({"route_any": "resq_agent"}, [turn(route="sales_agent")])
    assert r["gray"] is False and "routed to sales_agent" in r["failures"][0]


def test_route_is_judged_on_the_final_turn():
    turns = [turn(route="GENERAL_QUERY"), turn(route="ORDER_STATUS")]
    assert check_trace({"route_any": "ORDER_STATUS"}, turns)["gray"] is True


def test_escalation():
    assert check_trace({"escalate": True}, [turn(escalated=True)])["gray"] is True
    r = check_trace({"escalate": False}, [turn(escalated=True)])
    assert r["gray"] is False and r["failures"] == ["[gray-box] handed to a human"]


def test_tools_any_counts_calls_on_any_turn():
    turns = [turn(tools=[{"name": "search_products", "input": {"query": "tv"}}]), turn(tools=[])]
    assert check_trace({"tools_any": ["get_product_details", "search_products"]}, turns)["white"] is True
    r = check_trace({"tools_any": ["get_order_status"]}, [turn(tools=[])])
    assert r["white"] is False and "called no tool" in r["failures"][0]


def test_tools_none():
    assert check_trace({"tools_none": ["get_order_status"]}, [turn(tools=[])])["white"] is True
    r = check_trace({"tools_none": ["get_order_status"]},
                    [turn(tools=[{"name": "get_order_status", "input": {"order_id": "ORD10003"}}])])
    assert r["white"] is False


def test_tool_args_are_normalised():
    t = [turn(tools=[{"name": "get_order_status", "input": {"order_id": "ord10002", "phone": "9876543210"}}])]
    assert check_trace({"tool_args": {"order_id": "ORD10002"}}, t)["white"] is True
    r = check_trace({"tool_args": {"order_id": "ORD55555"}}, t)
    assert r["white"] is False and "order_id=ord10002" in r["failures"][0]


def test_context_any_separates_retrieval_from_generation():
    assert check_trace({"context_any": ["47,990"]}, [turn(context='{"price": 47990}')])["white"] is True
    r = check_trace({"context_any": ["149"]}, [turn(context="")])
    assert r["white"] is False and "retrieved nothing" in r["failures"][0]


def test_checks_for_other_profiles_are_skipped():
    # A VoltKart-only key ({tools_order} unfilled) must not count against the teammate's bot.
    expect = render({"route_any": "{route_order}", "tools_any": "{tools_order}"}, {"route_order": "sales_agent"})
    assert check_trace(expect, [turn(route="sales_agent", tools=[])]) == {"gray": True, "white": None, "failures": []}


def test_every_persona_session_is_checked():
    turns = [turn(variant="Woman", escalated=False), turn(variant="Man", escalated=True)]
    r = check_trace({"escalate": False}, turns)
    assert r["gray"] is False and r["failures"] == ["[gray-box] Man: handed to a human"]
