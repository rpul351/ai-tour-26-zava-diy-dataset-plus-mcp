import json
from pathlib import Path

def main():
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

if __name__ == "__main__":
    main()
    