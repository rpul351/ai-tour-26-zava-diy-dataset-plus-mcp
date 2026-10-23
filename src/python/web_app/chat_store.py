"""Saved chats, one private list per signed-in person.

Every function takes the signed-in user first and filters by it in SQL, so one person can never list, read, search
or delete another person's chats, even by guessing a chat id. The user comes from the sign-in, never from the browser.

The database file lives in logs/ (git-ignored). For Azure, replace this module with a table in a managed database that keeps the same functions.
"""

import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("CHAT_DB") or Path(__file__).resolve().parents[3] / "logs" / "chats.sqlite3")
MAX_CHATS_PER_USER = 200
MAX_MESSAGES_PER_CHAT = 400
MAX_MESSAGE_CHARS = 20000
TITLE_CHARS = 60
CHAT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    user TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_user_updated ON chats (user, updated DESC);
CREATE TABLE IF NOT EXISTS messages (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_chat ON messages (chat_id, n);
"""


@contextmanager
def _connect():
    """A connection that commits when the block ends cleanly, rolls back on an error, and always closes."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()


def _owner(user: str | None) -> str:
    owner = (user or "").strip().lower()
    if not owner:
        raise PermissionError("no signed-in user")
    return owner


def valid_id(chat_id: str) -> bool:
    return bool(CHAT_ID.fullmatch(chat_id or ""))


def _title_from(text: str) -> str:
    one_line = re.sub(r"\s+", " ", text).strip()
    return one_line if len(one_line) <= TITLE_CHARS else one_line[: TITLE_CHARS - 1].rstrip() + "\u2026"


def ensure_chat(user: str | None, chat_id: str) -> bool:
    """Make sure this person has a chat with this id. False if the id belongs to someone else or is not a valid id."""
    owner = _owner(user)
    if not valid_id(chat_id):
        return False
    now = time.time()
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO chats (id, user, title, created, updated) VALUES (?, ?, '', ?, ?)", (chat_id, owner, now, now))
        row = conn.execute("SELECT user FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if row is None or row["user"] != owner:
            return False
        extra = conn.execute("SELECT id FROM chats WHERE user = ? ORDER BY updated DESC LIMIT -1 OFFSET ?", (owner, MAX_CHATS_PER_USER)).fetchall()
        for old in extra:
            conn.execute("DELETE FROM chats WHERE id = ? AND user = ?", (old["id"], owner))
    return True


def add_message(user: str | None, chat_id: str, role: str, content: str) -> bool:
    owner = _owner(user)
    text = (content or "")[:MAX_MESSAGE_CHARS]
    if not text.strip():
        return False
    now = time.time()
    with _connect() as conn:
        chat = conn.execute("SELECT title FROM chats WHERE id = ? AND user = ?", (chat_id, owner)).fetchone()
        if chat is None:
            return False
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()[0]
        if count >= MAX_MESSAGES_PER_CHAT:
            return False
        conn.execute("INSERT INTO messages (chat_id, role, content, created) VALUES (?, ?, ?, ?)", (chat_id, role, text, now))
        title = chat["title"] or (_title_from(text) if role == "user" else "")
        conn.execute("UPDATE chats SET updated = ?, title = ? WHERE id = ? AND user = ?", (now, title, chat_id, owner))
    return True


def _snippet(text: str, needle: str, width: int = 70) -> str:
    flat = re.sub(r"\s+", " ", re.sub(r"[*_`|#>\-]+", " ", text)).strip()
    at = flat.lower().find(needle.lower())
    if at < 0:
        return flat[: width * 2]
    start = max(0, at - width // 2)
    piece = flat[start : start + width * 2]
    return ("\u2026" if start else "") + piece + ("\u2026" if start + width * 2 < len(flat) else "")


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_chats(user: str | None, query: str = "", limit: int = 100) -> list[dict]:
    """This person's chats, newest first. With a query: chats whose title or any message contains it, with a short snippet."""
    owner = _owner(user)
    needle = (query or "").strip()[:100]
    with _connect() as conn:
        if not needle:
            rows = conn.execute("SELECT id, title, updated FROM chats WHERE user = ? AND title <> '' ORDER BY updated DESC LIMIT ?", (owner, limit)).fetchall()
            return [{"id": r["id"], "title": r["title"], "updated": r["updated"]} for r in rows]
        pattern = _like(needle)
        rows = conn.execute(
            "SELECT c.id, c.title, c.updated, "
            "(SELECT m.content FROM messages m WHERE m.chat_id = c.id AND m.content LIKE ? ESCAPE '\\' ORDER BY m.n LIMIT 1) AS hit "
            "FROM chats c WHERE c.user = ? AND c.title <> '' AND (c.title LIKE ? ESCAPE '\\' OR "
            "EXISTS (SELECT 1 FROM messages m WHERE m.chat_id = c.id AND m.content LIKE ? ESCAPE '\\')) ORDER BY c.updated DESC LIMIT ?",
            (pattern, owner, pattern, pattern, limit),
        ).fetchall()
        return [{"id": r["id"], "title": r["title"], "updated": r["updated"], "snippet": _snippet(r["hit"], needle) if r["hit"] else ""} for r in rows]


def get_chat(user: str | None, chat_id: str) -> dict | None:
    owner = _owner(user)
    with _connect() as conn:
        chat = conn.execute("SELECT id, title, updated FROM chats WHERE id = ? AND user = ?", (chat_id, owner)).fetchone()
        if chat is None:
            return None
        rows = conn.execute("SELECT role, content, created FROM messages WHERE chat_id = ? ORDER BY n", (chat_id,)).fetchall()
    return {"id": chat["id"], "title": chat["title"], "updated": chat["updated"], "messages": [{"role": r["role"], "content": r["content"], "created": r["created"]} for r in rows]}


def recent_messages(user: str | None, chat_id: str, limit: int = 12) -> list[dict]:
    """The last messages of a chat, oldest first, to give the agent its memory back."""
    owner = _owner(user)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM (SELECT m.n, m.role, m.content FROM messages m JOIN chats c ON c.id = m.chat_id WHERE m.chat_id = ? AND c.user = ? ORDER BY m.n DESC LIMIT ?) ORDER BY n",
            (chat_id, owner, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"][:12000]} for r in rows]  # the agent accepts up to 12000 characters per message


def delete_chat(user: str | None, chat_id: str) -> bool:
    owner = _owner(user)
    with _connect() as conn:
        return conn.execute("DELETE FROM chats WHERE id = ? AND user = ?", (chat_id, owner)).rowcount > 0
