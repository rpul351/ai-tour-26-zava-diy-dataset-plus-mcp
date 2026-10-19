import argparse
import json
from pathlib import Path

import matplotlib

try:
    matplotlib.use("module://matplotlib_inline.backend_inline")
except Exception:
    pass

import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description="Analyze seasonal sales multipliers.")
    parser.add_argument("--save", action="store_true", help="Save a PNG copy of the chart instead of showing it in VS Code.")
    parser.add_argument("--show", action="store_true", help="Display the chart in the current Python environment.")
    args = parser.parse_args()
    # Path to the seasonal config file
    path = Path("/workspace/data/database/product_data.json")
    data = json.loads(path.read_text())

    categories = data.get("main_categories", {})

    results = []

    for category, cfg in categories.items():
        multipliers = cfg.get("washington_seasonal_multipliers")
        if not isinstance(multipliers, list):
            continue

        peak_index = max(range(len(multipliers)), key=lambda i: multipliers[i])
        low_index = min(range(len(multipliers)), key=lambda i: multipliers[i])

        peak_month = peak_index + 1
        low_month = low_index + 1
        swing = max(multipliers) - min(multipliers)

        results.append({
            "category": category,
            "peak_month": peak_month,
            "low_month": low_month,
            "peak_multiplier": round(max(multipliers), 2),
            "low_multiplier": round(min(multipliers), 2),
            "swing": round(swing, 2),
        })

    # Rank by largest swing
    results.sort(key=lambda x: x["swing"], reverse=True)

    print("Seasonal swing by category:")
    for r in results:
        print(
            f"{r['category']:<35} "
            f"swing={r['swing']:>4.2f} | "
            f"peak_month={r['peak_month']} | "
            f"low_month={r['low_month']} | "
            f"peak_mult={r['peak_multiplier']} | "
            f"low_mult={r['low_multiplier']}"
        )

    top = results[0]
    print("\nSharpest seasonal swing:")
    print(f"{top['category']} with swing {top['swing']}")
    print(f"Peak month: {top['peak_month']}, low month: {top['low_month']}")
    print(f"Recommended action window: {max(1, top['low_month'] - 1)} to {top['peak_month'] - 1} months ahead of the peak.")

    chart_data = results[:5]
    categories_for_chart = [r["category"] for r in chart_data]
    swings = [r["swing"] for r in chart_data]

    plt.figure(figsize=(10, 6))
    bars = plt.bar(categories_for_chart, swings, color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"])
    plt.title("Top Seasonal Swing by Category")
    plt.xlabel("Category")
    plt.ylabel("Swing (max - min multipliers)")
    plt.xticks(rotation=25, ha="right")
    plt.grid(axis="y", alpha=0.3)

    for bar, value in zip(bars, swings):
        plt.text(bar.get_x() + bar.get_width() / 2, value + 0.05, f"{value:.2f}", ha="center", va="bottom")

    plt.tight_layout()

    output_path = Path("/workspace/data/database/seasonal_analysis.png")
    if args.save or not args.show:
        plt.savefig(output_path, dpi=200)
        print(f"\nSaved seasonal chart to: {output_path}")
    else:
        plt.show()

    plt.close()

if __name__ == "__main__":
    main()

