#!/usr/bin/env python3
"""
Zava Inventory Advisor: agent service.

Serves the chat API the web app expects (POST /chat/stream, GET /health) on port 8006.
The model reaches data only through the three Zava MCP servers (sales analysis, customer
sales, semantic search). The service starts them over stdio and sets the Row Level Security
identity they run under; the model cannot change it.

To run: python agent_service.py
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import uvicorn
from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncAzureOpenAI, BadRequestError
from pydantic import BaseModel, Field

import charts
import exports
from access import GLOBAL_RLS_ID, STORE_RLS_IDS, AccessList, describe_viewer, load_access_list, normalise
from prompts import (  # noqa: E402
    CLOSING_QUESTION_PROBLEM,
    CONTENT_FILTER_MESSAGE,
    DECLINE_REPLY,
    EXAMPLE_QUESTIONS,
    GOODBYE_REPLY,
    SCOPE_GATE_PROMPT,
    SYSTEM_PROMPT,
    THANKS_REPLY,
    about_reply,
    build_revision_request as revision_request,
    build_scope_gate_messages,
    build_system_prompt,
    greeting_reply,
)
from answer_verifier import evaluate_arithmetic, missing_from_evidence, verify_answer

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("agent_service")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
MODEL_DEPLOYMENT = os.getenv("GPT_MODEL_DEPLOYMENT_NAME", "gpt-5-mini").strip()
MCP_ROOT = Path(__file__).resolve().parents[1] / "mcp_server"
MCP_SERVERS = {
    "sales_analysis": MCP_ROOT / "sales_analysis" / "sales_analysis.py",
    "customer_sales": MCP_ROOT / "customer_sales" / "customer_sales.py",
    "customer_sales_semantic_search": MCP_ROOT / "customer_sales" / "customer_sales_semantic_search.py",
}
# No default on purpose: a missing identity must fail closed, not fall back to all stores.
RLS_USER_ID = os.getenv("RLS_USER_ID", "").strip()
# When set, each person gets the identity the list gives them and anyone not on it gets nothing.
ACCESS_LIST_FILE = os.getenv("ACCESS_LIST_FILE", "").strip()
ACCESS_LIST: AccessList | None = None
ACCESS_LIST_ERROR = ""
if ACCESS_LIST_FILE:
    try:
        ACCESS_LIST = load_access_list(Path(ACCESS_LIST_FILE))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        ACCESS_LIST_ERROR = f"ACCESS_LIST_FILE could not be used: {type(exc).__name__}: {exc}"
API_VERSION = "2025-04-01-preview"

MAX_TOOL_ROUNDS = 10
MAX_REVISIONS = 2
MAX_EVIDENCE_ITEMS = 40
MAX_TOOL_RESULT_CHARS = 12000
MAX_STORED_MESSAGES = 20
STREAM_CHUNK_CHARS = 40
LOG_DIR = Path(os.getenv("AGENT_LOG_DIR") or Path(__file__).resolve().parents[3] / "logs")
MAX_LOGGED_RESULT_CHARS = 2000
TOOL_TIMEOUT_SECONDS = 60
MCP_START_TIMEOUT_SECONDS = 120
# A normal model call takes under 20 s. A hung call is retried after this long instead of after two minutes.
MODEL_TIMEOUT_SECONDS = int(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
MODEL_MAX_RETRIES = 3
# Lower effort answers faster; the evaluation shows what it costs in accuracy.
REASONING_EFFORT = os.getenv("MODEL_REASONING_EFFORT", "low").strip()
# Off by default. Set RATE_LIMIT_QUESTIONS (for example 30) to allow that many questions per person per window.
RATE_LIMIT_QUESTIONS = int(os.getenv("RATE_LIMIT_QUESTIONS", "0"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "600"))
CHART_TOOL_NAME = "make_chart"
# Handled by this service, not by an MCP server. It draws only figures that data tools already returned.
CHART_TOOL = {
    "type": "function",
    "function": {
        "name": CHART_TOOL_NAME,
        "description": (
            "Draw a chart image from figures your data tools already returned. Every value must appear in a tool result "
            "from this conversation; never estimate or invent values. kind: bar (compare categories or stores), barh "
            "(horizontal bars for long labels), line (change over time) or histogram (how values are spread; give the raw "
            "values and optionally bins). Returns one markdown image line to put in your answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["bar", "barh", "line", "histogram"]},
                "title": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "One label per value. Not needed for a histogram."},
                "values": {"type": "array", "items": {"type": "number"}},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "bins": {"type": "integer", "description": "Histogram only: number of bins, 2 to 30."},
            },
            "required": ["kind", "title", "values"],
        },
    },
}


async def make_chart_result(arguments_text: str, evidence: list[str], message: str) -> str:
    try:
        spec, problem = charts.validate(json.loads(arguments_text or "{}"))
    except json.JSONDecodeError:
        return "Tool error: arguments were not valid JSON."
    if problem:
        return f"Tool error: {problem}"
    missing = missing_from_evidence(spec["values"], [*evidence, message])
    if missing:
        return (
            f"Tool error: these values were not in any data returned so far: {missing[:8]}. "
            "Use only figures your data tools returned, or fetch the data first."
        )
    try:
        name = await asyncio.to_thread(charts.draw, spec)
    except Exception as exc:  # noqa: BLE001 - a failed chart must not stop the answer
        logger.warning("Chart failed: %s", exc)
        return f"Tool error: the chart could not be drawn ({type(exc).__name__}). Answer without it."
    return f"Chart created. Put exactly this line in your answer: ![{spec['title']}](/charts/{name})"


EXPORT_TOOL_NAME = "make_export"
# Handled by this service. It writes only figures that data tools already returned.
EXPORT_TOOL = {
    "type": "function",
    "function": {
        "name": EXPORT_TOOL_NAME,
        "description": (
            "Create a downloadable CSV or PDF file from figures your data tools already returned. Use it when the user asks "
            "for a file, download, export, CSV, Excel or PDF. Every number must appear in a tool result from this "
            "conversation; never estimate or invent values. Include every row you have, up to 1000, not only the top few. "
            "Returns one markdown link line to put in your answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["csv", "pdf"]},
                "title": {"type": "string"},
                "note": {"type": "string", "description": "Optional one-line note, for example the scope and snapshot date."},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Readable column names."},
                "rows": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": ["string", "number", "null"]}},
                    "description": "One list per row, one cell per column. Numbers as numbers.",
                },
            },
            "required": ["format", "title", "columns", "rows"],
        },
    },
}


async def make_export_result(arguments_text: str, evidence: list[str], message: str) -> str:
    try:
        spec, problem = exports.validate(json.loads(arguments_text or "{}"))
    except json.JSONDecodeError:
        return "Tool error: arguments were not valid JSON."
    if problem:
        return f"Tool error: {problem}"
    missing = missing_from_evidence(exports.numbers(spec), [*evidence, message])
    if missing:
        return (
            f"Tool error: these numbers were not in any data returned so far: {missing[:8]}. "
            "Use only figures your data tools returned, or fetch the data first."
        )
    try:
        name = await asyncio.to_thread(exports.write, spec)
    except Exception as exc:  # noqa: BLE001 - a failed export must not stop the answer
        logger.warning("Export failed: %s", exc)
        return f"Tool error: the file could not be created ({type(exc).__name__}). Answer without it."
    label = f"Download {spec['title']} ({spec['format'].upper()}, {len(spec['rows'])} rows)"
    return f"File created. Put exactly this line in your answer: [{label}](/exports/{name})"


CALC_TOOL_NAME = "calculate"
MAX_CALCULATIONS = 100
CONSTANTS = {1, 2, 4, 7, 12, 30, 52, 100, 365, 1000}  # conversion factors; every other operand must come from a tool
# Handled by this service. A model is unreliable at long division, so derived figures are worked out here, exactly.
CALC_TOOL = {
    "type": "function",
    "function": {
        "name": CALC_TOOL_NAME,
        "description": (
            "Work out derived figures exactly: a ratio, difference, sum, product, percentage or per-unit value. Use it for every "
            "figure you derive instead of doing arithmetic yourself. Every number in an expression must already appear in a tool "
            "result in this conversation or in the user's question. Use + - * / and brackets, for example "
            "'1726491.36 / 25349' or '100 * (25349 - 26075) / 26075'. Returns each result rounded to 2 decimals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "calculations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"}, "expression": {"type": "string"}},
                        "required": ["label", "expression"],
                    },
                    "description": f"Up to {MAX_CALCULATIONS} calculations, for example one per row of a table.",
                }
            },
            "required": ["calculations"],
        },
    },
}


def calculate_result(arguments_text: str, evidence: list[str], message: str) -> str:
    try:
        items = json.loads(arguments_text or "{}").get("calculations")
    except (json.JSONDecodeError, AttributeError):
        return "Tool error: arguments were not valid JSON."
    if not isinstance(items, list) or not items or len(items) > MAX_CALCULATIONS:
        return f"Tool error: give 1 to {MAX_CALCULATIONS} calculations."
    rows = []
    for item in items:
        label = str(item.get("label", "")) if isinstance(item, dict) else ""
        expression = item.get("expression") if isinstance(item, dict) else None
        if not isinstance(expression, str) or not expression.strip():
            return "Tool error: every calculation needs an expression."
        try:
            value, operands = evaluate_arithmetic(expression)
        except ZeroDivisionError:
            rows.append({"label": label, "expression": expression, "error": "division by zero"})
            continue
        except (ValueError, SyntaxError):
            return f"Tool error: '{expression[:60]}' is not plain arithmetic. Use numbers, + - * / and brackets."
        missing = missing_from_evidence([x for x in operands if x not in CONSTANTS], [*evidence, message])
        if missing:
            return (
                f"Tool error: these numbers were not in any data returned so far: {missing[:8]}. "
                "Use only figures your data tools returned, or fetch the data first."
            )
        rows.append({"label": label, "expression": expression, "result": f"{value:.2f}"})
    return json.dumps({"calculations": rows, "note": "Results are rounded to 2 decimals. Use them exactly as given."}, indent=1)




# Changes whenever the prompt text changes, so every logged call says which prompt produced it.
PROMPT_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:8]


def record(event: str, session_id: str, **fields: Any) -> None:
    """Append one JSON line to the call log. Logging must never break a chat."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "session": session_id,
            "prompt_version": PROMPT_VERSION,
            "rls_user_id": RLS_USER_ID,
            **fields,
        }
        with (LOG_DIR / "agent_calls.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        logger.warning("Could not write the call log: %s", exc)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="default", max_length=100)
    # The store a manager with several stores is asking about. Checked against the access list, never trusted.
    store: str | None = Field(default=None, max_length=100)
    # Earlier messages of a saved chat. Used only when the agent has no memory of this chat (after a restart or when it is reopened).
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


# Per-session memory keeps only user and final assistant text; raw tool results are discarded.
sessions: dict[str, list[dict[str, str]]] = {}
# Tool results are kept separately so later turns can still be checked against them.
evidence_store: dict[str, list[str]] = {}
# Start times of recent questions per session, used to stop one session flooding the model.
recent_questions: dict[str, deque[float]] = {}


def rate_limit_wait(session_id: str) -> int:
    """Seconds the session must wait before asking again, or 0 if it may ask now."""
    now = time.monotonic()
    if RATE_LIMIT_QUESTIONS <= 0:
        return 0
    times = recent_questions.setdefault(session_id, deque())
    while times and now - times[0] > RATE_LIMIT_WINDOW_SECONDS:
        times.popleft()
    if len(times) >= RATE_LIMIT_QUESTIONS:
        return int(RATE_LIMIT_WINDOW_SECONDS - (now - times[0])) + 1
    times.append(now)
    return 0


async def probe_semantic_search(call) -> str:
    """Ask semantic search for a hammer once at start-up. Vector search over an empty or missing embedding setup returns nothing quietly."""
    try:
        text = await asyncio.wait_for(call({"query_description": "hammer", "max_rows": 1, "similarity_threshold": 20}), 30)
    except Exception as exc:  # noqa: BLE001 - any failure is a health finding
        return f"failed ({type(exc).__name__})"
    if '"product_name"' in text:
        return "ok"
    if text.startswith("Tool error") or "Error:" in text[:80]:
        return "failed: " + text[:120].replace("\n", " ")
    return "returns nothing: check the embedding model deployment (infra/deploy.sh) before the code"


@asynccontextmanager
async def lifespan(app: FastAPI):
    credential = DefaultAzureCredential()
    app.state.credential = credential
    app.state.openai = None
    app.state.tools = []
    app.state.tool_owners = {}
    app.state.server_status = {}
    app.state.pools = {}
    app.state.pool_lock = asyncio.Lock()
    app.state.semantic_status = "not checked (no identity started yet)"
    if AZURE_OPENAI_ENDPOINT:
        token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
        app.state.openai = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version=API_VERSION,
            timeout=MODEL_TIMEOUT_SECONDS,
            max_retries=MODEL_MAX_RETRIES,
        )

    try:
        # A single configured identity starts now. Others start when their first user asks.
        if RLS_USER_ID:
            default = await get_pool(app, RLS_USER_ID)
            app.state.tools, app.state.tool_owners, app.state.server_status = default.tools, default.owners, default.status
            semantic = default.owners.get("semantic_search_products")
            if semantic is not None:
                async def search(arguments: dict) -> str:
                    return tool_result_text(await semantic.call_tool("semantic_search_products", arguments))

                app.state.semantic_status = await probe_semantic_search(search)
            else:
                app.state.semantic_status = "not available (server not connected)"
        yield
    finally:
        for pool in app.state.pools.values():
            pool.stop.set()
        await asyncio.gather(*(p.task for p in app.state.pools.values() if p.task), return_exceptions=True)
        if app.state.openai is not None:
            await app.state.openai.close()
        await credential.close()


