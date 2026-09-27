--select  * from retail.categories 


--1) Which category has the sharpest seasonal swing, and how far ahead would you need to act on it?

WITH category_season AS (
  SELECT * FROM (VALUES
    ('HAND TOOLS', ARRAY[1.0,1.0,1.2,1.4,1.6,1.5,1.5,1.4,1.2,1.1,1.0,0.9]),
    ('POWER TOOLS', ARRAY[0.9,0.9,1.1,1.5,1.8,2.0,2.1,1.9,1.4,1.2,1.0,0.8]),
    ('PAINT & FINISHES', ARRAY[1.2,1.1,1.8,2.2,2.0,1.9,1.8,1.6,1.3,1.1,1.0,1.2]),
    ('HARDWARE', ARRAY[1.0,1.0,1.1,1.3,1.2,1.1,1.0,1.0,1.4,1.8,1.6,1.2]),
    ('LUMBER & BUILDING MATERIALS', ARRAY[0.8,0.7,1.2,1.6,2.0,2.2,2.1,1.8,1.3,1.0,0.8,0.7]),
    ('ELECTRICAL', ARRAY[1.2,1.1,1.0,1.1,1.2,1.3,1.2,1.1,1.2,1.4,1.6,1.5]),
    ('PLUMBING', ARRAY[1.1,1.0,1.2,1.4,1.3,1.2,1.1,1.0,1.3,1.6,1.4,1.2]),
    ('GARDEN & OUTDOOR', ARRAY[0.6,0.5,1.5,2.5,2.2,1.8,1.6,1.4,1.3,1.0,0.7,0.5]),
    ('STORAGE & ORGANIZATION', ARRAY[1.4,1.6,1.2,1.0,0.9,0.8,0.8,0.9,1.1,1.2,1.3,1.8])
  ) AS t(category, multipliers)
),
months AS (
  SELECT 1 AS month_num, 'Jan' AS month_name
  UNION ALL SELECT 2, 'Feb'
  UNION ALL SELECT 3, 'Mar'
  UNION ALL SELECT 4, 'Apr'
  UNION ALL SELECT 5, 'May'
  UNION ALL SELECT 6, 'Jun'
  UNION ALL SELECT 7, 'Jul'
  UNION ALL SELECT 8, 'Aug'
  UNION ALL SELECT 9, 'Sep'
  UNION ALL SELECT 10, 'Oct'
  UNION ALL SELECT 11, 'Nov'
  UNION ALL SELECT 12, 'Dec'
),
expanded AS (
  SELECT
    c.category,
    m.month_num,
    m.month_name,
    c.multipliers[m.month_num] AS multiplier
  FROM category_season c
  CROSS JOIN months m
),
ranked AS (
  SELECT
    *,
    MAX(multiplier) OVER (PARTITION BY category) AS peak_mult,
    MIN(multiplier) OVER (PARTITION BY category) AS low_mult,
    ROW_NUMBER() OVER (PARTITION BY category ORDER BY multiplier DESC) AS peak_rank,
    ROW_NUMBER() OVER (PARTITION BY category ORDER BY multiplier ASC) AS low_rank
  FROM expanded
),
summary AS (
  SELECT DISTINCT
    category,
    peak_mult - low_mult AS seasonal_swing,
    peak_mult,
    low_mult
  FROM ranked
)
SELECT
  category,
  seasonal_swing,
  (SELECT month_name FROM ranked r WHERE r.category = s.category AND r.peak_rank = 1) AS peak_month,
  (SELECT month_name FROM ranked r WHERE r.category = s.category AND r.low_rank = 1) AS low_month
FROM summary s
ORDER BY seasonal_swing DESC;


--query 2- Which stores are most and least aligned to the national seasonal pattern?
WITH store_profile AS (
  SELECT * FROM (VALUES
    ('Zava Retail Seattle', 30, 3.0),
    ('Zava Retail Bellevue', 25, 2.6),
    ('Zava Retail Tacoma', 20, 2.4),
    ('Zava Retail Spokane', 8, 2.0),
    ('Zava Retail Everett', 7, 1.8),
    ('Zava Retail Redmond', 6, 1.6),
    ('Zava Retail Kirkland', 4, 1.4),
    ('Zava Retail Online', 30, 3.0)
  ) AS t(store_name, customer_distribution_weight, order_frequency_multiplier)
)
SELECT
  store_name,
  customer_distribution_weight,
  order_frequency_multiplier,
  customer_distribution_weight * order_frequency_multiplier AS alignment_index
