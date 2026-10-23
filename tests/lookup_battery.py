# Randomised product-lookup battery: random SKUs, prefixes, suffixes, names, typos, categories and stores, checked against independent SQL.
# Run: python tests/lookup_battery.py <seed>   (costs about $0.15; try several seeds)
import asyncio, random, re, sys, time
sys.path.insert(0, "/workspace"); sys.path.insert(0, "/workspace/src/python/workshop")
import agent_service as svc
from access import GLOBAL_RLS_ID, STORE_RLS_IDS
from tests.test_inventory_advisor import sql_rows, GLOBAL
K = STORE_RLS_IDS["Zava Retail Kirkland"]
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 714
rnd = random.Random(SEED)
num = lambda a, n: str(int(n)) in a.replace(",", "")

async def stock(where="TRUE", store=None, args=()):
    rows = await sql_rows(GLOBAL, f"SELECT p.sku, p.product_name, p.base_price, COALESCE(SUM(i.stock_level) FILTER (WHERE $1::int IS NULL OR i.store_id = $1), 0) s FROM retail.products p LEFT JOIN retail.inventory i USING (product_id) WHERE {where} GROUP BY p.sku, p.product_name, p.base_price ORDER BY p.sku", store, *args)
    return [(r["sku"], r["product_name"], float(r["base_price"]), int(r["s"])) for r in rows]

def all_rows(rows):
    return lambda a: [f"missing {s} {n}" for s, _, _, n in rows if s not in a or not num(a, n)]