async def start_servers(stack: AsyncExitStack, rls_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Start the three MCP servers for one identity. One broken server must not stop the others."""
    tools: list[Any] = []
    owners: dict[str, Any] = {}
    status: dict[str, str] = {}
    for name, script in MCP_SERVERS.items():
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(script), "--stdio", f"--RLS_USER_ID={rls_id}"],
                env=dict(os.environ),
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = (await session.list_tools()).tools
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP server %s failed to start: %s", name, exc)
            status[name] = f"failed: {type(exc).__name__}"
            continue
        added = []
        for tool in listed:
            if tool.name in owners:
                continue  # several servers define get_current_utc_date; keep the first
            owners[tool.name] = session
            tools.append(tool)
            added.append(tool.name)
        status[name] = f"connected ({len(added)} tools)"
    return to_openai_tools(tools), owners, status


class IdentityPool:
    """The MCP servers for one identity. One task opens and closes them, as the stdio client requires."""

    def __init__(self, rls_id: str) -> None:
        self.rls_id = rls_id
        self.tools: list[dict[str, Any]] = []
        self.owners: dict[str, Any] = {}
        self.status: dict[str, str] = {}
        self.ready = asyncio.Event()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None

    async def run(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                self.tools, self.owners, self.status = await start_servers(stack, self.rls_id)
                self.ready.set()
                await self.stop.wait()
        finally:
            self.ready.set()


async def get_pool(app: FastAPI, rls_id: str) -> IdentityPool:
    async with app.state.pool_lock:
        pool = app.state.pools.get(rls_id)
        if pool is None:
            pool = IdentityPool(rls_id)
            pool.task = asyncio.create_task(pool.run())
            app.state.pools[rls_id] = pool
    await asyncio.wait_for(pool.ready.wait(), MCP_START_TIMEOUT_SECONDS)
    return pool


app = FastAPI(title="Zava Inventory Advisor Agent Service", lifespan=lifespan)


def config_problems() -> list[str]:
    problems = []
    if not AZURE_OPENAI_ENDPOINT:
        problems.append("AZURE_OPENAI_ENDPOINT is not set")
    if ACCESS_LIST_ERROR:
        problems.append(ACCESS_LIST_ERROR)
    elif ACCESS_LIST is None and not RLS_USER_ID:
        problems.append("Neither ACCESS_LIST_FILE nor RLS_USER_ID is set (refusing to default to a user)")
    return problems


TOOL_STATUS = {
    "find_products": "Looking up products",
    "get_products_by_name": "Looking up products",
    "semantic_search_products": "Searching the catalogue",
    "product_sales": "Checking sales",
    "recent_order_lines": "Checking the latest orders",
    "rank_capital_tied_up": "Checking excess stock",
    "stock_cover_ranking": "Checking stock cover",
    "compare_store_coverage": "Comparing stores",
    "seasonal_baseline_check": "Checking seasonal patterns",
    "year_over_year_summary": "Comparing years",
    "store_seasonal_alignment": "Comparing store patterns",
    "frequently_bought_together": "Finding products bought together",
    "make_chart": "Drawing the chart",
    "make_export": "Preparing your file",
    "calculate": "Working out the figures",
}


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def to_openai_tools(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools
    ]


def tool_result_text(result: Any) -> str:
    text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
    if result.isError:
        text = f"Tool error: {text}"
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n[Result truncated. Ask for fewer rows or a narrower scope.]"
    return text




OFFER = re.compile(r"(?i)\b(pick one|choose one|would you like|do you want|want me to|should i|if you want|if you['\u2019]d like|tell me which)\b")
ASSISTANT_OFFER = re.compile(r"(?i)\bI (can|could|will|['\u2019]ll)\b")


def closing_question(answer: str, used_tools: bool) -> list[str]:
    """A data answer must not end by handing the work back to the user: report what without_closing_offer would remove."""
    if not used_tools or not answer.strip():
        return []
    lines = [ln for ln in answer.strip().splitlines() if ln.strip()]
    return [CLOSING_QUESTION_PROBLEM] if _strip_offer(answer) != answer.strip() or lines[-1].strip().endswith("?") else []


BROAD_SCOPE = re.compile(r"(?i)\b(all|every|each|other|the other|rest of the)\s+(the\s+)?stores?\b|\bnetwork\b|\bcompany(-wide)?\b|\bnational\b")
CANNOT_SEE = re.compile(r"(?i)\b(cannot|can't|can not|unable|not able|only see|not visible|no access|outside|don't have access)\b")


_NOT_VISIBLE = re.compile(r'"store_count":\s*0\b|is not visible to this user|No store named')
_VISIBLE = re.compile(r'"store_count":\s*[1-9]')


def empty_scope_problem(turn_results: list[str], answer: str) -> list[str]:
    """A tool that said the store was not visible returned zeros that are not sales figures; the answer must not present them as data."""
    last_bad = max((i for i, t in enumerate(turn_results) if _NOT_VISIBLE.search(t)), default=None)
    if last_bad is None:
        return []
    recovered = any(_VISIBLE.search(t) and not _NOT_VISIBLE.search(t) and '"results": []' not in t for t in turn_results[last_bad + 1 :])
    if recovered or CANNOT_SEE.search(answer) or re.search(r"(?i)not visible|no store named", answer):
        return []
    return [
        "A tool reported that no store was visible for that request (a wrong or unknown store), so its zeros and empty rows are not sales figures. "
        "Run the tool again without a store id, or with store_name, and answer from that result; or say plainly that the store could not be found."
    ]


SHOW_ALL_LIMIT = 10


def lookup_problem(turn_results: list[str], answer: str, message: str = "") -> list[str]:
    """A product lookup the tool answered in full must be shown in full: the model otherwise keeps the first 10 or 20 rows of 45.

    A question that only wants a count or a total ("how many", "total") is answered without the list.
    """
    if re.search(r"(?i)\b(how many|total|count|sum)\b", message) and not re.search(r"(?i)\b(sku|skus|list|show|which|each|every)\b", message):
        return []
    skus: list[str] = []
    for raw in turn_results:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("summary"), dict) and "products_returned" in data["summary"]:
            skus = [r["sku"] for r in data.get("results", []) if isinstance(r, dict) and r.get("sku")]
    if len(skus) <= SHOW_ALL_LIMIT or "](/exports/" in answer or "](/charts/" in answer:
        return []
    missing = [s for s in skus if s not in answer]
    if not missing:
        return []
    return [f"The product lookup returned {len(skus)} products and the answer lists only {len(skus) - len(missing)}. Show every returned product in the table, with the same columns, and do not say these are the first few."]


_COMPARISON_WORDS = re.compile(r"(?i)\bcompar|\bvs\.?\b|\bversus\b|\bagainst\b|\bthan\b|\bdiffer|what happened|how did")


def required_facts_problem(message: str, turn_results: list[str], answer: str) -> list[str]:
    """Facts the tool results make mandatory: both totals of a year comparison, and the exact dates a sales window covered."""
    text = answer.replace("**", "")
    flat = text.replace(",", "")
    problems: list[str] = []
    for raw in turn_results:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        totals = data.get("totals")
        if isinstance(totals, dict) and "units_compare" in totals and _COMPARISON_WORDS.search(message):
            missing = [f"{totals[k]:,}" for k in ("units", "units_compare") if isinstance(totals.get(k), (int, float)) and str(int(totals[k])) not in flat]
            if missing:
                problems.append(f"A comparison must write out both totals. The total units {' and '.join(missing)} are missing from the answer; state the units for each year, then the change.")
        window = data.get("window")
        if isinstance(window, dict) and window.get("start") and window.get("end") and isinstance(data.get("results"), list):
            if str(window["start"]) not in text or str(window["end"]) not in text:
                problems.append(f"State the exact dates the figures cover, written as {window['start']} to {window['end']}.")
    return list(dict.fromkeys(problems))


def scope_problem(message: str, identity: str | None, answer: str) -> list[str]:
    """A store user who asks about another store must be told it is not visible, not given their own figure."""
    if identity in (None, GLOBAL_RLS_ID):
        return []
    own = next((name for name, rls in STORE_RLS_IDS.items() if rls == identity), None)
    problems = []
    if BROAD_SCOPE.search(message) and not CANNOT_SEE.search(answer):
        problems.append(
            "The user asked for every store, the network or the company, which this user cannot see. Begin the answer by saying plainly "
            "that you can see only their own store and cannot list or compare the others, then give what you can see for their store."
        )
    for name in STORE_RLS_IDS:
        short = name.replace("Zava Retail ", "")
        if name != own and re.search(rf"(?i)\b{re.escape(short)}\b", message) and not (re.search(rf"(?i)\b{re.escape(short)}\b", answer) and CANNOT_SEE.search(answer)):
            problems.append(
                f"The user asked about {short}, which this user cannot see. Begin the answer by saying plainly that you cannot see {short}, "
                "then give only what you can see for their own store, and do not present their store's figure as the one asked about."
            )
    return problems


_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR = re.compile(r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*$")


def repair_tables(answer: str) -> str:
    """Fix markup slips in tables: alignment markers copied into cells, a missing header separator row and a row missing its closing pipe."""
    lines, out, i = answer.split("\n"), [], 0
    for k in range(1, len(lines)):
        if lines[k].lstrip().startswith("|") and not lines[k].rstrip().endswith("|") and _TABLE_LINE.match(lines[k - 1]):
            lines[k] = lines[k].rstrip() + " |"
    while i < len(lines):
        if not _TABLE_LINE.match(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and _TABLE_LINE.match(lines[j]):
            j += 1
        block = lines[i:j]
        header, rest = block[0], block[1:]
        columns = max(1, len(header.strip().strip("|").split("|")))
        if rest and _SEPARATOR.match(rest[0]):
            separator, rest = rest[0], rest[1:]
        else:
            separator = "|" + "|".join(["---"] * columns) + "|"
        clean = lambda ln: re.sub(r"\s*:?-{3,}:?(?=\s*\|)", "", ln)  # noqa: E731 - "Seattle ---:" becomes "Seattle"
        out += [clean(header), separator, *[clean(r) for r in rest if not _SEPARATOR.match(r)]]
        i = j
    return "\n".join(out)


def without_closing_offer(answer: str, used_tools: bool) -> str:
    """Drop a closing offer, with the options listed under it. Never touches a link, an image or a finding."""
    return _strip_offer(answer) if used_tools else answer


def without_scope_line(answer: str, used_tools: bool) -> str:
    """A Scope line says which stores a data answer covers; with no tool call and no real figures (small counts such as "8 stores" do not count) there is nothing to scope (run 33: "who built you?")."""
    if used_tools:
        return answer
    empty = re.sub(r"(?im)^\W*scope:?\W*(none|n/a|not applicable|no data)\b[^\n]*\n+", "", answer, count=1).strip()
    if empty != answer.strip() and empty:
        return empty  # "Scope: none" says nothing, whatever else the answer holds
    kept = re.sub(r"(?im)^\W*scope:.*\n+", "", answer, count=1).strip()
    return kept if kept and not re.search(r"\d{3,}|\d[\d,]*\.\d|\d%|\$\d", kept) and not re.fullmatch(r"\W*scope:.*", kept, re.IGNORECASE) else answer


_WORKINGS = re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?my calculation[^\n]*(?:\n|$)")
_EMPTY_HEADER = re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?\**(?:notes?|calculations?|workings?)\**[ \t]*:?[ \t]*\**[ \t]*(?=\n[ \t]*\n|\n?\Z)")
_ISO_TIME = re.compile(r"\b(\d{4}-\d\d-\d\d)T\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d)?(?:[ \t]*\(?UTC\)?)?")
_FIELD_NAME = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PROTECTED = re.compile(r"(\]\([^)]*\)|`[^`]*`)")
_LONG_DECIMAL = re.compile(r"(?<![\w.])(-?\d+\.\d{5,})(?![\w])")


def _short_decimal(match: re.Match) -> str:
    value = float(match.group(1))
    return f"{value:.2f}" if abs(value) >= 1 else f"{value:.4f}"
_BOLD_NUMBER = re.compile(r"(?<![\w*.$/:-])(\$?\d+(?:,\d{3})*(?:\.\d+)?%?)(?![\w*:-]|\.\d|,\d)")


_BARE_DOWNLOAD = re.compile(r"(?<![\](\w/])(/exports/e[0-9a-f]{20}\.(?:csv|pdf))")


def tidy_answer(answer: str) -> str:
    """What the reader sees: no workings, raw timestamps or field names. The verified draft is logged; this only changes the display."""
    text = _WORKINGS.sub("", answer)
    text = _BARE_DOWNLOAD.sub(r"[Download](\1)", text)  # the model sometimes writes the link as plain text
    text = _EMPTY_HEADER.sub("", text)
    text = _ISO_TIME.sub(r"\1", text)
    parts = _PROTECTED.split(text)
    text = "".join(p if i % 2 else _LONG_DECIMAL.sub(_short_decimal, _FIELD_NAME.sub(lambda m: m.group(0).replace("_", " "), p)) for i, p in enumerate(parts))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def bold_key_figures(answer: str) -> str:
    """If the model bolded nothing, bold the figures in the opening paragraph so the answer can be scanned. Years and dates stay plain."""
    if "**" in answer:
        return answer
    lines = answer.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.strip() and not re.match(r"\W*scope:", ln, re.IGNORECASE)), None)
    if start is None or lines[start].lstrip().startswith(("|", "-", "*", ">", "#", "!")) or re.match(r"\s*\d+[.)]\s", lines[start]):
        return answer

    def bold(match: re.Match) -> str:
        figure = match.group(1)
        if re.fullmatch(r"(19|20)\d\d", figure):
            return figure
        return f"**{figure}**"

    count = 0
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    paragraph = _PROTECTED.split(" ".join(lines[start:end]))
    out = []
    for i, part in enumerate(paragraph):
        if i % 2 or count >= 4:
            out.append(part)
            continue
        new, n = _BOLD_NUMBER.subn(bold, part, count=4 - count)
        count += n
        out.append(new)
    lines[start:end] = ["".join(out)]
    return "\n".join(lines)


def _strip_offer(answer: str) -> str:

    def is_offer(line: str) -> bool:
        text = line.strip()
        asks = bool(OFFER.search(text)) or text.endswith("?") or bool(re.match(r"[\-*\d.)\s]*I (can|could|will|['\u2019]ll)\b", text))
        return asks and "](/" not in text and len(text) <= 600 and (not re.search(r"\d", text) or bool(ASSISTANT_OFFER.search(text)))

    def is_offer_sentence(sentence: str) -> bool:
        text = sentence.strip()
        if "](/" in text:
            return False
        asks = bool(OFFER.search(text)) or text.endswith("?") or bool(re.match(r"I (can|could|will|['\u2019]ll)\b", text))
        return asks and (not re.search(r"\d", text) or bool(ASSISTANT_OFFER.search(text)))

    def trim_offer_sentences(line: str) -> str:
        """Remove trailing offer sentences from a line. Earlier sentences, which may hold figures, are kept."""
        prefix = re.match(r"\s*(?:[-*]|\d+[.)])?\s*", line).group(0)
        sentences = re.split(r"(?<=[.!?])\s+", line[len(prefix):].strip())
        while sentences and is_offer_sentence(sentences[-1]):
            sentences.pop()
        return prefix + " ".join(sentences) if sentences else ""

    def is_header(line: str) -> bool:
        text = line.strip()
        return (bool(OFFER.search(text)) or bool(ASSISTANT_OFFER.search(text))) and text.endswith((":", "?")) and "](/" not in text

    lines = answer.strip().split("\n")
    for _ in range(4):  # a closing question, then the offer block above it, then a sentence before that
        before = len(lines)
        while len([ln for ln in lines if ln.strip()]) > 1:
            if not lines[-1].strip():
                lines.pop()
                continue
            trimmed = trim_offer_sentences(lines[-1])
            if trimmed == lines[-1]:
                break
            if trimmed:
                lines[-1] = trimmed  # a finding stays; only its offer sentence goes
                break
            lines.pop()
        for i in range(max(0, len(lines) - 14), len(lines)):  # an offer block is short and last
            block = lines[i:]
            if any(ln.strip() for ln in lines[:i]) and is_header(lines[i]) and "](/" not in "\n".join(block) and len("\n".join(block)) <= 900 and all(
                not ln.strip() or re.match(r"\s*([-*]|\d+[.)])\s", ln) for ln in block[1:]
            ):
                lines = lines[:i]
                break
        if len(lines) == before:
            break
    kept = "\n".join(lines).rstrip()
    if not [ln for ln in kept.splitlines() if ln.strip() and not re.match(r"\W*scope:", ln, re.IGNORECASE)]:
        return answer.strip()  # never deliver an answer with nothing but its Scope line
    return kept




_GREETING = re.compile(
    r"(hi|hello|hey|hiya|howdy|yo|greetings|g'?day|kia ora|good (morning|afternoon|evening|day)|hi there|hello there|hey there|hello again|hi again)( (there|team|everyone|all|agent|advisor|bot))?"
)
_THANKS = re.compile(r"(thanks|thank you|thankyou|thx|ty|cheers|ta|much appreciated|thanks a lot|thank you very much)( (so much|a lot|again))?")
_GOODBYE = re.compile(r"(bye|goodbye|good bye|see you|see ya|cya|later|good night)( (now|later|soon))?")
_ABOUT = re.compile(
    r"(who are you|what are you|what is this|what do you do|what can you do|what can i ask( you)?|what can you help (me )?with|how can you help( me)?|help|help me|how do i use this|how does this work|what should i ask|what questions can i ask|introduce yourself|are you there|anyone there)"
)


def canned_reply(message: str, identity: str | None, user: str | None) -> str | None:
    """Answer a message that is only a greeting, thanks, goodbye or a question about the agent itself, with no model call.

    Anything that holds a real question returns None and goes to the model. The wording is fixed, so every person gets the
    same friendly reply, and it names who they are signed in as and what they can see.
    """
    text = re.sub(r"[^\w' ]+", " ", message.lower().replace("\u2019", "'"))
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > 40:
        return None
    signed_in = describe_viewer(identity, user).replace("The person asking is ", "You are signed in as ", 1)
    if _GREETING.fullmatch(text):
        return greeting_reply(signed_in)
    if _ABOUT.fullmatch(text):
        return about_reply(signed_in)
    if _THANKS.fullmatch(text):
        return THANKS_REPLY
    if _GOODBYE.fullmatch(text):
        return GOODBYE_REPLY
    return None


_SELF_TOPIC = re.compile(
    r"\b(chat ?bot|agent|ai|a\.i\.|llm|rag|gpt|chatgpt|model|machine|robot|bot|hallucinat\w*|made up|make up|making up|built|created|made you|trained|"
    r"work|works|limitations?|limits|capabilit\w+|remember|memory|internet|web|browse|your (data|source|sources|tools|prompt|instructions)|"
    r"architecture|pattern|multi.?agent|how are you|are you (real|human|alive|sure|accurate|reliable|safe)|trust|"
    r"export (the |our |this |my )?chat|save (the |our |this |my )?chat|print (the |our |this |my )?chat|copy (the |our |this |my )?chat|download (the |our |this |my )?chat)\b",
    re.IGNORECASE,
)
_DATA_WORDS = re.compile(
    r"\b(stock|stocks|inventory|sale|sales|sold|sell|selling|product|products|store|stores|sku|units?|revenue|order|orders|category|categories|season|seasonal|"
    r"transfer|transfers|capital|excess|price|prices|customer|customers|supplier|\d{4}|january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)


def is_about_you(message: str) -> bool:
    """True for a short message that is clearly about the assistant or the page, not about Zava data.

    It needs a word about the assistant, a pronoun addressed to it, and no word about the data, so "do you have cedar in stock"
    and "how do you rank excess stock" still go to the data tools. These messages are answered without tools.
    """
    text = message.strip()
    if not text or len(text) > 120:
        return False
    lowered = text.lower()
    addressed = bool(re.search(r"\b(you|your|yourself|this (system|tool|page|chat|app|agent|bot)|our chat|the chat)\b", lowered)) or lowered.startswith("is this")
    return addressed and bool(_SELF_TOPIC.search(lowered)) and not _DATA_WORDS.search(lowered)


SCOPE_GATE_ENABLED = os.getenv("SCOPE_GATE", "on").strip().lower() != "off"
SCOPE_GATE_TIMEOUT_SECONDS = 12


# Words only a question about Zava's own business uses. A message with one of them skips the model call.
STRONG_SCOPE = re.compile(
    r"(?i)\b(zava|sku|skus|inventory|super manager|store manager|excess stock|stock cover|months of (stock|cover)|units sold|seasonal (pattern|baseline|index))\b"
)


async def scope_allows(client: Any, message: str, previous: str = "") -> bool:
    """One small model call that says whether the message is about Zava's business. Any problem allows it: the gate must never block real work."""
    if not SCOPE_GATE_ENABLED or STRONG_SCOPE.search(message):
        return True
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=MODEL_DEPLOYMENT,
                messages=build_scope_gate_messages(message, previous),
                reasoning_effort="low",
                max_completion_tokens=300,
            ),
            SCOPE_GATE_TIMEOUT_SECONDS,
        )
        return not (response.choices[0].message.content or "").strip().upper().startswith("OUT")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scope gate failed, allowing the message: %s", exc)
        return True


