"""Tests for the chart tool. Run with: python test_charts.py"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

os.environ["CHART_DIR"] = tempfile.mkdtemp()
os.environ["AGENT_LOG_DIR"] = tempfile.mkdtemp()

import charts  # noqa: E402
import agent_service  # noqa: E402

EVIDENCE = ['{"results": [{"store": "Seattle", "units": 2046}, {"store": "Online", "units": 1981}], "pct": 12.3}']


def result(spec) -> str:
    return asyncio.run(agent_service.make_chart_result(json.dumps(spec), EVIDENCE, "question"))


def test_a_valid_bar_chart_is_drawn_and_returns_a_markdown_image():
    out = result({"kind": "bar", "title": "Units", "labels": ["Seattle", "Online"], "values": [2046, 1981]})
    assert out.startswith("Chart created") and "![Units](/charts/c" in out
    name = out.split("/charts/")[1].rstrip(")")
    assert charts.valid_chart_name(name) and (charts.CHART_DIR / name).stat().st_size > 1000


def test_values_that_no_tool_returned_are_refused_and_nothing_is_drawn():
    before = set(charts.CHART_DIR.glob("*.png"))
    out = result({"kind": "bar", "title": "Units", "labels": ["A", "B"], "values": [2046, 9999]})
    assert out.startswith("Tool error") and "9999" in out
    assert set(charts.CHART_DIR.glob("*.png")) == before


def test_bad_requests_get_a_plain_reason():
    assert "kind" in result({"kind": "pie", "title": "x", "values": [1]})
    assert "title" in result({"kind": "bar", "title": "", "labels": ["a"], "values": [1]})
    assert "labels" in result({"kind": "bar", "title": "t", "labels": ["a"], "values": [2046, 1981]})
    assert "numbers" in result({"kind": "bar", "title": "t", "labels": ["a"], "values": ["x"]})
    assert "at most" in result({"kind": "bar", "title": "t", "labels": ["a"] * 41, "values": [2046] * 41})
    assert "JSON" in asyncio.run(agent_service.make_chart_result("not json", EVIDENCE, ""))


def test_a_histogram_takes_raw_values_that_were_returned():
    evidence = ["daily units: 12, 15, 15, 18, 22, 22, 22, 30"]
    spec = {"kind": "histogram", "title": "Daily units", "values": [12, 15, 15, 18, 22, 22, 22, 30], "bins": 4}
    assert asyncio.run(agent_service.make_chart_result(json.dumps(spec), evidence, "")).startswith("Chart created")


def test_a_dollar_sign_in_a_title_does_not_break_the_chart():
    out = result({"kind": "bar", "title": "Cost $ and $ more", "labels": ["Seattle"], "values": [2046]})
    assert out.startswith("Chart created")


def test_only_the_random_name_pattern_is_servable():
    assert charts.valid_chart_name("c" + "0" * 20 + ".png")
    for bad in ("../secret.png", "c123.png", "c" + "0" * 20 + ".jpg", "", "c" + "g" * 20 + ".png"):
        assert not charts.valid_chart_name(bad), bad


def test_the_chart_line_does_not_trip_the_answer_check():
    from answer_verifier import verify_answer

    out = result({"kind": "bar", "title": "Units by store", "labels": ["Seattle", "Online"], "values": [2046, 1981]})
    line = out.split("exactly this line in your answer: ")[1]
    answer = f"Scope: all 8 stores\nSeattle sold 2046 units.\n{line}"
    assert verify_answer(answer, EVIDENCE + ["question"]).problems == []


def test_a_closing_question_or_offer_after_using_tools_is_caught():
    assert agent_service.closing_question("Scope: x\n\nBody.\n\nWhich should I do next?", True)
    assert agent_service.closing_question("Body.\n\nDraft next steps (pick one and I'll run it):\n- a\n- b", True)
    assert agent_service.closing_question("Body.\n\nIf you want, I can also draw a chart.", True)


def test_a_plain_recommendation_or_a_no_tool_redirect_is_not_caught():
    assert not agent_service.closing_question("Body.\n\nRecommendation: hold orders for these three products.", True)
    assert not agent_service.closing_question("That is outside what I do. Would you like an inventory question?", False)


def test_a_short_closing_offer_is_dropped_but_figures_in_it_are_kept():
    drop = agent_service.without_closing_offer("Scope: x\n\nSeattle sold 10 units.\n\nWould you like a chart?", True)
    assert drop == "Scope: x\n\nSeattle sold 10 units."
    options = agent_service.without_closing_offer("Body.\n\nDraft next steps (pick one and I'll run it):\n- a\n- b", True)
    assert options == "Body."
    figures = "Body.\n\nIf you want, order 500 units for 2000 dollars."
    assert agent_service.without_closing_offer(figures, True) == figures
    offer = "Body 424 rows.\n\nIf you want an export of all 424 products I can produce a CSV; say export all."
    assert agent_service.without_closing_offer(offer, True) == "Body 424 rows."
    assert agent_service.without_closing_offer("Would you like help?", True) == "Would you like help?"


def test_a_download_link_next_to_a_closing_offer_is_kept():
    answer = "Scope: x\n\nSummary.\n\n[Download list (CSV, 40 rows)](/exports/e0123456789abcdef012.csv)\nIf you want all 424 rows, I can export them."
    out = agent_service.without_closing_offer(answer, True)
    assert "](/exports/e0123456789abcdef012.csv)" in out and "If you want" not in out
    listed = "Body.\n\n1. Hold orders.\n2. Check seasonal peak.\n3. If you want, I can export the 424 products to CSV."
    assert agent_service.without_closing_offer(listed, True).endswith("2. Check seasonal peak.")


def test_a_store_user_asking_about_another_store_must_be_told_it_is_not_visible():
    from access import STORE_RLS_IDS

    kirkland = STORE_RLS_IDS["Zava Retail Kirkland"]
    ask = "How many units did the Seattle store sell in 2023?"
    assert agent_service.scope_problem(ask, kirkland, "Scope: Kirkland\nKirkland sold 1,171 units.")
    assert not agent_service.scope_problem(ask, kirkland, "I cannot see Seattle; I can see only Kirkland. Kirkland sold 1,171 units.")
    assert not agent_service.scope_problem("How is Kirkland doing?", kirkland, "Kirkland sold 1,171 units.")
    assert not agent_service.scope_problem(ask, agent_service.GLOBAL_RLS_ID, "Seattle sold 5 units.")


def test_a_closing_i_can_bullet_with_figures_is_dropped():
    answer = "Body 424 rows.\n\nIf you want:\n- I can list the next 10 products (rows 11-20) or export the full 424-row list to CSV."
    assert agent_service.without_closing_offer(answer, True) == "Body 424 rows."


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