async def main():
    prods = await stock()
    cats = [r["category_name"] for r in await sql_rows(GLOBAL, "SELECT category_name FROM retail.categories ORDER BY 1")]
    picks = rnd.sample(prods, 14)
    cases = []
    # exact SKU, varied wording and case
    for (sku, name, price, s), tpl in zip(picks[:3], ["stock of {sku}", "do we have any {sku_l} in stock?", "what's the stock level for sku {sku}"]):
        cases.append((f"exact:{sku}", GLOBAL_RLS_ID, tpl.format(sku=sku, sku_l=sku.lower()), lambda a, s=s: [] if num(a, s) else [f"stock {s} missing"]))
    # prefix / suffix / contains, random pieces
    pre = picks[3][0][:rnd.choice([2, 3, 4])]
    cases.append((f"prefix:{pre}", GLOBAL_RLS_ID, rnd.choice([f"show stock for skus starting with {pre}", f"all products whose sku begins {pre}", f"list {pre} products and their stock"]), None, "LIKE", f"{pre}%"))
    suf = picks[4][0][-3:]
    cases.append((f"suffix:{suf}", GLOBAL_RLS_ID, rnd.choice([f"stock of skus ending in {suf}", f"which products have a sku that ends with {suf}, with stock", f"products with SKU ...{suf} and how many do we hold"]), None, "LIKE", f"%{suf}"))
    mid = picks[5][0][2:5]
    cases.append((f"contains:{mid}", GLOBAL_RLS_ID, f"any sku containing {mid}? what is the stock", None, "LIKE", f"%{mid}%"))
    # names: first word, two words, plural, reversed order, shouting
    for (sku, name, price, s), kind in zip(picks[6:10], ["word", "plural", "reverse", "upper"]):
        words = name.split()
        q = {"word": f"how much {words[0].lower()} stock do we have", "plural": f"stock of {name.lower()}s" if not name.endswith("s") else f"stock of {name.lower()}", "reverse": f"stock of {' '.join(reversed(words)).lower()}", "upper": f"WHAT IS THE STOCK OF {name.upper()}"}[kind]
        cases.append((f"name-{kind}:{name}", GLOBAL_RLS_ID, q, lambda a, name=name, s=s, kind=kind: ([] if (num(a, s) or kind == "word") else [f"stock {s} missing for {name}"]) + ([] if name.split()[0].lower() in a.lower() else ["name missing"])))
    # price and details
    sku, name, price, s = picks[10]
    cases.append((f"price:{name}", GLOBAL_RLS_ID, f"what is the price of {name}", lambda a, price=price: [] if (f"{price:.2f}" in a or str(price) in a) else [f"price {price} missing"]))
    sku, name, price, s = picks[11]
    cases.append((f"store:{name}", GLOBAL_RLS_ID, f"how many {name} are in the Seattle store", None, "STORE1", sku))
    # category
    cat = rnd.choice(cats)
    n_s = (await sql_rows(GLOBAL, "SELECT COUNT(DISTINCT p.product_id) n, SUM(i.stock_level) s FROM retail.products p JOIN retail.categories c USING (category_id) JOIN retail.inventory i USING (product_id) WHERE c.category_name = $1", cat))[0]
    cases.append((f"category:{cat}", GLOBAL_RLS_ID, f"how many {cat.lower()} products are there and how much stock", lambda a, n_s=n_s: ([] if num(a, n_s["n"]) else ["count missing"]) + ([] if num(a, n_s["s"]) else ["total missing"])))
    # misspelling (semantic fallback) and missing product
    sku, name, price, s = picks[12]
    w = max(name.split(), key=len)
    typo = name.replace(w, w[:-2] + w[-1] + w[-2]) if len(w) > 4 else name
    cases.append((f"typo:{typo}", GLOBAL_RLS_ID, f"stock of {typo}", lambda a, s=s: [] if num(a, s) or re.search(r"(?i)did you mean|closest|similar|no product|not found|couldn", a) else ["no stock and no honest miss"]))
    cases.append(("missing", GLOBAL_RLS_ID, "do we sell unicorn saddles", lambda a: ([] if re.search(r"(?i)no product|not found|could not find|couldn.t find|no match|do not (sell|have|stock)|0 products|found 0|no —|don.t (sell|have|stock)|did not find|didn.t find|isn.t|not in", a) else ["did not say not found"]) + (["invented units"] if re.search(r"\d[\d,]*\s*units", a) else [])))
    # Kirkland: own store only, then another store
    sku, name, price, s = picks[13]
    ks = (await stock("p.sku = $2", 7, (sku,)))[0][3]
    cases.append((f"kirkland-own:{name}", K, f"stock of {name}", lambda a, ks=ks, s=s: ([] if num(a, ks) else [f"kirkland stock {ks} missing"]) + (["leaked network figure"] if num(a, s) and s != ks else [])))
    cases.append((f"kirkland-other:{name}", K, f"stock of {name} in Seattle", lambda a: ([] if re.search(r"(?i)cannot|can.t|only see|not visible|unable", a) else ["did not decline"])))

    # resolve LIKE-based and store cases with ground truth
    built = []
    for c in cases:
        if len(c) == 4:
            built.append(c); continue
        label, rls, q, _, kind, arg = c
        if kind == "LIKE":
            rows = await stock("p.sku LIKE $2", None, (arg,))
            built.append((label, rls, q, all_rows(rows) if rows else (lambda a: [])))
        else:
            r = (await stock("p.sku = $2", 1, (arg,)))[0]
            built.append((label, rls, q, lambda a, r=r: [] if num(a, r[3]) else [f"seattle stock {r[3]} missing"]))
    sem = asyncio.Semaphore(4)
    async def one(c):
        label, rls, q, check = c
        async with sem:
            svc.RLS_USER_ID = rls
            t, tools = "", []
            async for it in svc.run_turn(svc.app, f"l2-{abs(hash(label))%99999}-{int(time.time())}", q, rls_user_id=rls):
                t += it.get("content", "")
                if it.get("tool"): tools.append(it["tool"]["name"])
            return label, q, t, tools, check(t.replace("**", ""))
    async with svc.lifespan(svc.app):
        res = await asyncio.gather(*[one(c) for c in built])
    ok = 0
    for label, q, t, tools, fails in res:
        ok += not fails
        print(f"[{'PASS' if not fails else 'FAIL'}] {label} | {tools}\n    Q: {q}" + ("" if not fails else f"\n    WHY: {fails[:4]}{'...+'+str(len(fails)-4) if len(fails)>4 else ''}\n    A: {t[:380]!r}"))
    print(f"\nseed {SEED}: {ok}/{len(res)} passed")
asyncio.run(main())
