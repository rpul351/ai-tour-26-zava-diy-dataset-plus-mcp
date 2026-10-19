import psycopg2
from psycopg2.extras import RealDictCursor

def fetch_bought_together(min_pair_count=5):
    conn = psycopg2.connect(
        host="db",
        port=5432,
        dbname="zava",
        user="postgres",
        password="P@ssw0rd!"
    )

    sql = """
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
                WHEN EXTRACT(MONTH FROM o.order_date) IN (3, 4, 5) THEN 'Spring'
                WHEN EXTRACT(MONTH FROM o.order_date) IN (6, 7, 8) THEN 'Summer'
                WHEN EXTRACT(MONTH FROM o.order_date) IN (9, 10, 11) THEN 'Fall'
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
    WHERE pair_count >= %s
    ORDER BY season, store_name, pair_count DESC;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (min_pair_count,))
        rows = cur.fetchall()

    conn.close()
    return rows


if __name__ == "__main__":
    results = fetch_bought_together(min_pair_count=5)

    if not results:
        print("No product pairs met the threshold.")
    else:
        for row in results:
            print(
                f"{row['season']} | {row['store_name']} | "
                f"{row['product_a_name']} + {row['product_b_name']} | "
                f"count={row['pair_count']}"
            )