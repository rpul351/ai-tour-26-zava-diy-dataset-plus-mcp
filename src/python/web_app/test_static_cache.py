"""Tests that a new page is never served with an old script. Run with: python test_static_cache.py"""

import json
import os
import re
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


def signed_in() -> TestClient:
    client = TestClient(web_app.app, follow_redirects=False)
    temp_access._failures.clear()
    client.post("/temp-login", data={"code": "good-code-1", "role": "super_manager"})
    return client


def test_the_page_is_not_cached_and_every_script_and_style_carries_a_version():
    r = signed_in().get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', r.text)
    assert assets and all(re.search(r"\?v=\d+$", a) for a in assets), assets
    assert any(a.startswith("/static/chat.js") for a in assets)


def test_static_files_must_be_revalidated_so_an_old_script_cannot_linger():
    r = signed_in().get("/static/chat.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("2 passed")
