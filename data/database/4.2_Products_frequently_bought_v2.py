import psycopg2
from psycopg2.extras import RealDictCursor

def fetch_bought_together_global(min_pair_count=5):
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
    HAVING COUNT(*) >= %s
    ORDER BY pair_count DESC
    LIMIT 50;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (min_pair_count,))
        rows = cur.fetchall()

    conn.close()
    return rows


if __name__ == "__main__":
    results = fetch_bought_together_global(min_pair_count=5)
    for row in results:
        print(f"{row['product_a_name']} + {row['product_b_name']} | count={row['pair_count']}")