# Use case: Zava Inventory Advisor (Phase 3 draft for team review)

**Status: DRAFT. Not agreed.** Phase 3 stays open until every team member has agreed in the sign-off table at the end.

Figures are from the live database on 2026-10-13.

## What we are asking you to decide

1. **One use case or three?** We built one agent that handles three problems. Phase 3 asks for one use case. **Proposal: make P1 (excess stock) the main use case, and describe P2 and P3 as supporting workflows that reuse its tools.**
2. **Who is the user, and what do they decide?** Our proposed answer is in Part 2. Please correct it.
3. **Is the cost of a wrong decision worded correctly?** See Part 4.
4. **Do you agree with the success criteria and the scope limits?** See Parts 7 and 8.

## The use case (P1: excess stock)

**1. Problem.** Zava holds far more stock than it sells, and nothing says where to act first. Money is tied up in a few products. Some of them are about to enter their busy season, so clearing them would be a mistake.

**2. User.** An inventory manager or buyer at head office, accountable for stock levels and the cash tied up in them. A store manager is a second user and sees only their own store.

**3. Decision.** What to stop buying, move or clear first, and in which stores. *Please add: how often, and what is used today (spreadsheet, weekly report?). The data does not say.*

**4. Consequence of a wrong decision.** Cash stays tied up in stock nobody is buying. Or a product is cleared just before its peak and sales are lost.
- Stock is worth about **$193.7M at cost**. Cost of goods sold in the last 12 months was about **$5.6M**.
- Stock above 6 months of cover is worth **$190.85M at cost**. The top product (Sliding Miter Saw 12-inch) alone holds **$4.43M**.
- *These sizes come from synthetic stock data, so they show the shape of the problem, not a real loss. We say this in every answer and in the report.*

**5. Evidence.**
- 3,997,159 units in stock against about 116,600 sold in 12 months.
- 99% of product-store records hold more than 5 years of stock.
- Garden & Outdoor peaks in April every year from 2020 to 2026, so seasonal peaks are reliable.
- Where: notebook `data/database/all_7_analysis_db.ipynb` (questions 5 and 6), and the agent tools checked against independent SQL in `tests/test_inventory_advisor.py`.

**6. Why an agent (the removal test).** Take the model out and a scheduled report still ranks the excess. What the report cannot do is decide what to look at next. Example: the biggest excess is in power tools. Before recommending a clearance, the agent checks whether the category is near its seasonal peak. For Electrical today it is two months away, and the agent says "do not clear". It picks the tools, judges whether the evidence supports an action, and drafts a recommendation with its figures for a person to approve.

*Honest weakness:* the seasonal check now runs inside the ranking tool so that it is reliable. That moves one decision from the model into code. A marker may still say a report would do, so we should argue this with the example above.

**7. Success criteria.** A correct answer matches independent SQL and says which stores it covers. A *confidently wrong* answer reads as a clean recommendation but has a wrong figure, calls one store's data the network, or advises clearing before a peak.

| # | Criterion | How we catch a wrong answer |
|---|---|---|
| E1 | Every figure matches a tool result | An automatic check on every answer. Evaluation compares with independent SQL |
| E2 | The ranking matches ground truth | Evaluation H1, A1 |
| E3 | Never advises clearing a product whose peak is near | Evaluation S1, tool tests |
| E4 | No future-dated orders counted | Tool tests, evaluation E3 |
| E5 | No data from outside the user's stores, even under pressure | Evaluation A1 to A3, V1 |
| E6 | States its limits: snapshot, cost is not cash, lead times missing | Evaluation L1, L2 |
| E7 | Wrong answers are caught or refused | Evaluation A2, V2, V3, and the automatic check |

Latest result: 23 of 23 passed, with median 10.4 s per answer and about $0.004 per question (details and earlier runs in `docs/evaluation.md` and `docs/architecture.md`). The text rules were adjusted during the work, so read the answers as well as the pass marks.

**8. Scope boundaries.** The agent never places orders or moves or clears stock. It only drafts recommendations. It does not forecast demand or price clearances. It does not know transfer costs, supplier lead times or terms, because they are not in the data. It has one identity per running service, not per-user sign-in. It is a local demo and is not deployed.

## The five tests, for each candidate

| Test | P1 Excess stock | P2 Stock does not follow demand | P3 Seasonal demand | Products bought together |
|---|---|---|---|---|
| 1. Can the data answer it? | Yes, but stock is synthetic | Yes, but stock share equals customer share by construction | Partly: no lead times | Yes |
| 2. User, decision, consequence? | **Yes** | Weak: no shortage today | Weak: no purchasing risk today | Yes, low stakes |
| 3. Needs an agent? | **Moderate to strong** | Weak: close to one query | Moderate: monitoring needs a schedule we have not built | No: a report does it |
| 4. Two or more tools and reasoning? | Yes | Partly | Yes in principle | No |
| 5. Small enough to finish? | **Yes, built and tested** | Partly | Partly | Not chosen |

**Why the others lose.** Products bought together is a report, and store-level differences are too small to trust. P2 and P3 are real patterns, but each is weak on tests 2 and 3, so as use cases in their own right they are closer to a query than an agent.

## Sign-off

Phase 3 is complete only when every row says "Agree".

| Name | Agree / Changes needed | Date |
|---|---|---|
| | | |
| | | |
| | | |
| | | |

Changes the team asked for:

-
