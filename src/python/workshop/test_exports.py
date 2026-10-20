"""Tests for the CSV and PDF export tool. Run with: python test_exports.py"""

import asyncio
import csv
import json
import os
import tempfile

os.environ["EXPORT_DIR"] = tempfile.mkdtemp()
os.environ["CHART_DIR"] = tempfile.mkdtemp()
os.environ["AGENT_LOG_DIR"] = tempfile.mkdtemp()

import agent_service  # noqa: E402
import exports  # noqa: E402

EVIDENCE = ['{"results": [{"store": "Seattle", "units": 2046, "rev": 1726491.36}, {"store": "Online", "units": 1981, "rev": 1728682.32}]}']
SPEC = {"format": "csv", "title": "Units by store", "columns": ["Store", "Units"], "rows": [["Seattle", 2046], ["Online", 1981]]}


def run(spec) -> str:
    return asyncio.run(agent_service.make_export_result(json.dumps(spec), EVIDENCE, "question"))


def name_of(out: str) -> str:
    return out.split("/exports/")[1].rstrip(")")


def test_a_csv_is_written_with_the_returned_figures_and_a_download_link():
    out = run(SPEC)
    assert out.startswith("File created") and "[Download Units by store (CSV, 2 rows)](/exports/e" in out
    name = name_of(out)
    assert exports.valid_export_name(name)
    rows = list(csv.reader(open(exports.EXPORT_DIR / name, encoding="utf-8-sig")))
    assert rows == [["Store", "Units"], ["Seattle", "2046"], ["Online", "1981"]]


def test_a_pdf_is_written_across_pages():
    many = {"format": "pdf", "title": "Stores", "note": "Scope: all 8 stores", "columns": ["Store", "Units"], "rows": [["Seattle", 2046]] * 60}
    name = name_of(run(many))
    data = (exports.EXPORT_DIR / name).read_bytes()
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 3


def test_numbers_no_tool_returned_are_refused_and_no_file_is_written():
    before = set(exports.EXPORT_DIR.iterdir())
    out = run({**SPEC, "rows": [["Seattle", 2046], ["Online", 9999]]})
    assert out.startswith("Tool error") and "9999" in out
    assert set(exports.EXPORT_DIR.iterdir()) == before


def test_text_that_starts_like_a_formula_is_neutralised_but_negative_numbers_stay():
    name = name_of(run({**SPEC, "rows": [["=HYPERLINK(\"http://x\")", 2046], ["-cmd", 1981], ["@x", 2046]]}))
    rows = list(csv.reader(open(exports.EXPORT_DIR / name, encoding="utf-8-sig")))
    assert [r[0][0] for r in rows[1:]] == ["'", "'", "'"]
    assert exports.validate({**SPEC, "rows": [["a", -5]]})[0]["rows"][0][1] == -5


def test_bad_requests_get_a_plain_reason():
    assert "format" in run({**SPEC, "format": "xlsx"})
    assert "title" in run({**SPEC, "title": ""})
    assert "columns" in run({**SPEC, "columns": []})
    assert "exactly 2 cells" in run({**SPEC, "rows": [["Seattle"]]})
    assert "text, numbers or null" in run({**SPEC, "rows": [["Seattle", {"a": 1}]]})
    assert "at most" in run({**SPEC, "rows": [["Seattle", 2046]] * 1001})
    assert "JSON" in asyncio.run(agent_service.make_export_result("nope", EVIDENCE, ""))


def test_only_the_random_name_pattern_is_servable():
    assert exports.valid_export_name("e" + "0" * 20 + ".csv") and exports.valid_export_name("e" + "a" * 20 + ".pdf")
    for bad in ("../x.csv", "e123.csv", "e" + "0" * 20 + ".png", "e" + "0" * 20 + ".csv.exe", "", "e" + "g" * 20 + ".csv"):
        assert not exports.valid_export_name(bad), bad


def test_the_download_line_does_not_trip_the_answer_check():
    from answer_verifier import verify_answer

    line = run(SPEC).split("exactly this line in your answer: ")[1]
    assert verify_answer(f"Scope: all 8 stores\nSeattle sold 2046 units.\n{line}", EVIDENCE + ["question"]).problems == []


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
