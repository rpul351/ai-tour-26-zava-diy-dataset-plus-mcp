import psycopg2
from psycopg2.extras import RealDictCursor

def inventory_misalignment_query():
    conn = psycopg2.connect(
        host="db",
        port=5432,
        dbname="zava",
        user="postgres",
        password="P@ssw0rd!"
    )

    sql = """
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
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    conn.close()
    return rows


if __name__ == "__main__":
    results = inventory_misalignment_query()
    print(f"Rows returned: {len(results)}")
    for r in results[:20]:
        print(
            f"Surplus store: {r['surplus_store']}, "
            f"Category: {r['category_name']}, "
            f"Surplus inventory: {r['surplus_inventory']}, "
            f"Surplus ratio: {r['surplus_ratio']}, "
            f"Deficit store: {r['deficit_store']}, "
            f"Deficit ratio: {r['deficit_ratio']}"
        )