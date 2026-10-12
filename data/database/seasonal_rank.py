import os
import argparse
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import psycopg2
from psycopg2.extras import RealDictCursor

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}

def get_db_conn():
    inside_container = os.path.exists("/.dockerenv")
    host = os.getenv("PGHOST")
    if host is None:
        host = "db" if inside_container else "localhost"

    default_port = "5432" if host == "db" else "15432"
    port = int(os.getenv("PGPORT", default_port))
    dbname = os.getenv("PGDATABASE", "zava")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "P@ssw0rd!")

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )
    return conn

def month_name(month_num):
    return MONTH_NAMES.get(int(month_num), str(month_num))

def parse_categories(raw_value):
    if raw_value is None or raw_value.strip().lower() in ("all", ""):
        return None
    return [x.strip() for x in raw_value.split(",") if x.strip()]

def fetch_monthly_data(categories=None, start_date=None, end_date=None, value_field="units"):
    sql = """
        SELECT
            c.category_name,
            EXTRACT(MONTH FROM o.order_date)::int AS month_num,
            SUM(oi.quantity) AS units_sold,
            SUM(oi.total_amount) AS revenue
        FROM retail.orders o
        JOIN retail.order_items oi
          ON o.order_id = oi.order_id
        JOIN retail.products p
          ON oi.product_id = p.product_id
        JOIN retail.categories c
          ON p.category_id = c.category_id
        WHERE 1 = 1
    """

    params = []
    if categories:
        sql += " AND c.category_name = ANY(%s) "
        params.append(categories)

    if start_date:
        sql += " AND o.order_date >= %s "
        params.append(start_date)

    if end_date:
        sql += " AND o.order_date < %s "
        params.append(end_date)

    sql += """
        GROUP BY c.category_name, EXTRACT(MONTH FROM o.order_date)
        ORDER BY c.category_name, month_num
    """

    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return rows

def build_category_summary(rows, value_field="units"):
    data = defaultdict(dict)

    for row in rows:
        cat = row["category_name"]
        month_num = int(row["month_num"])
        if value_field == "units":
            value = float(row["units_sold"])
        elif value_field == "revenue":
            value = float(row["revenue"])
        else:
            raise ValueError(f"Unsupported value_field: {value_field}")
        data[cat][month_num] = value

    summaries = []
    for cat, month_map in data.items():
        peak_month = max(month_map, key=month_map.get)
        trough_month = min(month_map, key=month_map.get)
        peak_value = month_map[peak_month]
        trough_value = month_map[trough_month]
        swing = peak_value - trough_value
        ratio = peak_value / trough_value if trough_value else None
        avg_value = sum(month_map.values()) / len(month_map)
        action_window = [
            month_name(((peak_month - 2 - 1) % 12) + 1),
            month_name(((peak_month - 1 - 1) % 12) + 1)
        ]

        summaries.append({
            "category": cat,
            "peak_month_num": peak_month,
            "peak_month_name": month_name(peak_month),
            "trough_month_num": trough_month,
            "trough_month_name": month_name(trough_month),
            "peak_value": peak_value,
            "trough_value": trough_value,
            "swing": swing,
            "ratio": ratio,
            "avg_value": avg_value,
            "action_window": action_window
        })

    return summaries

def rank_results(summaries, metric="ratio", order="highest", top_n=10):
    if metric == "ratio":
        key = lambda x: x["ratio"] if x["ratio"] is not None else float("-inf")
    elif metric == "swing":
        key = lambda x: x["swing"]
    elif metric == "peak_value":
        key = lambda x: x["peak_value"]
    elif metric == "trough_value":
        key = lambda x: x["trough_value"]
    elif metric == "avg_value":
        key = lambda x: x["avg_value"]
    elif metric == "peak_month_num":
        key = lambda x: x["peak_month_num"]
    else:
        raise ValueError(f"Unsupported metric: {metric}")

    if order == "highest":
        ranked = sorted(summaries, key=key, reverse=True)
    elif order == "lowest":
        ranked = sorted(summaries, key=key)
    else:
        raise ValueError(f"Unsupported order: {order}")

    return ranked[:top_n]

def plot_ranked_results(rows, metric="ratio", output_path=None):
    if not rows:
        return

    labels = [row["category"] for row in rows]
    values = []
    ylabel = metric.replace("_", " ").title()

    for row in rows:
        if metric == "ratio":
            value = row["ratio"] if row["ratio"] is not None else 0
        elif metric == "swing":
            value = row["swing"]
        elif metric == "peak_value":
            value = row["peak_value"]
        elif metric == "trough_value":
            value = row["trough_value"]
        elif metric == "avg_value":
            value = row["avg_value"]
        elif metric == "peak_month_num":
            value = row["peak_month_num"]
        else:
            raise ValueError(f"Unsupported metric: {metric}")
        values.append(value)

    colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#B279A2", "#FF9DA6",
              "#72B7B2", "#EECA3B", "#9D755D", "#BAB0AC"]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(labels, values, color=colors[:len(labels)])
    ax.set_title(f"Top Seasonal Categories by {ylabel}")
    ax.set_xlabel("Category")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=200, bbox_inches="tight")
        print(f"Saved chart to {output_path}")
    else:
        plt.show()
    plt.close(fig)


def print_results(rows):
    print(f"{'Rank':<5} {'Category':<30} {'Peak':<10} {'Trough':<10} {'Peak/Trough':>12} {'Swing':>12} {'Action':<20}")
    print("-" * 100)

    for i, row in enumerate(rows, start=1):
        peak = f"{row['peak_month_name']}({int(row['peak_value'])})"
        trough = f"{row['trough_month_name']}({int(row['trough_value'])})"
        ratio = f"{row['ratio']:.2f}x" if row['ratio'] is not None else "N/A"
        swing = f"{int(row['swing'])}"
        action = ", ".join(row["action_window"])
        print(f"{i:<5} {row['category']:<30} {peak:<10} {trough:<10} {ratio:>12} {swing:>12} {action:<20}")

def main():
    parser = argparse.ArgumentParser(description="Rank seasonal swing by category in the retail dataset.")
    parser.add_argument("--categories", default="ALL", help="Comma-separated category names or ALL")
    parser.add_argument("--start-date", default=None, help="Start date, e.g. 2023-01-01")
    parser.add_argument("--end-date", default=None, help="End date, e.g. 2024-01-01")
    parser.add_argument("--value-field", choices=["units", "revenue"], default="units")
    parser.add_argument("--metric", choices=["ratio", "swing", "peak_value", "trough_value", "avg_value", "peak_month_num"], default="ratio")
    parser.add_argument("--order", choices=["highest", "lowest"], default="highest")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--plot", action="store_true", help="Display or save a matplotlib chart of the ranked results")
    parser.add_argument("--plot-file", default=None, help="Save the plot to a PNG file, e.g. seasonal_rank.png")
    args = parser.parse_args()

    categories = parse_categories(args.categories)
    rows = fetch_monthly_data(categories=categories, start_date=args.start_date, end_date=args.end_date, value_field=args.value_field)
    summaries = build_category_summary(rows, value_field=args.value_field)
    ranked = rank_results(summaries, metric=args.metric, order=args.order, top_n=args.top)
    print_results(ranked)

    if args.plot:
        plot_ranked_results(ranked, metric=args.metric, output_path=args.plot_file)

if __name__ == "__main__":
    main()