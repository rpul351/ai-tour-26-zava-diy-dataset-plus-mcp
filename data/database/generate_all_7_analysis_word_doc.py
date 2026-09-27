import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from docx import Document
from docx.shared import Inches, Pt
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    'host': 'db',
    'port': 5432,
    'dbname': 'zava',
    'user': 'postgres',
    'password': 'P@ssw0rd!',
}

OUTPUT_PATH = '/workspace/data/database/all_7_analysis_db_documentation.docx'
CHART_DIR = Path('/workspace/data/database/word_chart_exports')
CHART_DIR.mkdir(exist_ok=True, parents=True)


def fetch_query(sql, params=None):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    finally:
        conn.close()
    return rows, columns


def add_table(doc, columns, rows, max_rows=8):
    table = doc.add_table(rows=1, cols=len(columns))
    table.style = 'Table Grid'
    hdr = table.rows[0].cells
    for i, col in enumerate(columns):
        hdr[i].text = str(col)

    for i, row in enumerate(rows[:max_rows]):
        cells = table.add_row().cells
        for j, col in enumerate(columns):
            val = row.get(col)
            cells[j].text = '' if val is None else str(val)

    doc.add_paragraph('')


def save_bar_chart(title, x_labels, y_values, x_label, y_label, filename):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x_labels, y_values, color='steelblue')
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    plt.xticks(rotation=30, ha='right')
    fig.tight_layout()
    path = CHART_DIR / filename
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return str(path)


def save_line_chart(title, x_labels, y_values, x_label, y_label, filename):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(x_labels, y_values, marker='o', color='darkgreen')
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    plt.xticks(rotation=30, ha='right')
    fig.tight_layout()
    path = CHART_DIR / filename
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return str(path)


def add_chart_image(doc, image_path):
    if not os.path.exists(image_path):
        return
    doc.add_paragraph('Chart:')
    doc.add_picture(image_path, width=Inches(6.5))
    doc.add_paragraph('')


def build_chart_for_section(section_title, df):
    if df.empty:
        return None

    title = section_title.lower()
    if title.startswith('1. seasonal'):
        return save_bar_chart('Seasonal Swing by Category', list(df['category_name']), list(df['seasonal_swing']), 'Category', 'Seasonal Swing', 'chart_1_seasonal_demand.png')
    if title.startswith('2. store alignment'):
        return save_bar_chart('Store Alignment to National Seasonality', list(df['store_name']), list(df['alignment_index']), 'Store', 'Alignment Index', 'chart_2_store_alignment.png')
    if title.startswith('3. 2023'):
        month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        monthly = df.groupby('month_name', as_index=False)['revenue'].sum().copy()
        monthly['month_name'] = pd.Categorical(monthly['month_name'], categories=month_order, ordered=True)
        monthly = monthly.sort_values('month_name')
        return save_line_chart('2023 Revenue by Month', list(monthly['month_name']), list(monthly['revenue']), 'Month', 'Revenue', 'chart_3_2023_revenue.png')
    if title.startswith('4. product affinity') or title.startswith('5. product pair summary'):
        head = df.head(10).copy()
        labels = [f"{r['product_a_name']} + {r['product_b_name']}" for _, r in head.iterrows()]
        values = list(head['pair_count'])
        return save_bar_chart('Top Product Pairs', labels, values, 'Product Pair', 'Pair Count', 'chart_4_product_affinity.png')
    if title.startswith('6. inventory risk'):
        head = df.head(10).copy()
        labels = [f"{r['surplus_store']} / {r['category_name']}" for _, r in head.iterrows()]
        values = list(head['surplus_to_deficit_ratio'])
        return save_bar_chart('Inventory vs Demand Risk', labels, values, 'Store + Category', 'Surplus/Deficit Ratio', 'chart_6_inventory_risk.png')
    if title.startswith('7. inventory gap'):
        head = df.head(10).copy()
        return save_bar_chart('Largest Inventory Gaps vs Sales Velocity', list(head['product_name']), list(head['inventory_gap']), 'Product', 'Inventory Gap (Stock - Units Sold)', 'chart_7_inventory_gap.png')
    return None


