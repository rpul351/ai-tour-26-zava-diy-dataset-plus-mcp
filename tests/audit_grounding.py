"""Grounding audit: does any name, SKU or number in an answer lack support in the tool results the agent received?

Run from the repository root with `python tests/audit_grounding.py` (about 3 minutes, a few cents of model use).
It asks 24 questions as three identities plus a five-turn Seattle conversation and writes the details to logs/audit_grounding.json.
"""
import asyncio, json, re, sys, time
sys.path.insert(0, "/workspace"); sys.path.insert(0, "/workspace/src/python/workshop")
import agent_service as svc
from answer_verifier import _derivable, _evidence_values, _present
from access import GLOBAL_RLS_ID, STORE_RLS_IDS
from tests.test_inventory_advisor import sql_rows

K = STORE_RLS_IDS["Zava Retail Kirkland"]; S = STORE_RLS_IDS["Zava Retail Seattle"]; G = GLOBAL_RLS_ID
ONE_SHOT = [
 (G, "Which category has the sharpest seasonal swing, and how far ahead would you need to act on it?"),
 (G, "Which stores are most and least aligned to the national seasonal pattern?"),
 (G, "What actually happened in 2023? Which categories, which stores, which months?"),
 (G, "Which products are frequently bought together, and does that differ by store or season?"),
 (G, "Where is inventory misaligned with demand? Are there stores holding stock that another store needs?"),
 (G, "Which products have the widest gap between inventory levels and sales velocity?"),
 (G, "What are the top selling products?"),
 (G, "Top 5 products by sales"),
 (G, "Which products sold the most last month?"),
 (G, "Which products have more than 5 years of stock?"),
 (G, "Where is the most capital tied up in excess stock? Top 5."),
 (G, "Is Tacoma's hardware stock in line with demand compared with the other stores?"),
 (G, "How did 2024 compare with 2023?"),
 (G, "Compare Tacoma and Seattle sales in 2025"),
 (G, "Which stores sell the most Paint & Finishes in March?"),
 (G, "I need something to protect electrical connections outdoors. How many months of stock do we hold of those products?"),
 (G, "Table of units sold and revenue by store in 2023, with a new column for revenue per unit"),
 (G, "Which top 5 products are frequently bought together in seattle store?"),
 (K, "Where is capital tied up in excess stock? Top 3."),
 (K, "Which products sold the most last month in my store?"),
 (K, "What happened in 2023?"),
 (S, "How many units did the Seattle store sell in 2024?"),
 (S, "can you pull latest 5 products sold"),
 (S, "which top 5 products have the most stock in my store?"),
]
CONVERSATION = (S, [
 "tell which product is performing worst in Seattle store this season",
 "tell which product is performing worst in Seattle store this month",
 'how "windows casing set" is doing in Seattle store in this month',
 "then why this product isnot in my worst performing products in Seattle in this month",
 "why are you changing the number",
])
NUM = re.compile(r"(?<![\w.])-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
SKU = re.compile(r"\b[A-Z]{2,}[A-Z]*\d{2,}[A-Z\d]*\b")
DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")


async def run(session, rls, q):
    svc.RLS_USER_ID = rls
    text = ""
    async for it in svc.run_turn(svc.app, session, q, rls_user_id=rls):
        text += it.get("content", "")
    return text


def audit(answer, evidence, question, names):
    ev = "\n".join(evidence)
    vals = _evidence_values([*evidence, question])
    nameless = answer
    for n in sorted((n for n in names if n in answer), key=len, reverse=True):
        nameless = nameless.replace(n, " ")
    bad_names = sorted({n for n in names if n in answer and n not in ev and n not in question})
    bad_skus = sorted({s for s in SKU.findall(answer) if s not in ev and s not in question})
    big, small = [], []
    body = DATE.sub(" ", SKU.sub(" ", nameless))
    for line in body.splitlines():
        if line.lower().lstrip().startswith("scope:"):
            continue
        line = re.sub(r"^\s*(?:[-*]\s*)?\d+[.)]\s", " ", line)
        row = None
        if line.strip().startswith("|"):
            row = [abs(float(m.group().replace("$", "").replace(",", ""))) for m in NUM.finditer(line)]
        for m in NUM.finditer(line):
            raw = m.group().replace("$", "").replace(",", "")
            v = abs(float(raw))
            if 1900 <= v <= 2100 and "." not in raw:
                continue
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            tol = 0.5 * 10 ** (-decimals)
            if _present(vals, v, tol) or (row is not None and _derivable(v, tol, row, vals)):
                continue
            (big if v >= 100 or decimals else small).append(m.group())
    return bad_names, bad_skus, big, small


async def main():
    names = [r["product_name"] for r in await sql_rows(G, "SELECT product_name FROM retail.products")]
    rows = []
    async with svc.lifespan(svc.app):
        sem = asyncio.Semaphore(4)

        async def one(i, rls, q):
            async with sem:
                sid = f"audit-{i}-{int(time.time())}"
                a = await run(sid, rls, q)
                return q, a, list(svc.evidence_store.get(sid, []))

        results = await asyncio.gather(*[one(i, r, q) for i, (r, q) in enumerate(ONE_SHOT)])
        sid = f"audit-conv-{int(time.time())}"
        rls, turns = CONVERSATION
        conv = []
        for q in turns:
            a = await run(sid, rls, q)
            conv.append((q, a, list(svc.evidence_store.get(sid, []))))
    out = []
    for q, a, ev in [*results, *conv]:
        bn, bs, big, small = audit(a, ev, q, names)
        out.append(dict(q=q, names=bn, skus=bs, big=big, small=small, answer=a, evidence_chars=sum(len(x) for x in ev)))
    json.dump(out, open("/workspace/logs/audit_grounding.json", "w"), indent=1)
    print(f"{'question':64s} names skus big small")
    for r in out:
        print(f"{r['q'][:64]:64s} {len(r['names']):5d} {len(r['skus']):4d} {len(r['big']):3d} {len(r['small']):5d}")
    tot = lambda k: sum(len(r[k]) for r in out)
    print(f"\nanswers: {len(out)} | with an unsupported product name: {sum(1 for r in out if r['names'])} | unsupported SKU: {sum(1 for r in out if r['skus'])} | "
          f"answers with unsupported figures of 100 or more or with decimals: {sum(1 for r in out if r['big'])} ({tot('big')} figures) | answers with unsupported small numbers: {sum(1 for r in out if r['small'])} ({tot('small')} numbers)")

asyncio.run(main())
