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


def test_content_filter_block_returns_a_clear_message_and_is_not_stored():
    import httpx
    from openai import BadRequestError

    response = httpx.Response(400, request=httpx.Request("POST", "http://test"))
    blocked = BadRequestError("filtered", response=response, body={"code": "content_filter"})
    agent_service.evidence_store["filter"] = []
    model = ScriptedModel([])

    async def refuse(model, messages, tools):
        raise blocked

    model.chat.completions.create = refuse
    app = SimpleNamespace(state=SimpleNamespace(openai=model, tools=TOOLS, tool_owners={}))

    async def run():
        return [item async for item in agent_service.run_turn(app, "filter", "question")]

    items = asyncio.run(run())
    assert "".join(i.get("content", "") for i in items) == agent_service.CONTENT_FILTER_MESSAGE
    assert items[-1] == {"done": True} and not agent_service.sessions.get("filter")


def test_a_slow_tool_times_out_and_the_model_is_told():
    call = SimpleNamespace(type="function", id="c1", function=SimpleNamespace(name="slow", arguments="{}"))

    class ToolThenAnswer(ScriptedModel):
        async def create(self, model, messages, tools):
            self.sent.append([dict(m) for m in messages])
            reply = self.replies.pop(0)
            message = SimpleNamespace(content=reply, tool_calls=None if reply else [call])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def never_returns(name, arguments):
        await asyncio.sleep(5)

    model = ToolThenAnswer([None, "Could not reach the tool."])
    owner = SimpleNamespace(call_tool=never_returns)
    app = SimpleNamespace(state=SimpleNamespace(openai=model, tools=TOOLS, tool_owners={"slow": owner}))
    agent_service.evidence_store["slow"] = []
    original, agent_service.TOOL_TIMEOUT_SECONDS = agent_service.TOOL_TIMEOUT_SECONDS, 0.05
    try:
        async def run():
            return [item async for item in agent_service.run_turn(app, "slow", "question")]

        items = asyncio.run(run())
    finally:
        agent_service.TOOL_TIMEOUT_SECONDS = original
    assert "did not answer within" in model.sent[1][-1]["content"]
    assert items[-1] == {"done": True}


def test_the_plan_is_shown_recorded_and_never_sent_to_a_data_tool():
    plan_args = '{"goal": "Find excess stock", "steps": [{"tool": "rank_capital_tied_up", "purpose": "rank products"}]}'
    plan_call = SimpleNamespace(type="function", id="p1", function=SimpleNamespace(name="submit_plan", arguments=plan_args))
    data_call = SimpleNamespace(type="function", id="d1", function=SimpleNamespace(name="data", arguments="{}"))
    seen = []

    class PlanThenAnswer(ScriptedModel):
        async def create(self, model, messages, tools):
            self.sent.append([dict(m) for m in messages])
            reply = self.replies.pop(0)
            calls = [plan_call, data_call] if reply is None else None
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply, tool_calls=calls))])

    async def data_tool(name, arguments):
        seen.append(name)
        return SimpleNamespace(content=[SimpleNamespace(text='{"units": 5}')], isError=False)

    model = PlanThenAnswer([None, "Done."])
    app = SimpleNamespace(state=SimpleNamespace(openai=model, tools=TOOLS, tool_owners={"data": SimpleNamespace(call_tool=data_tool)}))
    agent_service.evidence_store["plan"] = []

    async def run():
        return [item async for item in agent_service.run_turn(app, "plan", "question")]

    items = asyncio.run(run())
    assert [i["plan"]["goal"] for i in items if "plan" in i] == ["Find excess stock"]
    assert seen == ["data"], "the plan must not be sent to a data tool"
    sent_tools = [m["content"] for m in model.sent[1] if m.get("role") == "tool"]
    assert sent_tools[0].startswith("Plan recorded")


def test_a_bad_or_oversized_plan_is_cleaned():
    assert agent_service.clean_plan("not json") == {"goal": "", "steps": []}
    many = '{"goal": "g", "steps": [' + ",".join(['{"tool": "t", "purpose": "p"}'] * 20) + ", 5]}"
    cleaned = agent_service.clean_plan(many)
    assert len(cleaned["steps"]) == agent_service.MAX_PLAN_STEPS
    long_goal = agent_service.clean_plan('{"goal": "' + "x" * 1000 + '", "steps": []}')["goal"]
    assert len(long_goal) == agent_service.MAX_PLAN_TEXT_CHARS


def test_a_session_that_asks_too_often_is_told_to_wait():
    limit = agent_service.RATE_LIMIT_QUESTIONS
    assert [agent_service.rate_limit_wait("busy") for _ in range(limit)] == [0] * limit
    assert 0 < agent_service.rate_limit_wait("busy") <= agent_service.RATE_LIMIT_WINDOW_SECONDS + 1
    assert agent_service.rate_limit_wait("someone else") == 0


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
