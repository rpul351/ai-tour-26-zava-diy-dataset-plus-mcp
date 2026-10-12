# Zava Retail: Findings and AI Agent Ideas

This is a plain-language summary of the seven questions in `all_7_analysis_db.ipynb`. All numbers come from the live `zava` database.

**Quick terms**

- **Units**: individual items sold or held in stock (not dollars).
- **Stock cover**: how long current stock would last at the current selling pace.
- **Store manager vs super manager**: a store manager can see only their own store's data. The super manager can see every store.

---

## The short version

| # | Question | Answer in one line |
|---|---|---|
| 1 | Which product categories change most through the year? | Garden & Outdoor. It sells most in April and least in December. |
| 2 | Which stores behave differently from the rest? | The four small stores (Kirkland, Everett, Redmond, Spokane). |
| 3 | What happened in 2023? | 91,301 units sold. Online and Seattle made up about 56% of them. |
| 4 | Which products are bought together? | Hand tools, mostly. The pattern is real across the whole company. |
| 5 | Is stock in the right stores? | No. Stock follows customer headcount, not how much each store sells. |
| 6 | Do stores hold too much or too little stock? | Far too much. The top 20 products each have over 5 years of stock. |
| 7 | What does a store manager see compared to the super manager? | A store manager sees only their own store (1.5% to 28.4% of all orders). |

---

## 1. Which categories change most through the year?

Garden & Outdoor changes the most. It sells best in April and worst in December. The table shows the busiest and quietest month for each category.

| Category | Busiest month | Quietest month |
|---|---|---|
| Garden & Outdoor | April | December |
| Storage & Organization | February | June |
| Lumber & Building Materials | June | December |
| Electrical | December | April |
| Hardware | October | July |
| Power Tools | August | December |
| Plumbing | October | August |
| Paint & Finishes | March | November |
| Hand Tools | July | October |

- Garden & Outdoor peaked in April in every year from 2020 to 2026, so it can be relied on.
- Paint & Finishes (March), Storage & Organization (February) and Electrical (December) repeat in most years.
- Hand Tools, Plumbing and Power Tools move around from year to year, so their peak months are less dependable.
- The database does not say how long suppliers take to deliver. We know when demand peaks, but not how early to order.

## 2. Which stores differ from the company-wide pattern?

The four large stores follow the company-wide pattern closely. The four small stores differ the most.

| Store | Follows company pattern? | Share of units sold |
|---|---|---|
| Online | Very closely | 28.4% |
| Seattle | Very closely | 27.5% |
| Bellevue | Closely | 18.4% |
| Tacoma | Fairly closely | 13.3% |
| Spokane | Differs | 5.0% |
| Redmond | Differs | 2.6% |
| Everett | Differs | 3.4% |
| Kirkland | Differs the most | 1.5% |

The small stores sell so little that random ups and downs can look like a real pattern. Treat this as a reason to take a closer look, not as proof.

## 3. What happened in 2023?

- 91,301 units were sold.
- Online (26,155) and Seattle (25,052) sold about 56% of them.
- Monthly sales across the whole company were steady, between 7,348 units (November) and 7,976 (July). Individual categories rise and fall, but those changes cancel each other out in the total.
- Paint & Finishes sold the most units (11,946), but Power Tools earned the most money.
- 2023 was a weak year. Units fell 3.5% from 2022, after growth in 2021 and 2022, and then recovered in 2024 and 2025. The biggest drops were in Kirkland (down 15.7%), Redmond (14.5%) and Spokane (7.9%). The data does not say why.

| Store | 2023 units | 2023 revenue |
|---|---|---|
| Online | 26,155 | 1,771,472 |
| Seattle | 25,052 | 1,700,747 |
| Bellevue | 16,804 | 1,180,296 |
| Tacoma | 12,313 | 844,883 |
| Spokane | 4,462 | 318,811 |
| Everett | 3,085 | 199,467 |
| Redmond | 2,159 | 149,597 |
| Kirkland | 1,271 | 83,909 |

## 4. Which products are bought together?

- Across the company, the most common pairs are hand tools bought with other hand tools. For example, a Level 24-inch with a SAE Hex Key Set appears together in 86 orders.
- These pairs are bought together about 9 times more often than you would expect by chance, and the pattern holds across different years. All of the top 100 pairs are hand tools.
- Individual stores do not show real differences. The "top pair" for a store is often based on only 3 to 12 orders, which is too few to trust. Do not build store-specific bundles from it.
- Garden & Outdoor items are bought together more in spring and summer. That simply follows the category's seasonal sales.