FROM store_profile
ORDER BY alignment_index DESC;


----------
-- query 3 - What actually happened in 2023? Which categories, which stores, which months?
WITH category_seasonality AS (
  SELECT *
  FROM (
    VALUES
      ('Garden & Outdoor', ARRAY[0.70,0.82,1.10,1.75,2.30,2.10,1.80,1.50,1.40,1.20,1.00,0.90]),
      ('Lumber & Building Materials', ARRAY[0.75,0.90,1.20,1.80,2.00,2.20,1.90,1.60,1.50,1.40,1.20,1.10]),
      ('Power Tools', ARRAY[0.85,0.90,1.00,1.05,1.25,1.55,2.10,1.95,1.70,1.35,1.10,0.80]),
      ('Paint & Finishes', ARRAY[0.90,1.00,1.20,2.20,1.80,1.40,1.20,1.10,1.05,1.00,1.10,0.95]),
      ('Hardware', ARRAY[0.95,0.98,1.10,1.25,1.50,1.75,1.80,1.60,1.35,1.20,1.10,1.05])
  ) AS v(category, multipliers)
),
expanded AS (
  SELECT
    category,
    month_no,
    multiplier
  FROM category_seasonality
  CROSS JOIN UNNEST(multipliers) WITH ORDINALITY AS u(multiplier, month_no)
),
ranked AS (
  SELECT
    category,
    month_no AS peak_month,
    multiplier AS peak_multiplier,
    ROW_NUMBER() OVER (
      PARTITION BY category
      ORDER BY multiplier DESC
    ) AS rn_peak,
    MIN(multiplier) OVER (PARTITION BY category) AS low_multiplier,
    MAX(multiplier) OVER (PARTITION BY category) AS high_multiplier
  FROM expanded
)
SELECT
  category,
  MAX(CASE WHEN rn_peak = 1 THEN peak_month END) AS peak_month,
  MAX(CASE WHEN rn_peak = 1 THEN peak_multiplier END) AS peak_multiplier,
  MAX(high_multiplier) - MIN(low_multiplier) AS swing
FROM ranked
GROUP BY category
ORDER BY swing DESC;


---------

-- query 4 - Which products are frequently bought together, and does that differ by store or season?


WITH order_pairs AS (
    SELECT
        oi1.order_id,
        oi1.store_id,
        CASE
            WHEN oi1.product_id < oi2.product_id THEN oi1.product_id
            ELSE oi2.product_id
        END AS product_a,
        CASE
            WHEN oi1.product_id < oi2.product_id THEN oi2.product_id
            ELSE oi1.product_id
        END AS product_b,
        CASE
            WHEN EXTRACT(MONTH FROM o.order_date) IN (3,4,5) THEN 'Spring'
            WHEN EXTRACT(MONTH FROM o.order_date) IN (6,7,8) THEN 'Summer'
            WHEN EXTRACT(MONTH FROM o.order_date) IN (9,10,11) THEN 'Fall'
            ELSE 'Winter'
        END AS season
    FROM retail.order_items oi1
    JOIN retail.order_items oi2
      ON oi1.order_id = oi2.order_id
     AND oi1.product_id < oi2.product_id
    JOIN retail.orders o
      ON o.order_id = oi1.order_id
),
pair_summary AS (
    SELECT
        op.season,
        s.store_name,
        p1.product_name AS product_a_name,
        p2.product_name AS product_b_name,
        COUNT(*) AS pair_count
    FROM order_pairs op
    JOIN retail.stores s
      ON s.store_id = op.store_id
    JOIN retail.products p1
      ON p1.product_id = op.product_a
    JOIN retail.products p2
      ON p2.product_id = op.product_b
    GROUP BY
        op.season,
        s.store_name,
        p1.product_name,
        p2.product_name
)
SELECT
    season,
    store_name,
    product_a_name,
    product_b_name,
    pair_count
FROM pair_summary
WHERE pair_count >= 5
ORDER BY season, store_name, pair_count DESC;

