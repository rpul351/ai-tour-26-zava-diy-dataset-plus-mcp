"""Repeat check: does the same question give the same figures every time?

Run from the repository root:   python -m tests.repeat_check [N] [case ids...]
Each chosen evaluation case is asked N times (default 5) in fresh chats. A case is stable if every run passes
its own evaluation rule (which checks the figures against independent SQL). Figures of 3 or more digits that appear in
some runs but not all are listed as extra detail, because the wording and how much is shown vary between runs. Needs the same set-up as
tests.evaluation. Writes logs/repeat_results.json.
"""

import asyncio
import json
import re
import sys

from tests import evaluation as ev

DEFAULT_CASES = ("K1", "K2", "F2", "H2", "H1", "T2")
IDENTITY_USER = ev.IDENTITIES


def figures(answer: str) -> set[str]:
    plain = re.sub(r"\b\d{4}-\d\d-\d\d\b", "", answer.replace(",", ""))
    return {m for m in re.findall(r"\d+(?:\.\d+)?", plain) if len(m.split(".")[0]) >= 3}


async def main(repeats: int, ids: tuple[str, ...]) -> None:
    from sales_analysis_postgres import PostgreSQLSchemaProvider

    ev._provider = PostgreSQLSchemaProvider()
    await ev._provider.create_pool()
    cases = [c for c in ev.build_cases(await ev.ground_truth()) if c.id in ids]
    report = []
    for identity, rls_user_id in IDENTITY_USER.items():
        batch = [c for c in cases if c.identity == identity]
        if not batch:
            continue
        ev.svc.RLS_USER_ID = rls_user_id
        sem = asyncio.Semaphore(ev.CONCURRENCY)
        async with ev.svc.lifespan(ev.svc.app):
            runs = await asyncio.gather(*(ev.run_case(c, sem) for c in batch for _ in range(repeats)))
        for case in batch:
            mine = [r for r in runs if r["id"] == case.id]
            sets = [figures(r["answer"]) for r in mine]
            always, sometimes = set.intersection(*sets), set.union(*sets) - set.intersection(*sets)
            passed = sum(r["passed"] for r in mine)
            report.append({"id": case.id, "runs": len(mine), "passed": passed,
                           "figures_in_every_run": sorted(always), "extra_detail_in_some_runs": sorted(sometimes),
                           "failures": sorted({x for r in mine for x in r["reasons"]})})
            print(f"{case.id}: {passed}/{len(mine)} runs pass; {len(always)} figures in every run, {len(sometimes)} only in some", flush=True)
    (ev.svc.LOG_DIR / "repeat_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    await ev._provider.close_pool()
    ok = all(r["passed"] == r["runs"] for r in report)
    print("ALL STABLE" if ok else "NOT STABLE: see logs/repeat_results.json")


if __name__ == "__main__":
    args = sys.argv[1:]
    n = int(args[0]) if args and args[0].isdigit() else 5
    chosen = tuple(a for a in args if not a.isdigit()) or DEFAULT_CASES
    asyncio.run(main(n, chosen))