## 5. Is stock in the right stores?

No. Each store's share of stock almost exactly matches its share of customers, but customers at different stores buy at different rates.

| Store | Share of stock | Share of customers | Share of units sold |
|---|---|---|---|
| Online | 23.3% | 23.1% | 28.4% |
| Seattle | 23.1% | 22.7% | 27.5% |
| Bellevue | 18.2% | 19.3% | 18.4% |
| Tacoma | 16.0% | 15.5% | 13.3% |
| Spokane | 6.2% | 6.2% | 5.0% |
| Everett | 5.4% | 5.5% | 3.4% |
| Redmond | 4.6% | 4.7% | 2.6% |
| Kirkland | 3.1% | 3.0% | 1.5% |

- Online, Seattle and Bellevue hold less stock than their sales suggest.
- Tacoma and the small stores hold more than their sales suggest. For example, Tacoma holds 54,434 units of Hand Tools but sold only 1,473 in 2025.
- This is a comparison between stores, not a shortage. Every store still has far more stock than it sells (see question 6).
- The inventory table has no dates. It is a snapshot of today's stock.

## 6. Do stores hold too much or too little stock?

Far too much. The company holds 3,878,342 units, but sold only about 108,000 in 2025.

- The 20 worst products each have over 5 years of stock. For example, the Natural Bristle Brush Set has 15,225 units in stock and sells about 22 a month.
- Almost every product in every store (99%) has more than 5 years of stock. No product in any store has zero stock.
- The stock is worth about $190.6 million at cost. The cost of what was sold in 2025 was about $5.2 million.
- This may be real over-buying. It may also mean stock and sales are counted in different units (for example, boxes of items versus single items). This must be checked with the inventory owner before acting.

## 7. What does a store manager see compared to the super manager?

A store manager sees only their own store. The super manager sees all stores. Each store's numbers were checked and matched.

| View | Orders visible | Share of all orders |
|---|---|---|
| Super manager (all stores) | 198,783 | 100% |
| Online | 56,467 | 28.4% |
| Seattle | 54,579 | 27.5% |
| Bellevue | 36,502 | 18.4% |
| Tacoma | 26,426 | 13.3% |
| Spokane | 9,934 | 5.0% |
| Everett | 6,718 | 3.4% |
| Redmond | 5,189 | 2.6% |
| Kirkland | 2,968 | 1.5% |

- **Security warning.** The default `postgres` login ignores the store restrictions and sees everything. Any app or agent meant for one store must use a restricted login such as `store_manager`.
- The `store_manager` login currently has no working password.

---

## Problems that suit an AI agent

An agent watches data, works through several steps with tools, and prepares actions for a person to approve. A chatbot only answers questions when asked. Three problems fit an agent.

### 1. Excess stock and capital tied up

- **Problem.** The business holds far more stock than it can sell, which ties up capital, and nothing prioritises what to stop buying or clear first.
- **Evidence (Questions 5 and 6).**
  - The network holds 3,878,342 units against 107,954 sold in 2025, about 36 times a year of sales. At product cost the stock is worth about 190.6 million, against about 5.2 million of cost of goods sold in 2025.
  - The capital is concentrated. Power Tools and Storage & Organization hold 117.3 million, 61.5% of the stock value. The 8 highest-value products alone tie up 29.6 million. For example, the Sliding Miter Saw 12-inch has 12,494 units in stock against 232 sold in 2025, about 54 years of stock.
  - All 3,392 product-store stock records hold at least about 37 months of stock at 2025 sales, and 99% hold more than 5 years. 47 records (17,369 units, about 0.8 million at cost) had no 2025 sales at all.
- **Agent solution: Excess Stock Prioritisation Agent.** It ranks products by capital tied up and years of cover, separates likely unit errors from real excess, and recommends an action for each (hold new purchases, transfer, or clear). It estimates the cash released by each action, drafts the list for approval, and reruns on a schedule.
- **Why not a chatbot.** It must score thousands of product-store combinations, compare options, and keep monitoring as stock and sales change. A chatbot can only answer "which products are overstocked" when asked.
- **Without an agent.** A scheduled report can list the overstocked products. The agent adds prioritisation by cash impact, option comparison and follow-up.
- **Safeguards and gaps.** The first step is confirming that stock and sales use the same units. The data has no price-elasticity, supplier return terms or clearance history. Nothing should be cancelled or cleared without human approval.

