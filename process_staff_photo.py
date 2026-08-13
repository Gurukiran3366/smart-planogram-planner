# process_staff_photo_v2.py
import os
import sys
import json
import cv2
import time
import easyocr
import pandas as pd
from google import genai
from google.genai import types
from pathlib import Path
from PIL import Image
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
MODEL_NAME = "gemini-3.6-flash"

RACK_ID = "BTM-CH01"
PRODUCTS_FILE = "data/products.xlsx"
RULES_FILE = "data/chiller_rules.json"
OUTPUT_DIR = Path("data/actual_maps")
DEBUG_DIR = Path("images/staff_processing")

# Crop settings
CROP_LEFT = 350
CROP_RIGHT = 1150

FALLBACK_SHELF_YS = [96, 380, 630, 867, 1110, 1345]

COMMODITY_LABELS = {
    "fruit_beverage": "Fruit Beverages",
    "energy_drink": "Energy Drinks",
    "soft_drink": "Soft Drinks",
    "milk_beverage": "Milk Beverages",
    "fruit_soft_10rs": "Small ₹10 packs",
    "water": "Water bottles"
}


def check_image_quality(image_path):
    """Fast local quality check before API call."""
    img = cv2.imread(image_path)
    if img is None:
        return False, ["Cannot read image"]
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    issues = []
    if w < 600 or h < 800:
        issues.append(f"Low resolution: {w}x{h}")
    if cv2.Laplacian(gray, cv2.CV_64F).var() < 100:
        issues.append("Image is blurry")
    brightness = gray.mean()
    if brightness < 50:
        issues.append(f"Too dark (brightness {brightness:.0f})")
    if brightness > 220:
        issues.append(f"Overexposed (brightness {brightness:.0f})")
    return len(issues) == 0, issues


def detect_shelves_via_ocr(image_path):
    """Detect S-1 through S-6 shelf labels using OCR."""
    print("   🔍 Running OCR to find shelf labels...")
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    result = reader.readtext(image_path, text_threshold=0.3, low_text=0.3,
                              width_ths=0.5, height_ths=0.5)
    shelf_labels = []
    for detection in result:
        box, text, confidence = detection
        text_clean = text.upper().replace(" ", "").replace(".", "-")
        text_normalized = text_clean.replace("5-", "S-").replace("$-", "S-")
        for i in range(1, 7):
            if text_clean in [f"S-{i}", f"S{i}", f"5-{i}"] or text_normalized == f"S-{i}":
                y_center = int(sum(pt[1] for pt in box) / 4)
                shelf_labels.append({"shelf": i, "y": y_center})
                break
    unique = {}
    for s in shelf_labels:
        if s["shelf"] not in unique:
            unique[s["shelf"]] = s
    return sorted(unique.values(), key=lambda x: x["shelf"])


def get_shelf_positions(image_path):
    """Try OCR first, fall back to reference positions if incomplete."""
    detected = detect_shelves_via_ocr(image_path)
    detected_shelves = {s["shelf"]: s["y"] for s in detected}
    if len(detected) == 6:
        print(f"   ✅ All 6 shelf labels detected via OCR")
        return [{"shelf": i, "y": detected_shelves[i]} for i in range(1, 7)]
    print(f"   ⚠️  Only {len(detected)}/6 shelves detected — using fallback for missing")
    result = []
    for i in range(1, 7):
        if i in detected_shelves:
            result.append({"shelf": i, "y": detected_shelves[i]})
        else:
            result.append({"shelf": i, "y": FALLBACK_SHELF_YS[i-1]})
            print(f"      Shelf {i}: using fallback y={FALLBACK_SHELF_YS[i-1]}")
    return result