async def run_turn(
    app: FastAPI, session_id: str, message: str, rls_user_id: str | None = None, user: str | None = None
) -> AsyncGenerator[dict[str, Any], None]:
    client: AsyncAzureOpenAI = app.state.openai
    if rls_user_id is None:
        tools, owners, identity = app.state.tools, app.state.tool_owners, RLS_USER_ID
    else:
        pool = await get_pool(app, rls_user_id)
        tools, owners, identity = pool.tools, pool.owners, rls_user_id
    log = {"user": user, "rls_user_id": identity}
    if not tools:
        yield {"error": "No MCP tools are available. Check /health for the server status."}
        return
    about_you = is_about_you(message)
    greeting = canned_reply(message, identity, user)
    if greeting is not None:
        history = sessions.setdefault(session_id, [])
        history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": greeting}])
        del history[:-MAX_STORED_MESSAGES]
        record("turn", session_id, **log, question=message, answer=greeting, revisions=0, tool_calls=0, ms=0, prompt_tokens=0, completion_tokens=0, unresolved_problems=[], canned=True)
        yield {"content": greeting}
        yield {"done": True}
        return
    tools = [*(t for t in tools if t["function"]["name"] != "get_current_utc_date"), CHART_TOOL, EXPORT_TOOL, CALC_TOOL]  # today's date is in the prompt
    history = sessions.setdefault(session_id, [])
    evidence = evidence_store.setdefault(session_id, [])
    revisions = 0
    turn_started = time.perf_counter()
    tokens = {"prompt": 0, "completion": 0}
    tool_count = 0
    turn_results: list[str] = []
    previous_question = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    gate = None if about_you else asyncio.ensure_future(scope_allows(client, message, previous_question))
    system = {
        "role": "system",
        "content": build_system_prompt(
            today=datetime.now(timezone.utc).date().isoformat(),
            viewer=describe_viewer(identity, user),
            model=MODEL_DEPLOYMENT,
            max_rounds=MAX_TOOL_ROUNDS,
            max_revisions=MAX_REVISIONS,
            memory=MAX_STORED_MESSAGES,
        ),
    }
    working: list[dict[str, Any]] = [system, *history, {"role": "user", "content": message}]

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await client.chat.completions.create(
                model=MODEL_DEPLOYMENT, messages=working, reasoning_effort=REASONING_EFFORT, **({} if about_you else {"tools": tools})
            )
        except BadRequestError as exc:
            if exc.code != "content_filter":
                raise
            record("turn", session_id, question=message, error="content_filter", tool_calls=tool_count, **log)
            yield {"content": CONTENT_FILTER_MESSAGE}
            yield {"done": True}
            return
        usage = getattr(response, "usage", None)
        if usage:
            tokens["prompt"] += usage.prompt_tokens or 0
            tokens["completion"] += usage.completion_tokens or 0
        reply = response.choices[0].message
        calls = [c for c in (reply.tool_calls or []) if c.type == "function"]
        if gate is not None:
            allowed, gate = await gate, None
            if not allowed:
                history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": DECLINE_REPLY}])
                del history[:-MAX_STORED_MESSAGES]
                record("turn", session_id, **log, question=message, answer=DECLINE_REPLY, revisions=0, tool_calls=0, ms=round((time.perf_counter() - turn_started) * 1000),
                       prompt_tokens=tokens["prompt"], completion_tokens=tokens["completion"], unresolved_problems=[], declined=True)
                yield {"content": DECLINE_REPLY}
                yield {"done": True}
                return

        if not calls:
            answer = repair_tables(without_closing_offer(without_scope_line(reply.content or "", tool_count > 0), tool_count > 0))
            problems = verify_answer(answer, [*evidence, message]).problems + scope_problem(message, identity, answer) + empty_scope_problem(turn_results, answer) + lookup_problem(turn_results, answer, message) + required_facts_problem(message, turn_results, answer)
            if problems and revisions < MAX_REVISIONS:
                revisions += 1
                logger.warning("Answer failed verification (revision %d): %s", revisions, problems)
                working.append({"role": "assistant", "content": answer})
                working.append({"role": "user", "content": revision_request(problems)})
                continue
            verified = answer
            answer = bold_key_figures(tidy_answer(answer))
            if problems:
                logger.warning("Answer delivered with unresolved verification problems: %s", problems)
                answer += "\n\nVerification note: this answer could not be fully checked against the data. " + " ".join(problems)
            history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": answer}])
            del history[:-MAX_STORED_MESSAGES]
            record(
                "turn",
                session_id,
                **log,
                question=message,
                answer=answer,
                answer_verified=verified,
                revisions=revisions,
                tool_calls=tool_count,
                ms=round((time.perf_counter() - turn_started) * 1000),
                prompt_tokens=tokens["prompt"],
                completion_tokens=tokens["completion"],
                unresolved_problems=problems,
            )
            for start in range(0, len(answer), STREAM_CHUNK_CHARS):
                yield {"content": answer[start : start + STREAM_CHUNK_CHARS]}
            yield {"done": True}
            return

        working.append(
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in calls
                ],
            }
        )
        yield {"status": TOOL_STATUS.get(calls[0].function.name, "Looking up the data")}

        async def call_data_tool(call: Any, owner: Any) -> tuple[str, Any, int]:
            began = time.perf_counter()
            arguments: Any = call.function.arguments
            try:
                arguments = json.loads(call.function.arguments or "{}")
                text = tool_result_text(await asyncio.wait_for(owner.call_tool(call.function.name, arguments), TOOL_TIMEOUT_SECONDS))
            except json.JSONDecodeError:
                text = "Tool error: arguments were not valid JSON."
            except asyncio.TimeoutError:
                text = f"Tool error: {call.function.name} did not answer within {TOOL_TIMEOUT_SECONDS} seconds."
            return text, arguments, round((time.perf_counter() - began) * 1000)

        service_tools = (CHART_TOOL_NAME, CALC_TOOL_NAME, EXPORT_TOOL_NAME)
        pending = {c.id: asyncio.ensure_future(call_data_tool(c, owners[c.function.name])) for c in calls if c.function.name not in service_tools and owners.get(c.function.name) is not None}
        try:
            for call in calls:
                owner = owners.get(call.function.name)
                arguments: Any = call.function.arguments
                started = time.perf_counter()
                if call.function.name == CHART_TOOL_NAME:
                    text = await make_chart_result(call.function.arguments, evidence, message)
                    try:
                        arguments = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        pass
                elif call.function.name == CALC_TOOL_NAME:
                    text = calculate_result(call.function.arguments, evidence, message)
                    try:
                        arguments = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        pass
                elif call.function.name == EXPORT_TOOL_NAME:
                    text = await make_export_result(call.function.arguments, evidence, message)
                    try:
                        spec_in = json.loads(call.function.arguments or "{}")
                        arguments = {k: spec_in.get(k) for k in ("format", "title")} | {"row_count": len(spec_in.get("rows") or [])}
                    except (json.JSONDecodeError, AttributeError):
                        pass
                elif owner is None:
                    text = f"Tool error: unknown tool {call.function.name}."
                else:
                    text, arguments, data_ms = await pending[call.id]
                elapsed_ms = data_ms if call.id in pending else round((time.perf_counter() - started) * 1000)
                tool_count += 1
                record(
                    "tool_call",
                    session_id,
                    **log,
                    tool=call.function.name,
                    arguments=arguments,
                    result=text[:MAX_LOGGED_RESULT_CHARS],
                    result_chars=len(text),
                    error=text.startswith("Tool error"),
                    ms=elapsed_ms,
                )
                if call.function.name not in (CHART_TOOL_NAME, EXPORT_TOOL_NAME, CALC_TOOL_NAME):
                    turn_results.append(text)
                if call.function.name not in (CHART_TOOL_NAME, EXPORT_TOOL_NAME):
                    evidence.append(text)
                    del evidence[:-MAX_EVIDENCE_ITEMS]
                working.append({"role": "tool", "tool_call_id": call.id, "content": text})
                yield {"tool": {"name": call.function.name, "arguments": arguments, "ms": elapsed_ms}}
        finally:
            for task in pending.values():
                task.cancel()
        yield {"status": "Putting the answer together"}

    record(
        "turn",
        session_id,
        **log,
        question=message,
        error="too many tool calls",
        tool_calls=tool_count,
        ms=round((time.perf_counter() - turn_started) * 1000),
        prompt_tokens=tokens["prompt"],
        completion_tokens=tokens["completion"],
    )
    yield {"error": "Stopped after too many tool calls without an answer. Try a narrower question."}


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, x_zava_user: str | None = Header(default=None)) -> StreamingResponse:
    async def events() -> AsyncGenerator[str, None]:
        problems = config_problems()
        if problems:
            yield sse({"error": "Agent service is not configured: " + "; ".join(problems)})
            return
        try:
            rls_user_id: str | None = None
            user: str | None = None
            session_key = limit_key = request.session_id
            if ACCESS_LIST is not None:
                user = normalise(x_zava_user)
                rls_user_id = ACCESS_LIST.rls_id_for(user, request.store)
                if rls_user_id is None:
                    record("denied", request.session_id, user=user or None)
                    yield sse({"error": "You are not on the access list for this agent, or not for that store."})
                    return
                # Sessions and limits belong to the person (and store), so nobody can read or use up another's.
                session_key, limit_key = f"{user}:{request.session_id}", user
                if request.store:
                    session_key = f"{user}:{rls_user_id}:{request.session_id}"
            if request.history and session_key not in sessions:
                sessions[session_key] = [{"role": t.role, "content": t.content} for t in request.history][-MAX_STORED_MESSAGES:]
            wait = rate_limit_wait(limit_key)
            if wait:
                yield sse({"error": f"Too many questions. Please wait {wait} seconds and try again."})
                return
            async for item in run_turn(app, session_key, request.message, rls_user_id, user):
                yield sse(item)
        except Exception as exc:  # noqa: BLE001 - report to the client instead of dropping the stream
            logger.exception("Chat turn failed")
            yield sse(
                {"error": f"Could not complete the request ({type(exc).__name__}). Check /health for MCP server status."}
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> JSONResponse:
    problems = config_problems()
    servers = app.state.server_status
    failed = [name for name, status in servers.items() if status.startswith("failed")]
    problems += [f"MCP server {name} {servers[name]}" for name in failed]
    if not app.state.semantic_status.startswith(("ok", "not checked")):
        problems.append(f"Semantic search {app.state.semantic_status}")
    usable = (bool(app.state.tools) or ACCESS_LIST is not None) and not config_problems()
    status = "healthy" if not problems else ("degraded" if usable else "misconfigured")
    body = {
        "status": status,
        "model": MODEL_DEPLOYMENT,
        "prompt_version": PROMPT_VERSION,
        "mcp_servers": servers,
        "tool_count": len(app.state.tools),
        "semantic_search": app.state.semantic_status,
        "access_list_users": len(ACCESS_LIST.users) if ACCESS_LIST else None,
        "identities_running": len(app.state.pools),
        "problems": problems,
    }
    return JSONResponse(body, status_code=200 if usable else 503)


if __name__ == "__main__":
    print("Starting agent service on http://127.0.0.1:8006")
    print(f"MCP servers (stdio): {', '.join(MCP_SERVERS)}  |  model deployment: {MODEL_DEPLOYMENT}")
    uvicorn.run(app, host="127.0.0.1", port=8006)
