# Use case definition (DRAFT: not signed off by the team)

Phase 3 is **not complete**. This draft is for the team to read, change and agree. Items marked **[CONFIRM]** are my assumptions about people and decisions that the data cannot answer. Figures are from the live database on 2026-10-13 (agent tools and the analysis notebook). `data/database/analysis_summary_and_agent_candidates.md` is older and some of its figures differ (for example 2023 units down 3.5% there, 5.0% now).

## Part 1: The five tests, for each candidate

| Test | P1 Excess stock and capital tied up | P2 Store stock does not follow demand | P3 Seasonal demand and demand shifts | Products bought together |
|---|---|---|---|---|
| 1. Can the data answer it? | **Yes, with a caveat.** Stock is synthetic and not tied to sales, so the size of the excess reflects how the data was generated | **Yes, with a caveat.** Stock share equals customer share by construction | **Partly.** Seasonal patterns are in the data. Supplier lead times are not | Yes |
| 2. User, decision, consequence? | **Yes** (see Part 2) | **Weak.** There is no shortage today, so the cost of a wrong decision is hard to state | **Weak.** No purchasing risk today: stock covers hundreds of months | Yes, but low stakes |
| 3. Needs an agent? | **Moderate to strong.** A report can rank excess. It cannot decide to check seasonality, other stores or a recent demand shift next, and reconcile low sales now against a coming peak | **Weak.** `compare_store_coverage` is close to one query. The agent adds explanation | **Moderate.** Monitoring and early warning would need a schedule, which we have not built. On demand, it is one query | **No.** A report or recommender does it |
| 4. Two or more tools and a real reasoning step? | **Yes.** Ranking, seasonal guard, store coverage, year history | **Partly.** Coverage plus seasonality | **Yes** in principle | No |
| 5. Small enough to finish, big enough to be interesting? | **Yes.** Built and tested | **Partly.** The tool is built, the workflow is thin | **Partly.** The seasonal check is built, forecasting is not | Not chosen |

**Why the other candidates lost, honestly.**
- *Products bought together:* a report or simple recommender does it, and store-level differences are too small to trust.
- *P2 and P3:* both are real patterns, but each scores weakly on tests 2 and 3. In their current form they are closer to a query than to an agent.

**A weakness in test 3 for P1.** The seasonal check now runs inside `rank_capital_tied_up` (`clearance_guard`), which was done to make the guard reliable. That moves a decision from the model into code. The model still chooses which tool to call, whether to look at other stores or years, and how to explain a conflict. A marker may still say a report would do, so the removal-test argument should be made with an example, not just stated.

**Decision for the team.** We built all three as one agent with three workflows (decision log D1 and D9). The page asks for one use case. This draft recommends **P1 as the primary use case**, with P2 and P3 described as supporting workflows that share its tools, not as separate use cases. **[CONFIRM: team decision.]**

## Part 2: One-page use case definition (P1)

**1. Problem statement.** Zava holds far more stock than it sells, and nothing tells the people who buy and clear stock where to act first. Capital is tied up in a small number of products, and some of those are about to enter their busy season, so clearing them would be a mistake.

**2. The user.** An inventory manager or buyer at Zava Retail head office, accountable for stock levels and the cash tied up in them. A store manager is a second user, who can see only their own store. **[CONFIRM: job titles, and who the team treats as the main user.]**

**3. The decision.** What to stop buying, move or clear first, and in which stores. **[CONFIRM: how often this is decided and what they use today, for example a spreadsheet or weekly report. The data does not say.]**

**4. The consequence.** Cash is tied up in stock nobody is buying, and clearing a product just before its peak loses sales. Stock is worth about $193.7M at cost against about $5.6M of cost of goods sold in the last 12 months. At the 6-month cover target, excess at cost is $190.85M, and the top product alone (Sliding Miter Saw 12-inch) holds $4.43M. These sizes come from synthetic stock data, so they show the shape of the problem, not a real loss. **[CONFIRM: wording of the real-world cost.]**

**5. The evidence.** Analysis notebook `data/database/all_7_analysis_db.ipynb`, questions 5 and 6, and the agent tools checked against independent SQL (`tests/test_inventory_advisor.py`). Stock is 3,997,159 units against about 116,600 sold in 12 months. 99% of product-store records hold more than 5 years of stock. Seasonal peaks are stable: Garden & Outdoor peaks in April every year.

**6. Why an agent.** (Removal test.) Take the model out and a scheduled report still ranks excess. What it cannot do is decide what to look up next. Example: the top excess products are mostly power tools. The agent checks whether any category is near its seasonal peak before recommending a clear, and says "do not clear" when it is. It chooses between tools, judges whether the evidence supports an action, and drafts a recommendation with the figures behind it for a person to approve.

**7. Success criteria.** See the table below. A correct answer matches independent SQL and states its scope. A **confidently wrong** answer looks like a clean, plausible recommendation with a wrong figure, a store's view called the network, or a clearance advised before a peak.

| # | Criterion | How a wrong answer is caught |
|---|---|---|
| E1 | Every figure matches a tool result | Automatic check on every answer; evaluation compares with independent SQL |
| E2 | Ranking matches ground truth | Evaluation H1, A1 |
| E3 | Never recommends clearing a product whose peak is near | Evaluation S1 and tool tests |
| E4 | No future-dated orders counted | Tool tests, evaluation E3 |
| E5 | No data from outside the user's scope, even under pressure | Evaluation A1 to A3, V1 |
| E6 | States limits: snapshot, cost is not cash, lead times missing | Evaluation L1 and L2 |
| E7 | Wrong answers are caught or refused | Evaluation A2, V2, V3, and the answer check |

**8. Scope boundaries.** The agent does not place orders, clear or move stock (drafts only). It does not forecast demand or price clearance. It does not know transfer costs, lead times or supplier terms because they are not in the data. It has one identity per running service, not per-user sign-in. It is not deployed beyond a local demo.