--4.1 

WITH order_pairs AS (
    SELECT
        oi1.order_id,
        CASE
            WHEN oi1.product_id < oi2.product_id THEN oi1.product_id
            ELSE oi2.product_id
        END AS product_a,
        CASE
            WHEN oi1.product_id < oi2.product_id THEN oi2.product_id
            ELSE oi1.product_id
        END AS product_b
    FROM retail.order_items oi1
    JOIN retail.order_items oi2
      ON oi1.order_id = oi2.order_id
     AND oi1.product_id < oi2.product_id
)
SELECT
    p1.product_name AS product_a_name,
    p2.product_name AS product_b_name,
    COUNT(*) AS pair_count
FROM order_pairs op
JOIN retail.products p1
  ON p1.product_id = op.product_a
JOIN retail.products p2
  ON p2.product_id = op.product_b
GROUP BY p1.product_name, p2.product_name
HAVING COUNT(*) >= 5
ORDER BY pair_count DESC
LIMIT 50;


-- Query 5 - Where is inventory misaligned with demand? Are there stores holding stock that another store needs?

WITH store_weights AS (
    SELECT *
    FROM (VALUES
        ('Zava Retail Seattle', 30, 3.0),
        ('Zava Retail Bellevue', 25, 2.6),
        ('Zava Retail Tacoma', 20, 2.4),
        ('Zava Retail Spokane', 8, 2.0),
        ('Zava Retail Everett', 7, 1.8),
        ('Zava Retail Redmond', 6, 1.6),
        ('Zava Retail Kirkland', 4, 1.4),
        ('Zava Retail Online', 30, 3.0)
    ) AS t(store_name, customer_distribution_weight, order_frequency_multiplier)
),
store_demand AS (
    SELECT
        s.store_name,
        c.category_name,
        SUM(oi.quantity) AS units_sold,
        SUM(oi.total_amount) AS demand_revenue,
        SUM(oi.quantity) * sw.customer_distribution_weight * sw.order_frequency_multiplier AS weighted_demand_index
    FROM retail.orders o
    JOIN retail.order_items oi
      ON oi.order_id = o.order_id
    JOIN retail.products p
      ON p.product_id = oi.product_id
    JOIN retail.categories c
      ON c.category_id = p.category_id
    JOIN retail.stores s
      ON s.store_id = o.store_id
    JOIN store_weights sw
      ON sw.store_name = s.store_name
    GROUP BY s.store_name, c.category_name, sw.customer_distribution_weight, sw.order_frequency_multiplier
),
store_inventory AS (
    SELECT
        s.store_name,
        c.category_name,
        SUM(i.stock_level) AS inventory_units
    FROM retail.inventory i
    JOIN retail.products p
      ON p.product_id = i.product_id
    JOIN retail.categories c
      ON c.category_id = p.category_id
    JOIN retail.stores s
      ON s.store_id = i.store_id
    GROUP BY s.store_name, c.category_name
),
inventory_vs_demand AS (
    SELECT
        d.store_name AS demand_store,
        d.category_name,
        d.weighted_demand_index,
        inv.inventory_units,
        inv.inventory_units / NULLIF(d.weighted_demand_index, 0) AS inventory_to_demand_ratio
    FROM store_demand d
    JOIN store_inventory inv
      ON inv.store_name = d.store_name
     AND inv.category_name = d.category_name
)
SELECT
    a.demand_store AS surplus_store,
    a.category_name,
    a.inventory_units AS surplus_inventory,
    a.inventory_to_demand_ratio AS surplus_ratio,
    b.demand_store AS deficit_store,
    b.inventory_units AS deficit_inventory,
    b.inventory_to_demand_ratio AS deficit_ratio,
    a.inventory_units / NULLIF(b.inventory_units, 0) AS surplus_to_deficit_ratio
FROM inventory_vs_demand a
JOIN inventory_vs_demand b
  ON a.category_name = b.category_name
 AND a.demand_store <> b.demand_store
WHERE a.inventory_to_demand_ratio >= 1.5
  AND b.inventory_to_demand_ratio <= 0.7
ORDER BY a.category_name, a.inventory_to_demand_ratio DESC, surplus_to_deficit_ratio DESC;