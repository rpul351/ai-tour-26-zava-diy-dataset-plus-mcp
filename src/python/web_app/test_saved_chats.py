"""Tests for saved chats: each chat belongs to one signed-in person. Run with: python test_saved_chats.py"""

import json
import os
import tempfile
from pathlib import Path

os.environ["CHAT_DB"] = str(Path(tempfile.mkdtemp()) / "chats.sqlite3")
os.environ["CHART_DIR"] = tempfile.mkdtemp()
os.environ["EXPORT_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient

import chat_store
import roles
import temp_access

temp_access.CODES_FILE = Path(tempfile.mkdtemp()) / "codes.json"
temp_access.CODES_FILE.write_text(json.dumps({"codes": {"alice-code": "alice", "kim-code": "kim"}}), encoding="utf-8")
_access = Path(tempfile.mkdtemp()) / "access_list.json"
_access.write_text(json.dumps({"users": {"alice": {"role": "super_manager"}, "kim": {"role": "store_manager", "store": "Zava Retail Kirkland"}}}), encoding="utf-8")
roles.ACCESS_LIST_FILE = _access

import web_app  # noqa: E402

A, B = "a" * 8 + "-1111", "b" * 8 + "-2222"


def fresh_store():
    chat_store.DB_PATH = Path(tempfile.mkdtemp()) / "chats.sqlite3"


def sign_in(code: str, role: str) -> TestClient:
    client = TestClient(web_app.app, follow_redirects=False)
    temp_access._failures.clear()
    assert client.post("/temp-login", data={"code": code, "role": role}).status_code == 303
    return client


def test_a_chat_is_titled_from_the_first_question_and_keeps_its_messages_in_order():
    fresh_store()
    assert chat_store.ensure_chat("alice", A)
    assert chat_store.add_message("alice", A, "user", "Which products have more than 5 years of stock?")
    assert chat_store.add_message("alice", A, "assistant", "**424 products** have more than five years of stock.")
    chat = chat_store.get_chat("alice", A)
    assert chat["title"] == "Which products have more than 5 years of stock?"
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert [c["id"] for c in chat_store.list_chats("alice")] == [A]
    long = "x" * 200
    chat_store.ensure_chat("alice", B)
    chat_store.add_message("alice", B, "user", long)
    assert len(chat_store.get_chat("alice", B)["title"]) <= chat_store.TITLE_CHARS


def test_one_person_can_never_see_use_search_or_delete_another_persons_chat():
    fresh_store()
    chat_store.ensure_chat("alice", A)
    chat_store.add_message("alice", A, "user", "secret super manager question about Seattle")
    assert chat_store.list_chats("kim") == [] and chat_store.list_chats("kim", "secret") == []
    assert chat_store.get_chat("kim", A) is None
    assert chat_store.ensure_chat("kim", A) is False  # a guessed id cannot be claimed or written to
    assert chat_store.add_message("kim", A, "user", "injected") is False
    assert chat_store.recent_messages("kim", A) == []
    assert chat_store.delete_chat("kim", A) is False
    chat = chat_store.get_chat("alice", A)
    assert len(chat["messages"]) == 1 and chat["messages"][0]["content"].startswith("secret")


def test_search_finds_titles_and_message_text_with_a_snippet_and_treats_wildcards_literally():
    fresh_store()
    chat_store.ensure_chat("kim", A)
    chat_store.add_message("kim", A, "user", "stock of sku ending 001")
    chat_store.add_message("kim", A, "assistant", "There are 45 products. The **Garden Hose 50-foot** holds 7159 units in total.")
    chat_store.ensure_chat("kim", B)
    chat_store.add_message("kim", B, "user", "weekly seasonal pattern")
    assert [c["id"] for c in chat_store.list_chats("kim", "garden hose")] == [A]  # in an answer, not the title
    hit = chat_store.list_chats("kim", "GARDEN HOSE")[0]
    assert "Garden Hose" in hit["snippet"] and "**" not in hit["snippet"]
    assert [c["id"] for c in chat_store.list_chats("kim", "seasonal")] == [B]
    assert chat_store.list_chats("kim", "nothing like this") == []
    assert chat_store.list_chats("kim", "%") == [] and chat_store.list_chats("kim", "_") == []  # not wildcards
    assert len(chat_store.list_chats("kim", "")) == 2


def test_the_agent_gets_the_last_messages_back_in_order_and_at_a_size_it_accepts():
    fresh_store()
    chat_store.ensure_chat("alice", A)
    for i in range(20):
        chat_store.add_message("alice", A, "user" if i % 2 == 0 else "assistant", f"message {i}")
    chat_store.add_message("alice", A, "assistant", "y" * 19000)
    recent = chat_store.recent_messages("alice", A, limit=5)
    assert len(recent) == 5 and len(recent[-1]["content"]) == 12000
    assert [m["content"] for m in recent[:4]] == ["message 16", "message 17", "message 18", "message 19"]


def test_old_chats_beyond_the_limit_are_dropped_and_only_for_that_person():
    fresh_store()
    old_limit = chat_store.MAX_CHATS_PER_USER
    chat_store.MAX_CHATS_PER_USER = 3
    try:
        for i in range(5):
            cid = f"chat-{i}"
            chat_store.ensure_chat("alice", cid)
            chat_store.add_message("alice", cid, "user", f"q{i}")
        chat_store.ensure_chat("kim", "kim-1")
        chat_store.add_message("kim", "kim-1", "user", "kims question")
        kept = [c["id"] for c in chat_store.list_chats("alice")]
        assert len(kept) == 3 and "chat-4" in kept and "chat-0" not in kept  # the newest are kept
        assert len(chat_store.list_chats("kim")) == 1
    finally:
        chat_store.MAX_CHATS_PER_USER = old_limit


def test_the_api_shows_each_signed_in_person_only_their_own_chats():
    fresh_store()
    chat_store.ensure_chat("alice", A)
    chat_store.add_message("alice", A, "user", "alice question")
    chat_store.add_message("alice", A, "assistant", "alice answer about hammers")
    alice, kim = sign_in("alice-code", "super_manager"), sign_in("kim-code", "store_manager")
    listed = alice.get("/api/chats")
    assert listed.status_code == 200 and [c["id"] for c in listed.json()["chats"]] == [A]
    assert listed.headers["cache-control"] == "no-store"
    assert kim.get("/api/chats").json()["chats"] == []
    assert [c["id"] for c in alice.get("/api/chats", params={"q": "hammers"}).json()["chats"]] == [A]
    assert kim.get("/api/chats", params={"q": "hammers"}).json()["chats"] == []
    assert alice.get(f"/api/chats/{A}").json()["messages"][1]["content"] == "alice answer about hammers"
    assert kim.get(f"/api/chats/{A}").status_code == 404
    assert kim.delete(f"/api/chats/{A}").status_code == 404
    assert alice.get(f"/api/chats/{A}").status_code == 200  # kim's attempt changed nothing
    assert alice.get("/api/chats/not%20valid!").status_code == 404
    assert alice.delete(f"/api/chats/{A}").status_code == 200 and alice.get(f"/api/chats/{A}").status_code == 404


def test_the_api_needs_a_sign_in_and_reports_who_and_what_role():
    fresh_store()
    anonymous = TestClient(web_app.app, follow_redirects=False)
    assert anonymous.get("/api/chats").status_code == 401 and anonymous.get("/api/me").status_code == 401
    assert anonymous.delete(f"/api/chats/{A}").status_code == 401
    me = sign_in("kim-code", "store_manager").get("/api/me").json()
    assert (me["role"], me["role_label"], me["store"], me["name"]) == ("store_manager", "Store Manager", "Kirkland", "Kim")
    assert sign_in("alice-code", "super_manager").get("/api/me").json()["sees"] == "all 8 stores"


def test_a_chat_id_that_belongs_to_someone_else_cannot_be_used_to_ask_a_question():
    fresh_store()
    chat_store.ensure_chat("alice", A)
    chat_store.add_message("alice", A, "user", "alice question")
    kim = sign_in("kim-code", "store_manager")
    response = kim.get("/chat/stream", params={"message": "hello there", "session_id": A})
    assert "That chat is not available." in response.text
    assert len(chat_store.get_chat("alice", A)["messages"]) == 1  # nothing was written into alice's chat


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print(f"{len(tests)} passed")
