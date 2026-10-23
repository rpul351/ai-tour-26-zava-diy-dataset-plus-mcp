"""Tests for the /charts route. Run with: python test_charts_route.py"""

import json
import os
import tempfile
from pathlib import Path

os.environ["CHART_DIR"] = tempfile.mkdtemp()
os.environ["EXPORT_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient

import temp_access

import roles  # noqa: E402

_access = Path(tempfile.mkdtemp()) / "access_list.json"
_access.write_text(json.dumps({"users": {"alice": {"role": "super_manager"}, "kim": {"role": "store_manager", "store": "Zava Retail Kirkland"}}}), encoding="utf-8")
roles.ACCESS_LIST_FILE = _access

temp_access.CODES_FILE = Path(tempfile.mkdtemp()) / "codes.json"
temp_access.CODES_FILE.write_text(json.dumps({"codes": {"good-code-1": "alice"}}), encoding="utf-8")

import web_app  # noqa: E402
from charts import CHART_DIR  # noqa: E402
from exports import EXPORT_DIR  # noqa: E402

NAME = "c" + "a1" * 10 + ".png"
(CHART_DIR / NAME).write_bytes(b"\x89PNG\r\n\x1a\nfake")
CSV = "e" + "b2" * 10 + ".csv"
(EXPORT_DIR / CSV).write_text("Store,Units\nSeattle,2046\n", encoding="utf-8")


def signed_in_client() -> TestClient:
    client = TestClient(web_app.app, follow_redirects=False)
    temp_access._failures.clear()
    client.post("/temp-login", data={"code": "good-code-1", "role": "super_manager"})
    return client


def test_a_signed_in_person_gets_the_chart_image():
    r = signed_in_client().get(f"/charts/{NAME}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_a_visitor_who_is_not_signed_in_does_not_get_the_chart():
    temp_access._failures.clear()
    r = TestClient(web_app.app, follow_redirects=False).get(f"/charts/{NAME}")
    assert r.status_code in (302, 303, 401) and r.content != (CHART_DIR / NAME).read_bytes()


def test_other_names_and_paths_are_not_served():
    client = signed_in_client()
    (CHART_DIR.parent / "secret.png").write_bytes(b"x")
    for bad in ("..%2Fsecret.png", "secret.png", "c" + "0" * 20 + ".png", "c" + "a1" * 10 + ".jpg"):
        assert client.get(f"/charts/{bad}").status_code == 404, bad


def test_a_signed_in_person_can_download_an_export_as_an_attachment():
    r = signed_in_client().get(f"/exports/{CSV}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.text.startswith("Store,Units")


def test_exports_need_a_login_and_only_valid_names_are_served():
    temp_access._failures.clear()
    anon = TestClient(web_app.app, follow_redirects=False).get(f"/exports/{CSV}")
    assert anon.status_code in (302, 303, 401) and "Seattle" not in anon.text
    client = signed_in_client()
    (EXPORT_DIR.parent / "secret.csv").write_text("x", encoding="utf-8")
    for bad in ("..%2Fsecret.csv", "secret.csv", "e" + "0" * 20 + ".csv", "e" + "b2" * 10 + ".txt"):
        assert client.get(f"/exports/{bad}").status_code == 404, bad


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
