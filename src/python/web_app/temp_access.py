"""TEMPORARY access-code login for local team testing.

REMOVE BEFORE DEPLOYING TO AZURE. To remove it:
  1. delete this file and temp_access_codes.json
  2. delete the two lines in web_app.py marked "TEMP ACCESS"
In Azure, the signed-in user comes from the platform sign-in instead, and the same access list
(src/python/workshop/access_list.json) decides who sees what.

Each tester gets a code. The code names a person on the access list. Signing in sets a signed cookie, and
the web app tells the agent service who is asking. The agent service, not this file, picks the identity.

Make codes:  python temp_access.py generate teammate-one teammate-two
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from html import escape
from pathlib import Path

import roles
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

CODES_FILE = Path(__file__).with_name("temp_access_codes.json")
COOKIE = "zava_temp_user"
COOKIE_HOURS = 8
OPEN_PATHS = {"/temp-login", "/logout", "/health", "/favicon.ico", "/static/styles.css"}
LOGIN_PAGE = Path(__file__).resolve().parents[2] / "shared" / "static" / "login.html"
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 600

# A fresh secret each start means a restart signs everyone out. Set TEMP_ACCESS_SECRET to keep sessions.
_SECRET = (os.getenv("TEMP_ACCESS_SECRET") or secrets.token_hex(32)).encode()
_failures: dict[str, list[float]] = {}


def _load_codes() -> dict[str, str]:
    return json.loads(CODES_FILE.read_text(encoding="utf-8"))["codes"]


def _sign(user: str, expires: int) -> str:
    return hmac.new(_SECRET, f"{user}|{expires}".encode(), hashlib.sha256).hexdigest()


def _make_cookie(user: str) -> str:
    expires = int(time.time()) + COOKIE_HOURS * 3600
    return f"{user}|{expires}|{_sign(user, expires)}"


def _user_from_cookie(value: str | None) -> str | None:
    try:
        user, expires, signature = (value or "").rsplit("|", 2)
        if int(expires) < time.time() or not hmac.compare_digest(signature, _sign(user, int(expires))):
            return None
        return user
    except ValueError:
        return None


def _throttled(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW_SECONDS]
    _failures[ip] = recent
    return len(recent) >= MAX_FAILURES


def _page(message: str = "", role: str = "") -> HTMLResponse:
    """The sign-in screen. A wrong code keeps the chosen role so the person only retypes the code."""
    role = role if role in roles.ROLE_LABELS else ""
    html = LOGIN_PAGE.read_text(encoding="utf-8")
    html = html.replace("{{ROLE}}", role).replace("{{ERROR}}", escape(message) if role else "").replace("{{ROLE_ERROR}}", "" if role else escape(message))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def install_temp_access(app: FastAPI) -> None:
    """Require a valid code cookie for every page except the login page and /health."""
    if not CODES_FILE.exists():
        raise SystemExit(f"No access codes found. Run: python {Path(__file__).name} generate <name> ...")

    @app.middleware("http")
    async def require_code(request: Request, call_next):
        request.state.zava_user = _user_from_cookie(request.cookies.get(COOKIE))
        if request.url.path in OPEN_PATHS or request.state.zava_user:
            return await call_next(request)
        if request.url.path.startswith(("/chat/", "/api/")) or request.method != "GET":
            return JSONResponse({"error": "Sign in with an access code first."}, status_code=401)
        return RedirectResponse("/temp-login", status_code=303)

    @app.get("/temp-login", response_class=HTMLResponse)
    async def login_form() -> HTMLResponse:
        return _page()

    @app.post("/temp-login")
    async def login(request: Request, code: str = Form(""), role: str = Form("")) -> Response:
        ip = request.client.host if request.client else "unknown"
        if _throttled(ip):
            return _page("Too many wrong codes. Try again in a few minutes.", role)
        if role not in roles.ROLE_LABELS:
            return _page("Choose Store Manager or Super Manager first.")
        user = _load_codes().get(code.strip())
        if user is None:
            _failures.setdefault(ip, []).append(time.time())
            return _page("That code is not valid.", role)
        person = roles.describe(user)
        if person is None:
            return _page("That code is not set up for the agent. Ask the team lead.", role)
        if person["role"] != role:
            _failures.setdefault(ip, []).append(time.time())
            return _page(f"That code is not for a {roles.ROLE_LABELS[role]}. Check the role you chose.", role)
        response = RedirectResponse("/", status_code=303)
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(
            COOKIE, _make_cookie(user), max_age=COOKIE_HOURS * 3600, httponly=True, samesite="lax", secure=secure
        )
        return response

    @app.post("/logout")
    async def logout() -> Response:
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response


def generate(names: list[str]) -> None:
    codes = {secrets.token_urlsafe(9): name.strip().lower() for name in names}
    CODES_FILE.write_text(json.dumps({"codes": codes}, indent=2), encoding="utf-8")
    print(f"Wrote {CODES_FILE.name}. Give each person only their own code:\n")
    for code, name in codes.items():
        print(f"  {name:<24} {code}")
    print("\nEach name must also be on the agent's access list (access_list.json).")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "generate":
        generate(sys.argv[2:])
    else:
        print(__doc__)
