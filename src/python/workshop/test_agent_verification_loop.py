"""Tests for the verify-then-revise loop in run_turn. Run with: python test_agent_verification_loop.py"""

import asyncio
import os
import tempfile
from types import SimpleNamespace

os.environ["AGENT_LOG_DIR"] = tempfile.mkdtemp()  # keep test turns out of the real call log

import agent_service  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "noop", "description": "", "parameters": {}}}]


class ScriptedModel:
    """Stands in for the chat model and replays fixed replies, recording what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, model, messages, tools):
        self.sent.append([dict(m) for m in messages])
        message = SimpleNamespace(content=self.replies.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def ask(replies, session_id, evidence=None):
    agent_service.evidence_store[session_id] = list(evidence or [])
    model = ScriptedModel(replies)
    app = SimpleNamespace(state=SimpleNamespace(openai=model, tools=TOOLS, tool_owners={}))

    async def run():
        return [item async for item in agent_service.run_turn(app, session_id, "question")]

    items = asyncio.run(run())
    text = "".join(i.get("content", "") for i in items)
    return text, model, items


def test_clean_answer_is_delivered_without_revision():
    text, model, items = ask(["No figures here."], "clean")
    assert text == "No figures here."
    assert len(model.sent) == 1 and items[-1] == {"done": True}


def test_fabricated_figure_triggers_a_revision_that_fixes_it():
    text, model, _ = ask(["Scope: x\nRevenue was 7,000,000.", "I could not find a revenue figure."], "fix")
    assert text == "I could not find a revenue figure."
    assert len(model.sent) == 2
    request = model.sent[1][-1]["content"]
    assert "7,000,000" in request and "Rewrite the answer" in request


def test_unfixed_answer_is_delivered_with_a_visible_warning_after_two_revisions():
    bad = "Scope: x\nRevenue was 7,000,000."
    text, model, _ = ask([bad, bad, bad], "stuck")
    assert len(model.sent) == 3
    assert "Verification note" in text and "7,000,000" in text


def test_figure_found_in_an_earlier_tool_result_is_accepted():
    text, model, _ = ask(["Scope: x\nUnits were 90,308."], "evidence", evidence=['{"scope": 1, "units": 90308}'])
    assert "Verification note" not in text and len(model.sent) == 1


def test_revision_history_is_not_stored_in_the_session():
    ask(["Scope: x\nRevenue was 7,000,000.", "Nothing to report."], "history")
    stored = agent_service.sessions["history"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[-1]["content"] == "Nothing to report."


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
