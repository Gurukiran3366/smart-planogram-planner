# fix_positions_with_facings.py
"""
Updates expected_map to use slot-based positioning that accounts for facings.
A product with 2 facings occupies 2 slots.
"""

import json
from pathlib import Path
from datetime import datetime

INPUT_FILE = "data/expected_map_BTM_CH01.json"
BACKUP_FILE = f"data/expected_map_BTM_CH01_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

# Load current expected map
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

# Backup first
with open(BACKUP_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"✅ Backup saved: {BACKUP_FILE}")

# Add slot_start and slot_end based on facings
for shelf in data["shelves"]:
    shelf_num = shelf["shelf_number"]
    products = shelf.get("products", [])
    
    current_slot = 1
    total_slots = 0
    
    for product in products:
        facings = product.get("facings", 1)
        
        # Remove old 'position' field (replace with slot_start/slot_end)
        product.pop("position", None)
        
        # Add slot range
        product["slot_start"] = current_slot
        product["slot_end"] = current_slot + facings - 1
        
        current_slot += facings
        total_slots += facings
    
    print(f"✅ Shelf {shelf_num}: {len(products)} products occupying {total_slots} total slots")

# Save
with open(INPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n✅ Updated: {INPUT_FILE}")
print(f"\nExample of new format:")
print(f"  Coca-Cola with facings=2 → slot_start=3, slot_end=4")
print(f"  Next product starts at slot 5, not slot 4")