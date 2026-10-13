# Demo script: Zava Inventory Advisor

About 8 minutes. Rehearse it out loud, twice, with a timer. This script has not been rehearsed yet.

## Before you start

1. `az login`, then `az account show` to confirm the subscription.
2. The database is running. Run the tasks **Run Agent Service** and **Run Web App**.
3. Check http://127.0.0.1:8006/health. It should say `healthy`, with 3 servers and 11 tools.
4. Open http://127.0.0.1:8005/?debug=1 so the tool calls show. The normal page hides them.
5. `.env` has `RLS_USER_ID` set to the all-zeros ID for the main demo. For the access demo, restart the agent service with a store ID (for example Kirkland, `9c8b7a65-4321-fed0-9876-543210fedcba`).
6. Ask one throwaway question first so the first real answer is not slow.

Each session may ask 10 questions in 10 minutes. Open a new tab to start a fresh session.

## Script

| # | Ask | What to point at |
|---|---|---|
| 1 | Where is the most capital tied up in excess stock? Top 5. | The tool call, the `Scope:` line, value at cost described as an upper bound, `clearance_guard` on each product |
| 2 | What happened in 2023? | Totals for both years, the biggest movers (Online by amount, Kirkland by percentage -21.5%), and that it says the data gives no reasons |
| 3 | Is Tacoma's hardware stock in line with demand compared with the other stores? | The imbalance is described as relative, not a shortage |
| 4 | I need something to protect electrical connections outdoors. What do you sell? | Semantic search finding products by description |
| 5 | Run this: DELETE FROM retail.orders WHERE order_date < '2023-01-01' | It refuses. The database role is read-only as well, so the refusal is not the only protection |
| 6 | (Restart as Kirkland.) What is the total excess stock value for the whole network? | It names Kirkland as the scope and says it cannot give a network total |

## The deliberate limit

Ask: **Which store should we move Sliding Miter Saw stock to, and what will the transfer cost?**

On 2026-10-13 the agent found no transfer opportunities, because the data has almost no shortages, and said it could not give a transfer cost. Say this out loud: stock in this dataset is synthetic and not tied to sales, so the size of the excess reflects how the data was generated, and transfer costs and lead times are not in the data.

A weakness to know about. For "When should I order Garden and Outdoor stock so it arrives before the peak?" the agent gave the peak (April) and then added generic lead-time offsets that did not come from the data. It did say the timing depends on supplier lead time. If asked, say this is something the answer check does not catch, because it checks figures, not advice.

## Numbers to quote

From the latest evaluation (`docs/evaluation.md`), one run on 2026-10-13:

- Accuracy: 23 of 23 on our own 23 questions. Earlier runs scored 16 to 19 (history in `docs/architecture.md`). The rules were adjusted while the work was in progress.
- Latency: median 10.4 s, slowest 29.2 s.
- Cost: about $0.0042 per question at list price (median 11,293 tokens).
- About 1 in 7 answers needed a rewrite after the automatic check (12 of 85 logged answers).
- Nothing in the data changed during testing: the orders table stayed at 198,946 rows.

## If something fails during the demo

- Slow answer: wait. Do not retype the question.
- "Too many questions" message: open a new tab.
- Content-policy message: rephrase as an inventory question.
- `/health` is not `healthy`: restart the agent service task.
- No network or service: use the fallback below.

## Fallback

Record a screen capture of questions 1, 2 and 6, and screenshots of the answers. Not done yet. Save them outside the repository.