sections = [
    {
        'title': '1. Seasonal Demand Pattern',
        'sql': """
WITH monthly_category_sales AS (
    SELECT c.category_name,
           EXTRACT(MONTH FROM o.order_date)::int AS month_num,
           SUM(oi.quantity) AS units_sold,
           SUM(oi.total_amount) AS revenue
    FROM retail.orders o
    JOIN retail.order_items oi ON oi.order_id = o.order_id
    JOIN retail.products p ON p.product_id = oi.product_id
    JOIN retail.categories c ON c.category_id = p.category_id
    GROUP BY c.category_name, EXTRACT(MONTH FROM o.order_date)::int
),
month_names AS (
    SELECT 1 AS month_num, 'Jan' AS month_name
    UNION ALL SELECT 2, 'Feb' UNION ALL SELECT 3, 'Mar' UNION ALL SELECT 4, 'Apr'
    UNION ALL SELECT 5, 'May' UNION ALL SELECT 6, 'Jun' UNION ALL SELECT 7, 'Jul'
    UNION ALL SELECT 8, 'Aug' UNION ALL SELECT 9, 'Sep' UNION ALL SELECT 10, 'Oct'
    UNION ALL SELECT 11, 'Nov' UNION ALL SELECT 12, 'Dec'
),
category_months AS (
    SELECT s.category_name, m.month_num, m.month_name,
           COALESCE(s.units_sold, 0) AS units_sold,
           COALESCE(s.revenue, 0) AS revenue
    FROM (SELECT DISTINCT category_name FROM retail.categories) cat
    CROSS JOIN month_names m
    LEFT JOIN monthly_category_sales s
      ON s.category_name = cat.category_name AND s.month_num = m.month_num
),
normalized AS (
    SELECT category_name, month_num, month_name, units_sold,
           AVG(units_sold) OVER (PARTITION BY category_name) AS avg_units,
           units_sold / NULLIF(AVG(units_sold) OVER (PARTITION BY category_name), 0) AS seasonal_index
    FROM category_months
),
ranked AS (
    SELECT *,
           MAX(seasonal_index) OVER (PARTITION BY category_name) AS peak_index,
           MIN(seasonal_index) OVER (PARTITION BY category_name) AS low_index,
           ROW_NUMBER() OVER (PARTITION BY category_name ORDER BY seasonal_index DESC) AS peak_rank,
           ROW_NUMBER() OVER (PARTITION BY category_name ORDER BY seasonal_index ASC) AS low_rank
    FROM normalized
),
summary AS (
    SELECT DISTINCT category_name,
           peak_index - low_index AS seasonal_swing,
           peak_index,
           low_index
    FROM ranked
)
SELECT category_name,
       seasonal_swing,
       (SELECT month_name FROM ranked r WHERE r.category_name = s.category_name AND r.peak_rank = 1) AS peak_month,
       (SELECT month_name FROM ranked r WHERE r.category_name = s.category_name AND r.low_rank = 1) AS low_month
FROM summary s
ORDER BY seasonal_swing DESC;
        """,
    },
    {
        'title': '2. Store Alignment to National Seasonality',
        'sql': """
WITH store_weights AS (
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
SELECT s.store_name,
       sw.customer_distribution_weight AS customer_weight,
       sw.order_frequency_multiplier AS frequency_multiplier,
       sw.customer_distribution_weight * sw.order_frequency_multiplier AS alignment_index
FROM retail.stores s
JOIN store_weights sw ON sw.store_name = s.store_name
ORDER BY alignment_index DESC;
        """,
    },
    {
        'title': '3. 2023 Sales Snapshot',
        'sql': """
SELECT EXTRACT(MONTH FROM o.order_date)::int AS month_num,
       TO_CHAR(o.order_date, 'Mon') AS month_name,
       c.category_name,
       SUM(oi.quantity) AS units_sold,
       SUM(oi.total_amount) AS revenue
FROM retail.orders o
JOIN retail.order_items oi ON oi.order_id = o.order_id
JOIN retail.products p ON p.product_id = oi.product_id
JOIN retail.categories c ON c.category_id = p.category_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2023
GROUP BY EXTRACT(MONTH FROM o.order_date)::int, TO_CHAR(o.order_date, 'Mon'), c.category_name
ORDER BY month_num, category_name;
        """,
    },
    {
        'title': '4. Product Affinity and Cross-Sell Signals',
        'sql': """
WITH order_pairs AS (
    SELECT oi1.order_id,
           oi1.store_id,
           CASE WHEN oi1.product_id < oi2.product_id THEN oi1.product_id ELSE oi2.product_id END AS product_a,
           CASE WHEN oi1.product_id < oi2.product_id THEN oi2.product_id ELSE oi1.product_id END AS product_b
    FROM retail.order_items oi1
    JOIN retail.order_items oi2
      ON oi1.order_id = oi2.order_id
     AND oi1.product_id < oi2.product_id
),
pair_summary AS (
    SELECT op.product_a,
           op.product_b,
           p1.product_name AS product_a_name,
           p2.product_name AS product_b_name,
           COUNT(*) AS pair_count
    FROM order_pairs op
    JOIN retail.products p1 ON p1.product_id = op.product_a
    JOIN retail.products p2 ON p2.product_id = op.product_b
    GROUP BY op.product_a, op.product_b, p1.product_name, p2.product_name
)
SELECT *
FROM pair_summary
ORDER BY pair_count DESC, product_a_name
LIMIT 20;
        """,
    },
    {
        'title': '5. Product Pair Summary',
        'sql': """
WITH order_pairs AS (
    SELECT CASE WHEN oi1.product_id < oi2.product_id THEN oi1.product_id ELSE oi2.product_id END AS product_a,
           CASE WHEN oi1.product_id < oi2.product_id THEN oi2.product_id ELSE oi1.product_id END AS product_b
    FROM retail.order_items oi1
    JOIN retail.order_items oi2
      ON oi1.order_id = oi2.order_id
     AND oi1.product_id < oi2.product_id
)
SELECT p1.product_name AS product_a_name,
       p2.product_name AS product_b_name,
       COUNT(*) AS pair_count
FROM order_pairs op
JOIN retail.products p1 ON p1.product_id = op.product_a
JOIN retail.products p2 ON p2.product_id = op.product_b
GROUP BY p1.product_name, p2.product_name
ORDER BY pair_count DESC
LIMIT 20;
        """,
    },
    {
        'title': '6. Inventory Risk by Store',
        'sql': """
WITH store_weights AS (
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
),
store_demand AS (
    SELECT s.store_name,
           c.category_name,
           SUM(oi.quantity) AS units_sold,
           SUM(oi.total_amount) AS demand_revenue,
           SUM(oi.quantity) * sw.customer_distribution_weight * sw.order_frequency_multiplier AS weighted_demand_index
    FROM retail.orders o
    JOIN retail.order_items oi ON oi.order_id = o.order_id
    JOIN retail.products p ON p.product_id = oi.product_id
    JOIN retail.categories c ON c.category_id = p.category_id
    JOIN retail.stores s ON s.store_id = o.store_id
    JOIN store_weights sw ON sw.store_name = s.store_name
    GROUP BY s.store_name, c.category_name, sw.customer_distribution_weight, sw.order_frequency_multiplier
),
store_inventory AS (
    SELECT s.store_name,
           c.category_name,
           SUM(i.stock_level) AS inventory_units
    FROM retail.inventory i
    JOIN retail.products p ON p.product_id = i.product_id
    JOIN retail.categories c ON c.category_id = p.category_id
    JOIN retail.stores s ON s.store_id = i.store_id
    GROUP BY s.store_name, c.category_name
),
inventory_vs_demand AS (
    SELECT d.store_name AS demand_store,
           d.category_name,
           d.weighted_demand_index,
           inv.inventory_units,
           inv.inventory_units / NULLIF(d.weighted_demand_index, 0) AS inventory_to_demand_ratio
    FROM store_demand d
    JOIN store_inventory inv
      ON inv.store_name = d.store_name AND inv.category_name = d.category_name
)
SELECT a.demand_store AS surplus_store,
       a.category_name,
       a.inventory_units AS surplus_inventory,
       a.inventory_to_demand_ratio AS surplus_ratio,
       b.demand_store AS deficit_store,
       b.inventory_units AS deficit_inventory,
       b.inventory_to_demand_ratio AS deficit_ratio,
       a.inventory_units / NULLIF(b.inventory_units, 0) AS surplus_to_deficit_ratio
FROM inventory_vs_demand a
JOIN inventory_vs_demand b
  ON a.category_name = b.category_name AND a.demand_store <> b.demand_store
WHERE a.inventory_to_demand_ratio >= 1.5
  AND b.inventory_to_demand_ratio <= 0.7
ORDER BY a.category_name, a.inventory_to_demand_ratio DESC, surplus_to_deficit_ratio DESC
LIMIT 20;
        """,
    },
    {
        'title': '7. Inventory Gap vs. Sales Velocity',
        'sql': """
WITH product_sales AS (
    SELECT p.product_id,
           p.product_name,
           SUM(oi.quantity) AS units_sold,
           SUM(oi.total_amount) AS sales_revenue
    FROM retail.order_items oi
    JOIN retail.products p ON p.product_id = oi.product_id
    GROUP BY p.product_id, p.product_name
),
product_inventory AS (
    SELECT i.product_id,
           SUM(i.stock_level) AS total_stock
    FROM retail.inventory i
    GROUP BY i.product_id
)
SELECT ps.product_name,
       ps.units_sold,
       COALESCE(pi.total_stock, 0) AS total_stock,
       COALESCE(pi.total_stock, 0) - ps.units_sold AS inventory_gap,
       CASE WHEN ps.units_sold = 0 THEN 0
            ELSE (COALESCE(pi.total_stock, 0) / ps.units_sold)::numeric(12,2)
       END AS stock_to_sales_ratio
FROM product_sales ps
LEFT JOIN product_inventory pi ON pi.product_id = ps.product_id
ORDER BY ABS(COALESCE(pi.total_stock, 0) - ps.units_sold) DESC, ps.units_sold DESC
LIMIT 20;
        """,
    },
    {
        'title': '8. Super Manager vs Store Manager RLS Comparison',
        'sql': """
SELECT store_id, store_name, rls_user_id::text AS rls_user_id
FROM retail.stores
ORDER BY store_name;
        """,
    },
]


