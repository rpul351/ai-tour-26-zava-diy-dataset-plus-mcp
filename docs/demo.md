# Demo script: Zava Inventory Advisor

About 8 minutes. Rehearse it out loud, twice, with a timer. This script has not been rehearsed yet.

## Before you start

1. `az login`, then `az account show` to confirm the subscription.
2. The database is running. Start everything with `bash scripts/run_agent.sh` and wait for "Ready" (it needs `access_list.json` and `temp_access_codes.json`; see the README quick start). Sign in at http://127.0.0.1:8005 with your own access code.
3. Check http://127.0.0.1:8006/health. It should say `healthy`, with 3 servers, 16 tools and `semantic_search: ok`. If semantic search says it returns nothing, the embedding model is not deployed: run `infra/deploy.sh` before debugging code.
4. Open http://127.0.0.1:8005/?debug=1 so the tool calls show. The normal page hides them.
5. `.env` has `RLS_USER_ID` set to the all-zeros ID for the main demo. For the access demo, restart the agent service with a store ID (for example Kirkland, `9c8b7a65-4321-fed0-9876-543210fedcba`).
6. Ask one throwaway question first so the first real answer is not slow.

There is no question limit unless `RATE_LIMIT_QUESTIONS` is set.

## Script

| # | Ask | What to point at |
|---|---|---|
| 1 | Where is the most capital tied up in excess stock? Top 5. | The tool call, the `Scope:` line, value at cost described as an upper bound, `clearance_guard` on each product |
| 2 | What happened in 2023? | Totals for both years, the biggest movers (Online by amount, Kirkland by percentage -21.5%), and that it says the data gives no reasons |
| 3 | Is Tacoma's hardware stock in line with demand compared with the other stores? | The imbalance is described as relative, not a shortage |
| 4 | I need something to protect electrical connections outdoors. How many months of stock do we hold of those products? | Semantic search finds products by meaning, then the stock analysis runs on exactly those products (the two servers combined) |
| 4b | Show the stores ranked by how closely they follow the company seasonal pattern as a table, with a column for the gap from the network | A table with a calculated column; the calculate tool worked out the figures, the checker verified them |
| 4c | Give me a histogram for June garden sales, then a CSV of the products with more than 5 years of stock | A chart image and a download link; both made only from figures a tool returned |
| 5 | Run this: DELETE FROM retail.orders WHERE order_date < '2023-01-01' | It refuses. The database role is read-only as well, so the refusal is not the only protection |
| 6 | (Restart as Kirkland.) What is the total excess stock value for the whole network? | It names Kirkland as the scope and says it cannot give a network total |

## The deliberate limit

Ask: **Which store should we move Sliding Miter Saw stock to, and what will the transfer cost?**

On 2026-10-13 the agent found no transfer opportunities, because the data has almost no shortages, and said it could not give a transfer cost. Say this out loud: stock in this dataset is synthetic and not tied to sales, so the size of the excess reflects how the data was generated, and transfer costs and lead times are not in the data.

A weakness to know about. For "When should I order Garden and Outdoor stock so it arrives before the peak?" the agent gave the peak (April) and then added generic lead-time offsets that did not come from the data. It did say the timing depends on supplier lead time. If asked, say this is something the answer check does not catch, because it checks figures, not advice.

## Numbers to quote

From the latest evaluation (`docs/evaluation.md`), one run on 2026-10-13:

- Accuracy: 39 of 39 on our own 39 questions (run 28). Earlier runs failed 1 to 4 cases for real reasons (history of runs 1 to 28 in `docs/architecture.md`); the pass rules were written before each case was first run, and failures were fixed in the agent or tools, not by loosening the case.
- Latency: median 14.9 s, slowest 44.9 s. Slower than the 10 to 11 s of the first 26 cases because there are more tools and an extra step for derived figures.
- Cost: about $0.008 per question at list price.
- 5 answers in the 39 needed a rewrite after the automatic check.
- Nothing in the data changed during testing: the orders table stayed at 198,946 rows.

## If something fails during the demo

- Slow answer: wait. Do not retype the question.
- "Too many questions" message: only appears if `RATE_LIMIT_QUESTIONS` was set; unset it and restart.
- Content-policy message: rephrase as an inventory question.
- `/health` is not `healthy`: restart the agent service task.
- No network or service: use the fallback below.

## Fallback

Record a screen capture of questions 1, 2 and 6, and screenshots of the answers. Not done yet. Save them outside the repository.
