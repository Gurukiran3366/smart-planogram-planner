# add_positions_to_reference.py
"""
Adds a 'position' field (1-based index) to each product in the expected map.
Position is determined by order within the shelf's products array
(assuming products are already listed left-to-right).
"""

import json
from pathlib import Path

INPUT_FILE = "data/expected_map_BTM_CH01.json"
OUTPUT_FILE = "data/expected_map_BTM_CH01.json"
BACKUP_FILE = "data/expected_map_BTM_CH01_backup_before_positions.json"

# Load current expected map
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

# Backup first
with open(BACKUP_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"✅ Backup saved: {BACKUP_FILE}")

# Add position based on order in the array
for shelf in data["shelves"]:
    products = shelf.get("products", [])
    for idx, product in enumerate(products, start=1):
        product["position"] = idx
    print(f"✅ Shelf {shelf['shelf_number']}: assigned positions 1-{len(products)}")

# Save
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n✅ Updated: {OUTPUT_FILE}")
print(f"\nNext step: Review the file and verify positions match reality!")