def build_rls_summary():
    SUPER_MANAGER_UUID = '00000000-0000-0000-0000-000000000000'
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT store_id, store_name, rls_user_id::text AS rls_user_id FROM retail.stores ORDER BY store_name;")
            stores = cur.fetchall()
            selected_store = stores[0]
            selected_rls = selected_store['rls_user_id']
            cur.execute("SELECT set_config('app.current_rls_user_id', %s, false)", (SUPER_MANAGER_UUID,))
            cur.execute("SELECT COUNT(*) AS order_count FROM retail.orders")
            super_rows = cur.fetchall()
            cur.execute("SELECT set_config('app.current_rls_user_id', %s, false)", (selected_rls,))
            cur.execute("SELECT COUNT(*) AS order_count FROM retail.orders")
            store_rows = cur.fetchall()
    finally:
        conn.close()

    return pd.DataFrame({
        'View': ['Super Manager (All Stores)', 'Selected Store View'],
        'order_count': [super_rows[0]['order_count'], store_rows[0]['order_count']],
    })


def main():
    doc = Document()
    doc.add_heading('Zava Retail Analysis Report', 0)
    doc.add_paragraph('This document captures the SQL, sample outputs, and chart summaries for the consolidated analysis workflow in the Zava retail database.')
    doc.add_paragraph('Database: zava | Host: db | Schema: retail')

    for section in sections:
        doc.add_heading(section['title'], level=1)
        doc.add_paragraph('SQL used:')
        para = doc.add_paragraph(section['sql'].strip())
        para.runs[0].font.size = Pt(9)

        rows, columns = fetch_query(section['sql'])
        doc.add_paragraph('Sample output:')
        add_table(doc, columns, rows, max_rows=8)

        if section['title'] == '8. Super Manager vs Store Manager RLS Comparison':
            rls_df = build_rls_summary()
            chart_path = save_bar_chart('RLS View Comparison', list(rls_df['View']), list(rls_df['order_count']), 'View', 'Order Count', 'chart_8_rls_comparison.png')
            add_chart_image(doc, chart_path)
        else:
            if rows:
                df = pd.DataFrame(rows, columns=columns)
                chart_path = build_chart_for_section(section['title'], df)
                if chart_path:
                    add_chart_image(doc, chart_path)

    doc.save(OUTPUT_PATH)
    print(f'Word document created: {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