def calculate_horizontal_bounds(image_path, shelf_positions):
    """
    Dynamically calculate horizontal crop boundaries based on where 
    shelf labels are detected. The chiller content is to the RIGHT of the labels.
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    
    if not shelf_positions:
        # Fallback to defaults if no shelves detected
        return CROP_LEFT, CROP_RIGHT
    
    # Get x-coordinates of detected labels (they should be on left side)
    # We need to re-run OCR to get x positions, so let's use a simpler approach:
    # Look at existing shelf_positions - but they only have Y coords.
    # 
    # Alternative: use image analysis to find the chiller frame
    
    # Simple approach: assume labels are at ~5-15% of width from left
    # Chiller content starts at ~20% from left
    # Chiller content ends at ~90% from left (glass edge)
    
    # But we should be MORE GENEROUS to avoid cutting off products
    left_bound = int(w * 0.18)   # Start 18% from left (safer than 350px hardcoded)
    right_bound = int(w * 0.95)  # End 95% from left (include full width)
    
    return left_bound, right_bound


def crop_shelves(image_path, shelf_positions, output_folder):
    """
    Crop image into 6 shelf strips using midpoint boundaries.
    Uses DYNAMIC horizontal boundaries based on image dimensions,
    not hardcoded values — makes it robust across different photo angles/distances.
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    output_folder.mkdir(parents=True, exist_ok=True)
    crops = []
    positions = sorted(shelf_positions, key=lambda x: x["shelf"])
    ys = [p["y"] for p in positions]
    
    # Calculate vertical boundaries (midpoints between shelf labels)
    boundaries = [0]
    for i in range(len(ys) - 1):
        boundaries.append((ys[i] + ys[i+1]) // 2)
    boundaries.append(h)
    
    # Calculate horizontal boundaries DYNAMICALLY
    left_bound, right_bound = calculate_horizontal_bounds(image_path, shelf_positions)
    
    print(f"   📊 Image size: {w}x{h}")
    print(f"   📊 Horizontal crop: x={left_bound} to x={right_bound} (width: {right_bound-left_bound}px)")
    print(f"   📊 Vertical boundaries: {boundaries}")
    
    for i, shelf in enumerate(positions):
        shelf_num = shelf["shelf"]
        y_start = boundaries[i]
        y_end = boundaries[i + 1]
        
        if y_end <= y_start:
            print(f"   ⚠️  Shelf {shelf_num}: invalid boundaries, skipping")
            continue
        
        # Use dynamic horizontal bounds instead of hardcoded CROP_LEFT/CROP_RIGHT
        crop = img[y_start:y_end, left_bound:right_bound]
        crop_path = output_folder / f"shelf_{shelf_num}.jpg"
        cv2.imwrite(str(crop_path), crop)
        crop_h, crop_w = crop.shape[:2]
        print(f"   ✂️  Shelf {shelf_num}: {crop_w}x{crop_h}px")
        crops.append({"shelf_number": shelf_num, "image_path": str(crop_path)})
    
    return crops


def build_full_catalog_text(products_df):
    """Build catalog grouped by commodity for the multi-shelf prompt."""
    lines = []
    for commodity in sorted(products_df["commodity"].unique()):
        commodity_label = COMMODITY_LABELS.get(commodity, commodity)
        lines.append(f"\n{commodity_label} ({commodity}):")
        for _, row in products_df[products_df["commodity"] == commodity].iterrows():
            lines.append(
                f"  - {row['product_id']}: {row['product_name']} "
                f"({row['brand']}, {row['pack_size_ml']}ml, {row['colour_tone']}, {row['size_band']})"
            )
    return "\n".join(lines)


def analyze_all_shelves_one_call(crops, products_df, shelf_commodity_map, max_retries=3):
    """
    Send ALL 6 shelf images in ONE Gemini API call.
    6x cheaper and faster than making per-shelf calls.
    """
    catalog_text = build_full_catalog_text(products_df)
    
    # Build shelf-by-shelf expectations
    shelf_expectations = []
    for crop in sorted(crops, key=lambda x: x["shelf_number"]):
        shelf_num = crop["shelf_number"]
        commodities = shelf_commodity_map[str(shelf_num)]
        commodity_desc = ", ".join(COMMODITY_LABELS.get(c, c) for c in commodities)
        shelf_expectations.append(f"  Shelf {shelf_num}: expected commodity → {commodity_desc}")
    
    expectations_text = "\n".join(shelf_expectations)
    
    prompt = f"""You are analyzing a beverage chiller with 6 shelves (STAFF-UPLOADED PHOTO — may be imperfect).

I am sending you 6 SEPARATE IMAGES in order — one per shelf, from Shelf 1 (top) to Shelf 6 (bottom).

CRITICAL RULES:
- Each image shows ONE shelf only
- Products in image N are on Shelf N — do NOT combine products across images
- Do NOT confuse shelf boundaries
- A single shelf typically has 5-10 products maximum
- If you find yourself listing 12+ products for one shelf, you are HALLUCINATING — stop and re-examine the image

SHELF EXPECTATIONS (what SHOULD be there — but report what you actually SEE):
{expectations_text}

⚠️ IMPORTANT: Products may be MISPLACED. If you see a soft drink on the energy drink shelf, 
report it correctly using the FULL catalog below. Do NOT restrict yourself to the shelf's 
expected commodity when identifying products.

FULL PRODUCT CATALOG (identify products from this ENTIRE list, regardless of which shelf):
{catalog_text}

YOUR TASK:
For EACH of the 6 shelf images, identify EVERY product visible, even if it seems misplaced.

STEPS FOR EACH IMAGE:
1. Look at ONLY the current image
2. Identify EVERY distinct product visible from LEFT to RIGHT (bottles, cans, pouches, cartons)
3. Match to a product_id from the FULL catalog above (any commodity — not just this shelf's)
4. Only use "unknown_items" if the product is truly not in the catalog at all
5. Count SLOTS (each physical bottle/can position = 1 slot):
   - slot_start = leftmost slot the product occupies (1 = leftmost of shelf)
   - slot_end = rightmost slot (same as slot_start if only 1 facing)
   - Example: If Coca-Cola has 2 bottles side-by-side starting at slot 3,
     then slot_start=3 and slot_end=4
   - Next product starts at slot 5 (not 4)
6. Count facings = slot_end - slot_start + 1
7. Also assign zone: "left", "center", or "right" (rough position reference)
8. Assign confidence: "high", "medium", "low"

CRITICAL: When counting slots, count EACH physical bottle/can position.
If you see [Product A][Product A][Product B], that's:
- Product A: slot_start=1, slot_end=2, facings=2
- Product B: slot_start=3, slot_end=3, facings=1

IDENTIFICATION HINTS:
- Small carton pack with mango imagery = Maaza Mango
- Red/silver energy can = Red Bull (regular) or Red Bull Sugarfree
- Blue/silver energy can = often Red Bull Sugarfree
- Green pouch = Paper Boat Swing (various flavors)
- Look at COLORS, LOGOS, and PACKAGING SHAPES to distinguish similar products
- If uncertain between similar products, use "medium" or "low" confidence

Return ONLY this JSON (all 6 shelves included):

{{
  "shelves": [
    {{
      "shelf_number": 1,
      "products": [
        {{"product_id": "PRODUCT_ID", "position": 1, "zone": "left", "facings": 1, "confidence": "high"}}
      ],
      "unknown_items": [
        {{"description": "brief description", "zone": "left|center|right", "notes": ""}}
      ],
      "empty_zones": [],
      "notes": ""
    }},
    {{"shelf_number": 2, "products": [], "unknown_items": [], "empty_zones": [], "notes": ""}},
    {{"shelf_number": 3, "products": [], "unknown_items": [], "empty_zones": [], "notes": ""}},
    {{"shelf_number": 4, "products": [], "unknown_items": [], "empty_zones": [], "notes": ""}},
    {{"shelf_number": 5, "products": [], "unknown_items": [], "empty_zones": [], "notes": ""}},
    {{"shelf_number": 6, "products": [], "unknown_items": [], "empty_zones": [], "notes": ""}}
  ]
}}
"""
    
    # Build the multi-image content for Gemini
    # Gemini accepts a list where you can interleave text and images
    contents = [prompt]
    
    for crop in sorted(crops, key=lambda x: x["shelf_number"]):
        shelf_num = crop["shelf_number"]
        contents.append(f"\n--- Image below is SHELF {shelf_num} ---")
        contents.append(Image.open(crop["image_path"]))
    
    # Make the single API call with retry
    for attempt in range(1, max_retries + 1):
        try:
            print(f"   🚀 Sending 6 shelf images in ONE API call to {MODEL_NAME}...")
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0
                )
            )
            return json.loads(response.text)
        except Exception as e:
            error_str = str(e)
            is_retryable = any(code in error_str for code in ["503", "429", "500", "502", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED"])
            
            if is_retryable and attempt < max_retries:
                # For quota errors, wait longer
                if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                    wait_time = 30 * attempt  # 30s, 60s, 90s
                else:
                    wait_time = 2 ** attempt  # 2s, 4s, 8s
                print(f"      ⏳ Attempt {attempt} failed ({error_str[:100]}...)")
                print(f"      ⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                raise
    raise Exception(f"Failed after {max_retries} retries")


def process_photo(image_path):
    print(f"\n{'='*70}")
    print(f"PROCESSING: {image_path}")
    print(f"{'='*70}\n")
    
    # Step 1: Quality
    print("📋 Step 1: Image quality check")
    passed, issues = check_image_quality(image_path)
    if not passed:
        print(f"   ❌ Rejected: {issues}")
        return None
    print(f"   ✅ Image quality acceptable")
    
    # Step 2: Load data
    print("\n📋 Step 2: Loading catalog and rules")
    products_df = pd.read_excel(PRODUCTS_FILE)
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        rules = json.load(f)
    shelf_commodity_map = rules["rules"][0]["shelf_commodity_map"]
    print(f"   ✅ Loaded {len(products_df)} products")
    
    # Step 3: Detect shelves
    print("\n📋 Step 3: Detecting shelf positions")
    shelf_positions = get_shelf_positions(image_path)
    
    # Step 4: Crop
    print("\n📋 Step 4: Cropping shelves")
    photo_name = Path(image_path).stem
    debug_folder = DEBUG_DIR / photo_name
    crops = crop_shelves(image_path, shelf_positions, debug_folder)
    print(f"   ✅ Created {len(crops)} shelf crops")
    
    # Step 5: ONE API call for all shelves
    print(f"\n📋 Step 5: Analyzing ALL shelves in ONE API call to {MODEL_NAME}")
    all_shelves = []
    try:
        result = analyze_all_shelves_one_call(crops, products_df, shelf_commodity_map)
        all_shelves = result.get("shelves", [])
        
        # Enrich with expected_commodities and print summary
        for shelf in all_shelves:
            shelf_num = shelf["shelf_number"]
            shelf["expected_commodities"] = shelf_commodity_map[str(shelf_num)]
            
            products = shelf.get("products", [])
            unknowns = shelf.get("unknown_items", [])
            print(f"\n   ─── Shelf {shelf_num} ─── ({len(products)} products, {len(unknowns)} unknowns)")
            for p in products:
                print(f"      {p.get('zone', '?'):6} | {p.get('facings', '?')}× {p.get('product_id', '?')} ({p.get('confidence', '?')})")
            for u in unknowns:
                print(f"      🔍 unknown: {u.get('description', '?')} in {u.get('zone', '?')}")
    except Exception as e:
        print(f"   ❌ API call failed: {e}")
    
    # Step 6: Save output
    actual_map = {
        "rack_id": RACK_ID,
        "source_image": str(image_path),
        "processed_at": datetime.now().isoformat(),
        "model_used": MODEL_NAME,
        "api_calls_used": 1,
        "shelves": all_shelves
    }
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"actual_map_{photo_name}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(actual_map, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*70}")
    print(f"✅ COMPLETE! Saved to: {output_file}")
    print(f"   💰 Total API calls: 1 (previously 6)")
    print(f"{'='*70}")
    
    return output_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        upload_dir = Path("images/staff_uploads")
        photos = sorted(upload_dir.glob("*.jp*g")) + sorted(upload_dir.glob("*.png"))
        print(f"Processing all {len(photos)} test photos...")
        print(f"💰 Total API calls needed: {len(photos)} (previously {len(photos)*6})")
        for photo in photos:
            process_photo(str(photo))
    else:
        process_photo(sys.argv[1])