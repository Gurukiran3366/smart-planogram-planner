# diagnose_naming.py
"""
Diagnose ID mismatches between products.xlsx and expected_map_BTM_CH01.json
"""
import json
import pandas as pd
from pathlib import Path

CATALOG_FILE = "data/products.xlsx"
EXPECTED_MAP_FILE = "data/expected_map_BTM_CH01.json"

print("=" * 70)
print("PRODUCT ID CONSISTENCY CHECK")
print("=" * 70)

# Load catalog
products_df = pd.read_excel(CATALOG_FILE)
catalog_ids = set(products_df["product_id"].astype(str))
print(f"\n📚 Catalog has {len(catalog_ids)} products")

# Load expected map
with open(EXPECTED_MAP_FILE, "r", encoding="utf-8") as f:
    expected = json.load(f)

expected_ids = set()
for shelf in expected["shelves"]:
    for product in shelf.get("products", []):
        expected_ids.add(product["product_id"])

print(f"📋 Expected map uses {len(expected_ids)} unique product IDs\n")

# Find mismatches
in_expected_not_in_catalog = expected_ids - catalog_ids
in_catalog_not_in_expected = catalog_ids - expected_ids

print("=" * 70)
print("❌ IDS IN EXPECTED_MAP BUT NOT IN CATALOG (broken references)")
print("=" * 70)
if in_expected_not_in_catalog:
    print("These will cause 'missing product' errors:\n")
    for pid in sorted(in_expected_not_in_catalog):
        # Find similar IDs in catalog
        similar = [c for c in catalog_ids if pid[:5] in c or c[:5] in pid]
        print(f"  • {pid}")
        if similar:
            print(f"    Similar in catalog: {similar[:3]}")
        else:
            print(f"    No similar IDs found")
        print()
else:
    print("✅ None - all expected_map IDs exist in catalog")

print("\n" + "=" * 70)
print("📝 IDS IN CATALOG BUT NEVER USED IN EXPECTED_MAP")
print("=" * 70)
if in_catalog_not_in_expected:
    print("These products won't be checked against reference:\n")
    for pid in sorted(in_catalog_not_in_expected):
        print(f"  • {pid}")
else:
    print("✅ All catalog products are in expected_map")

# Show mapping suggestions
print("\n" + "=" * 70)
print("🔧 SUGGESTED FIXES FOR EXPECTED_MAP")
print("=" * 70)
if in_expected_not_in_catalog:
    print("\nEdit data/expected_map_BTM_CH01.json and replace:\n")
    for old_id in sorted(in_expected_not_in_catalog):
        # Find best match in catalog
        similar = [c for c in catalog_ids if old_id[:5] in c or c[:5] in pid]
        if similar:
            print(f"  '{old_id}'  →  '{similar[0]}'")
        else:
            print(f"  '{old_id}'  →  ??? (no obvious match, please choose manually)")