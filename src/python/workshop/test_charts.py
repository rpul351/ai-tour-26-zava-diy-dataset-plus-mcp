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


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
