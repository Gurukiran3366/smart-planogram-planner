# validate_json.py
import json
import pandas as pd

# Load the JSON
try:
    with open("data/expected_map_BTM_CH01_DRAFT.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    total_products = sum(len(s["products"]) for s in data["shelves"])
    total_shelves = len(data["shelves"])
    
    print(f"✅ JSON is valid!")
    print(f"   Shelves: {total_shelves}")
    print(f"   Total products: {total_products}\n")
    
    for shelf in data["shelves"]:
        print(f"   Shelf {shelf['shelf_number']}: {len(shelf['products'])} products")
        
except json.JSONDecodeError as e:
    print(f"❌ JSON is broken!")
    print(f"   Error: {e}")
    print(f"   Line {e.lineno}, position {e.colno}")
    exit()

# Load products catalog
print("\n" + "="*60)
print("Checking product IDs against catalog...")
print("="*60)

products_df = pd.read_excel("data/products.xlsx")
valid_ids = set(products_df["product_id"].astype(str))

print(f"\nCatalog has {len(valid_ids)} products\n")

invalid_found = []
zone_issues = []
valid_zones = {"left", "center", "right"}

for shelf in data["shelves"]:
    shelf_num = shelf["shelf_number"]
    for product in shelf["products"]:
        pid = product["product_id"]
        zone = product.get("zone", "")
        
        # Check product_id validity
        if pid not in valid_ids:
            invalid_found.append(f"Shelf {shelf_num}: '{pid}'")
        
        # Check zone validity (must be lowercase)
        if zone not in valid_zones:
            zone_issues.append(f"Shelf {shelf_num} / {pid}: zone = '{zone}' (must be 'left', 'center', or 'right')")

if invalid_found:
    print(f"❌ {len(invalid_found)} product IDs are NOT in catalog:")
    for item in invalid_found:
        print(f"   - {item}")
    print(f"\n   Fix: either add these to products.xlsx OR change to existing IDs")
else:
    print("✅ All product IDs exist in catalog")

if zone_issues:
    print(f"\n❌ {len(zone_issues)} zone issues found:")
    for item in zone_issues:
        print(f"   - {item}")
else:
    print("✅ All zones are valid (left/center/right)")

# Check for duplicate products within same shelf
print("\n" + "="*60)
print("Checking for duplicate products within shelves...")
print("="*60)

duplicates_found = []
for shelf in data["shelves"]:
    shelf_num = shelf["shelf_number"]
    seen = {}
    for product in shelf["products"]:
        pid = product["product_id"]
        if pid in seen:
            duplicates_found.append(f"Shelf {shelf_num}: '{pid}' appears multiple times")
        seen[pid] = True

if duplicates_found:
    print(f"\n⚠️ Duplicate products found:")
    for item in duplicates_found:
        print(f"   - {item}")
    print("\n   Note: some products can legitimately have multiple facings — use 'facings': 2 instead of listing twice")
else:
    print("\n✅ No duplicate product entries within shelves")

# Check for products in unexpected commodities
print("\n" + "="*60)
print("Checking commodity match per shelf...")
print("="*60)

commodity_issues = []
for shelf in data["shelves"]:
    shelf_num = shelf["shelf_number"]
    expected_commodities = shelf.get("expected_commodities", [])
    
    for product in shelf["products"]:
        pid = product["product_id"]
        if pid in valid_ids:
            product_row = products_df[products_df["product_id"] == pid].iloc[0]
            actual_commodity = product_row["commodity"]
            if actual_commodity not in expected_commodities:
                commodity_issues.append(
                    f"Shelf {shelf_num}: '{pid}' has commodity '{actual_commodity}' "
                    f"but shelf expects {expected_commodities}"
                )

if commodity_issues:
    print(f"\n⚠️ {len(commodity_issues)} commodity mismatches (might be OK if substitution allowed):")
    for item in commodity_issues:
        print(f"   - {item}")
else:
    print("\n✅ All products match their shelf's expected commodity")

print("\n" + "="*60)
print("Validation complete!")
print("="*60)