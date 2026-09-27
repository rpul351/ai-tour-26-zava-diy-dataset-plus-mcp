store_data = [
    ("Zava Retail Seattle", 30, 3.0),
    ("Zava Retail Bellevue", 25, 2.6),
    ("Zava Retail Tacoma", 20, 2.4),
    ("Zava Retail Spokane", 8, 2.0),
    ("Zava Retail Everett", 7, 1.8),
    ("Zava Retail Redmond", 6, 1.6),
    ("Zava Retail Kirkland", 4, 1.4),
    ("Zava Retail Online", 30, 3.0),
]

rows = []
for store, weight, freq in store_data:
    alignment = weight * freq
    rows.append((store, weight, freq, alignment))

rows.sort(key=lambda x: x[3], reverse=True)

print("Most aligned to national seasonal pattern:")
for r in rows:
    print(f"{r[0]} -> weight={r[1]}, freq={r[2]}, alignment_index={r[3]}")

print("\nLeast aligned:")
for r in reversed(rows):
    print(f"{r[0]} -> weight={r[1]}, freq={r[2]}, alignment_index={r[3]}")