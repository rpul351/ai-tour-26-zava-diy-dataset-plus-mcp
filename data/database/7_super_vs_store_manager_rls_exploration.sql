-- =========================================================
-- Super Manager vs Store Manager RLS Comparison
-- =========================================================
-- Purpose:
-- Compare what a super manager can see versus a single store manager when
-- Row Level Security (RLS) is enabled on the retail schema.
--
-- Run this in PostgreSQL against the zava database.
-- =========================================================

-- 1) View the stores and their manager RLS IDs
SELECT
    store_id,
    store_name,
    rls_user_id::text AS rls_user_id
FROM retail.stores
ORDER BY store_name;

-- 2) Super manager view: bypasses all store restrictions
SELECT set_config('app.current_rls_user_id', '00000000-0000-0000-0000-000000000000', false);

SELECT 'Super Manager' AS view_name,
       COUNT(*) AS order_count
FROM retail.orders;

SELECT 'Super Manager' AS view_name,
       COUNT(*) AS customer_count
FROM retail.customers;

SELECT 'Super Manager' AS view_name,
       COUNT(*) AS inventory_count
FROM retail.inventory;

-- 3) Example: switch to a single store manager context
-- Replace this store name with any store you want to inspect
SELECT set_config(
    'app.current_rls_user_id',
    (
        SELECT rls_user_id::text
        FROM retail.stores
        WHERE store_name = 'Zava Retail Seattle'
        LIMIT 1
    ),
    false
);

SELECT current_setting('app.current_rls_user_id', true) AS current_rls_user_id;

SELECT 'Single Store Manager' AS view_name,
       COUNT(*) AS order_count
FROM retail.orders;

SELECT 'Single Store Manager' AS view_name,
       COUNT(*) AS customer_count
FROM retail.customers;

SELECT 'Single Store Manager' AS view_name,
       COUNT(*) AS inventory_count
FROM retail.inventory;

-- 4) Side-by-side comparison using a single query
WITH super_view AS (
    SELECT set_config('app.current_rls_user_id', '00000000-0000-0000-0000-000000000000', false)
),
store_view AS (
    SELECT set_config(
        'app.current_rls_user_id',
        (
            SELECT rls_user_id::text
            FROM retail.stores
            WHERE store_name = 'Zava Retail Seattle'
            LIMIT 1
        ),
        false
    )
),
metrics AS (
    SELECT 'Super Manager' AS view_name, COUNT(*) AS order_count FROM retail.orders
    UNION ALL
    SELECT 'Single Store Manager' AS view_name, COUNT(*) AS order_count FROM retail.orders
)
SELECT * FROM metrics;

-- 5) Store-specific customer view for the selected manager
SELECT
    c.customer_id,
    c.first_name,
    c.last_name,
    c.primary_store_id,
    s.store_name
FROM retail.customers c
JOIN retail.stores s ON s.store_id = c.primary_store_id
WHERE s.rls_user_id::text = current_setting('app.current_rls_user_id', true)
ORDER BY c.customer_id
LIMIT 20;

-- 6) Store-specific inventory view for the selected manager
SELECT
    i.store_id,
    s.store_name,
    i.product_id,
    p.product_name,
    i.stock_level
FROM retail.inventory i
JOIN retail.stores s ON s.store_id = i.store_id
JOIN retail.products p ON p.product_id = i.product_id
WHERE s.rls_user_id::text = current_setting('app.current_rls_user_id', true)
ORDER BY i.store_id, i.product_id
LIMIT 20;