### 2. Store stock allocation does not follow demand

- **Problem.** Each store's stock follows its customer headcount, not how much it sells, so replenishment keeps feeding the wrong stores.
- **Evidence (Questions 2 and 5).**
  - Stock share matches assigned-customer share in every store (Online 23.3% against 23.1%, Kirkland 3.1% against 3.0%), but sales do not. Over the order history, customers at Online place 4.87 orders each and Kirkland customers 1.93.
  - Coverage therefore differs: Online holds 358 months of stock at 2025 sales and Kirkland 857, about 2.4 times as much.
  - About 9.7% to 10% of all stock (roughly 377,000 to 389,000 units) would need to move to give every store the same coverage within each category. The result is similar whether 2025 or 2023 to 2025 sales are used.
  - Tacoma is the most over-stocked store relative to demand in 7 of 9 categories (2025), and Seattle the most under-stocked in 5.
- **Agent solution: Store Allocation Agent.** It sets demand-based stock targets for each store and category from ordering rates and seasonal patterns, then recommends where future purchases should go and which transfers would correct the drift. It treats transfer options as alternatives so the same surplus is never moved twice.
- **Why not a chatbot.** It must evaluate every store, category and period together, and keep targets current as demand changes.
- **Without an agent.** A one-off allocation table could be built with a report. The agent adds ongoing monitoring and updated recommendations.
- **Safeguards and gaps.** This is a relative imbalance, not a shortage: every store holds years of stock, so the near-term benefit is mainly in where future purchases are directed. Transfer costs are not in the data. A store manager can see only their own store (Question 7), so network-wide recommendations must come from a super-manager context and be filtered before they reach a store manager.

### 3. Seasonal forecasting and demand-shift monitoring (conditional)

- **Problem.** Demand follows strong seasonal patterns and can shift unexpectedly, as it did in 2023, but nothing turns that into a forward view for replenishment timing. The data also has no lead times.
- **Evidence (Questions 1 and 3).**
  - Garden & Outdoor peaked in April in every year in the data, Paint & Finishes in March in 6 of 7 years, and Storage & Organization in February in 6 of 7.
  - In 2023 units fell 3.5% after two years of roughly 9% to 11% growth, then recovered. The fall was concentrated in Kirkland, Redmond and Spokane and in Plumbing, Hand Tools, Garden & Outdoor and Power Tools, so a plan built on the network total alone would have misjudged them.
  - The database has no supplier or lead-time fields.
- **Why it is conditional.** There is no purchasing risk today: Garden & Outdoor stock covers about 280 peak months of demand. This becomes a real problem only after Problems 1 and 2 are addressed and stock levels are credible.
- **Agent solution: Seasonal Forecasting and Monitoring Agent.** It forecasts monthly demand for each store and category from the seasonal pattern, compares actual sales with the forecast each month, and flags deviations like 2023 early, showing where they are concentrated. Given lead-time assumptions the user supplies (for example "120 days of ocean freight"), it works backward to order deadlines and alerts buyers before they pass.
- **Worked example.** With a 120-day lead time and an April peak, the order is due by about 2 December (for a 1 April start) or 16 December (for mid-April), so a November alert leaves a few weeks of buffer.
- **Why not a chatbot.** It must run on a schedule for every store and category, compare forecasts with new sales, and alert buyers unprompted.
- **Without an agent.** A seasonal forecast on its own is a model or report. Monitoring, diagnosing where a shift is happening, and raising deadlines is the agent part.
- **Safeguards.** Lead times are assumptions and are shown with every recommendation. The agent drafts forecasts and calendars and does not place orders.

### Not an agent problem: products bought together

Hand tools being bought together is a real pattern, but a regular report or a simple recommendation feature can handle it. The data does not show store differences that would justify a store-specific agent.

### Safety rule for every agent

Any agent that serves store managers must connect with a restricted login, so the database itself limits what it can see.

---

## Data problems to fix first

These are not agent problems. They limit how far the numbers above can be trusted.

- **Orders dated in the future.** About 4% of orders (8,172) are dated after today (7 October to 31 December 2026). Any "last 12 months" figure includes them.
- **Possible unit mismatch.** Stock and sales may be counted differently, so the huge stock gaps need confirming.
- **Missing information.** The database has no supplier delivery times, reorder levels, safety stock, moving costs or stock history.
- **Login setup.** The default login ignores store restrictions, and `store_manager` has no working password.
- **Small stores.** Low sales volumes make their patterns weaker evidence.
