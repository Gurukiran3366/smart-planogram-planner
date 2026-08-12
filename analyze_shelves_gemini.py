# analyze_shelves_gemini.py
import os
import json
import pandas as pd
from google import genai
from google.genai import types
from pathlib import Path
from PIL import Image

# ============================================================
# CONFIG
# ============================================================
client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

RACK_ID = "BTM-CH01"
PRODUCTS_FILE = "data/products.xlsx"
RULES_FILE = "data/chiller_rules.json"
CROPS_METADATA = "data/shelf_crops.json"
OUTPUT_FILE = "data/expected_map_BTM_CH01_DRAFT.json"
MODEL_NAME = "gemini-3.6-flash"

# Human-readable commodity labels for the prompt
COMMODITY_LABELS = {
    "fruit_beverage": "Fruit Beverages (juices, fruit drinks)",
    "energy_drink": "Energy Drinks (Monster, Red Bull, Sting, etc.)",
    "soft_drink": "Soft Drinks (Coca-Cola, Pepsi, Fanta, Sprite, etc.)",
    "milk_beverage": "Milk Beverages (flavored milk, protein drinks, buttermilk)",
    "fruit_soft_10rs": "Small ₹10 packs (fruit + soft drinks)",
    "water": "Water bottles"
}


def build_product_catalog_text(products_df, allowed_commodities):
    """Build a text list of products that could appear on this shelf."""
    filtered = products_df[products_df["commodity"].isin(allowed_commodities)]
    lines = []
    for _, row in filtered.iterrows():
        lines.append(
            f"  - {row['product_id']}: {row['product_name']} "
            f"({row['brand']}, {row['pack_size_ml']}ml, {row['colour_tone']}, {row['size_band']})"
        )
    return "\n".join(lines)


def analyze_shelf(shelf_num, shelf_image_path, allowed_commodities, catalog_text):
    """Send one shelf image to Gemini and get structured product data."""
    
    commodity_desc = ", ".join(COMMODITY_LABELS.get(c, c) for c in allowed_commodities)
    
    prompt = f"""You are analyzing SHELF {shelf_num} of a beverage chiller.

CONTEXT:
This shelf should contain: {commodity_desc}

The following is the COMPLETE LIST of products in our catalog that could appear on this shelf.
You MUST only identify products from this list — if you see a product not on this list, mark it as "UNKNOWN".

CATALOG (product_id: description):
{catalog_text}

YOUR TASK:
1. Identify every distinct product visible on this shelf
2. Match each one to a product_id from the catalog above (exact match required)
3. Determine which zone it's in: "left", "center", or "right" (divide shelf width into thirds)
4. Count facings (how many identical units are placed side-by-side, front-facing)
5. Assign a confidence: "high" (certain), "medium" (mostly sure), "low" (uncertain)
6. Note any empty areas or unknown items

Return ONLY this JSON format (no other text):

{{
  "shelf_number": {shelf_num},
  "products": [
    {{
      "product_id": "PEPSI_CAN_300",
      "zone": "left",
      "facings": 2,
      "confidence": "high",
      "notes": ""
    }}
  ],
  "unknown_items": [
    {{
      "description": "unidentified dark bottle",
      "zone": "center",
      "notes": "possibly a new product not in catalog"
    }}
  ],
  "empty_zones": []
}}
"""

    # Load image
    image = Image.open(shelf_image_path)
    
    # Call Gemini with new SDK
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt, image],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0
        )
    )
    
    return json.loads(response.text)


def main():
    print("📖 Loading catalog and rules...")
    products_df = pd.read_excel(PRODUCTS_FILE)
    
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        rules = json.load(f)
    
    with open(CROPS_METADATA, "r") as f:
        crops_meta = json.load(f)
    
    shelf_commodity_map = rules["rules"][0]["shelf_commodity_map"]
    valid_product_ids = set(products_df["product_id"].astype(str))
    
    print(f"✅ Loaded {len(products_df)} products from catalog")
    print(f"✅ Loaded rules for {len(shelf_commodity_map)} shelves")
    print(f"🤖 Using: {MODEL_NAME} (free tier)\n")
    
    all_shelves = []
    
    for crop_info in sorted(crops_meta["crops"], key=lambda x: x["shelf_number"]):
        shelf_num = crop_info["shelf_number"]
        shelf_image = crop_info["image_path"]
        allowed_commodities = shelf_commodity_map[str(shelf_num)]
        
        print(f"─── Analyzing Shelf {shelf_num} ─── (expected: {allowed_commodities})")
        
        catalog_text = build_product_catalog_text(products_df, allowed_commodities)
        
        try:
            result = analyze_shelf(shelf_num, shelf_image, allowed_commodities, catalog_text)
        except Exception as e:
            print(f"   ❌ Error analyzing shelf {shelf_num}: {e}")
            continue
        
        # Validate detected product IDs against catalog
        validated_products = []
        invalid_ids = []
        
        for item in result.get("products", []):
            pid = item.get("product_id", "")
            if pid in valid_product_ids:
                validated_products.append(item)
            else:
                invalid_ids.append(pid)
                item["validation_error"] = "product_id not found in catalog"
                validated_products.append(item)
        
        # Print summary
        valid_count = len(validated_products) - len(invalid_ids)
        print(f"   ✅ {valid_count} valid products identified")
        if invalid_ids:
            print(f"   ⚠️  {len(invalid_ids)} unrecognized product IDs: {invalid_ids}")
        
        unknown_items = result.get("unknown_items", [])
        if unknown_items:
            print(f"   🔍 {len(unknown_items)} unknown items (not in catalog)")
        
        for item in validated_products:
            marker = "⚠️" if "validation_error" in item else "  "
            conf = item.get("confidence", "?")
            print(f"      {marker} {item['zone']:6} | {item['facings']}× {item['product_id']} ({conf})")
        
        all_shelves.append({
            "shelf_number": shelf_num,
            "expected_commodities": allowed_commodities,
            "products": validated_products,
            "unknown_items": unknown_items,
            "empty_zones": result.get("empty_zones", [])
        })
        
        print()
    
    # Build final expected_map
    expected_map = {
        "rack_id": RACK_ID,
        "extraction_method": f"{MODEL_NAME} shelf-by-shelf with catalog constraint",
        "extraction_status": "DRAFT - requires human verification",
        "shelves": all_shelves
    }
    
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(expected_map, f, indent=2, ensure_ascii=False)
    
    print("=" * 70)
    print(f"✅ Draft expected map saved to: {OUTPUT_FILE}")
    print("=" * 70)
    print("""
NEXT STEP: Human verification
1. Open the draft JSON file
2. Compare each shelf's products against your reference image
3. Fix any errors:
   - Wrong product_ids (typos, wrong pack size, etc.)
   - Wrong zones (left/center/right)
   - Wrong facing counts
   - Items marked with validation_error
   - Unknown items — either add them to products.xlsx or ignore
4. When fully verified, rename the file to:
   data/expected_map_BTM_CH01.json  (remove the _DRAFT suffix)
""")


if __name__ == "__main__":
    main()