"""Tests for the TEMPORARY access-code login. Delete this file together with temp_access.py.

Run with: python test_temp_access.py
"""

import json
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import temp_access

import roles  # noqa: E402

_access = Path(tempfile.mkdtemp()) / "access_list.json"
_access.write_text(json.dumps({"users": {"alice": {"role": "super_manager"}, "kim": {"role": "store_manager", "store": "Zava Retail Kirkland"}}}), encoding="utf-8")
roles.ACCESS_LIST_FILE = _access

temp_access.CODES_FILE = Path(tempfile.mkdtemp()) / "codes.json"
temp_access.CODES_FILE.write_text(json.dumps({"codes": {"good-code-1": "alice", "good-code-2": "kim"}}), encoding="utf-8")


def make_client() -> TestClient:
    app = FastAPI()

    @app.get("/")
    async def home(request: Request):
        return {"user": request.state.zava_user}

    @app.get("/chat/stream")
    async def chat():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    temp_access.install_temp_access(app)
    temp_access._failures.clear()
    return TestClient(app, follow_redirects=False)


def test_a_visitor_without_a_code_is_sent_to_the_login_page():
    client = make_client()
    response = client.get("/")
    assert response.status_code == 303 and response.headers["location"] == "/temp-login"


def test_chat_requests_without_a_code_are_refused_not_redirected():
    client = make_client()
    assert client.get("/chat/stream").status_code == 401
    assert client.post("/upload").status_code == 401


def test_health_and_the_login_page_stay_open():
    client = make_client()
    assert client.get("/health").status_code == 200
    assert client.get("/temp-login").status_code == 200


def test_a_wrong_code_does_not_sign_in():
    client = make_client()
    response = client.post("/temp-login", data={"code": "nope", "role": "super_manager"})
    assert response.status_code == 200 and "not valid" in response.text
    assert client.get("/").status_code == 303


def test_a_right_code_signs_in_as_that_person():
    client = make_client()
    response = client.post("/temp-login", data={"code": "good-code-2", "role": "store_manager"})
    assert response.status_code == 303
    assert client.get("/").json() == {"user": "kim"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_a_forged_or_expired_cookie_is_rejected():
    client = make_client()
    forged = f"alice|{int(time.time()) + 3600}|{'0' * 64}"
    client.cookies.set(temp_access.COOKIE, forged)
    assert client.get("/").status_code == 303
    expired = f"alice|{int(time.time()) - 5}|{temp_access._sign('alice', int(time.time()) - 5)}"
    client.cookies.set(temp_access.COOKIE, expired)
    assert client.get("/").status_code == 303


def test_a_cookie_cannot_be_changed_to_a_different_person():
    client = make_client()
    client.post("/temp-login", data={"code": "good-code-1", "role": "super_manager"})
    value = client.cookies.get(temp_access.COOKIE)
    user, expires, signature = value.rsplit("|", 2)
    client.cookies.set(temp_access.COOKIE, f"kim|{expires}|{signature}")
    assert client.get("/").status_code == 303


def test_repeated_wrong_codes_are_throttled_even_for_a_right_code():
    client = make_client()
    for _ in range(temp_access.MAX_FAILURES):
        client.post("/temp-login", data={"code": "guess", "role": "super_manager"})
    response = client.post("/temp-login", data={"code": "good-code-1", "role": "super_manager"})
    assert "Too many wrong codes" in response.text
    assert client.get("/").status_code == 303


def test_the_sign_in_screen_offers_both_roles_before_asking_for_a_code():
    page = make_client().get("/temp-login").text
    assert "Store Manager" in page and "Super Manager" in page and 'name="code"' in page and 'name="role"' in page


def test_a_code_only_signs_in_for_the_role_it_belongs_to():
    client = make_client()
    wrong = client.post("/temp-login", data={"code": "good-code-2", "role": "super_manager"})  # kim is a store manager
    assert wrong.status_code == 200 and "not for a Super Manager" in wrong.text and "set-cookie" not in wrong.headers
    assert 'data-role="super_manager"' in wrong.text  # the chosen role stays selected, only the code is retyped
    wrong = client.post("/temp-login", data={"code": "good-code-1", "role": "store_manager"})  # alice is a super manager
    assert "not for a Store Manager" in wrong.text and "set-cookie" not in wrong.headers
    right = client.post("/temp-login", data={"code": "good-code-2", "role": "store_manager"})
    assert right.status_code == 303 and "zava_temp_user" in right.headers["set-cookie"]


def test_a_missing_or_made_up_role_never_signs_anyone_in():
    client = make_client()
    for role in ("", "admin", "SUPER_MANAGER"):
        response = client.post("/temp-login", data={"code": "good-code-1", "role": role})
        assert response.status_code == 200 and "set-cookie" not in response.headers and "Choose Store Manager or Super Manager" in response.text


def test_trying_the_wrong_role_with_a_real_code_counts_toward_the_limit():
    client = make_client()
    for _ in range(temp_access.MAX_FAILURES):
        client.post("/temp-login", data={"code": "good-code-1", "role": "store_manager"})
    response = client.post("/temp-login", data={"code": "good-code-1", "role": "super_manager"})
    assert "Too many wrong codes" in response.text and "set-cookie" not in response.headers


def test_signing_out_clears_the_cookie():
    client = make_client()
    client.post("/temp-login", data={"code": "good-code-1", "role": "super_manager"})
    assert client.get("/").status_code == 200
    out = client.post("/logout")
    assert out.status_code == 200 and "zava_temp_user" in out.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/").status_code == 303


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
