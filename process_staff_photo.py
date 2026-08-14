# process_staff_photo.py
"""
Processes staff-uploaded chiller photos through the audit pipeline.
Uses OCR for shelf detection, dynamic cropping, and Gemini AI for product identification.
"""

import os
import sys
import json
import base64
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

# Fallback shelf Y-positions if OCR completely fails
FALLBACK_SHELF_YS = [96, 380, 630, 867, 1110, 1345]

COMMODITY_LABELS = {
    "fruit_beverage": "Fruit Beverages",
    "energy_drink": "Energy Drinks",
    "soft_drink": "Soft Drinks",
    "milk_beverage": "Milk Beverages",
    "fruit_soft_10rs": "Small ₹10 packs",
    "water": "Water bottles"
}


def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


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


def calculate_horizontal_bounds(image_path):
    """
    Calculate horizontal crop boundaries based on image width.
    Uses percentage-based bounds that work across different photo distances.
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    
    # Chiller content is roughly between 18% and 95% of image width
    left_bound = int(w * 0.18)
    right_bound = int(w * 0.95)
    
    return left_bound, right_bound


def crop_shelves(image_path, shelf_positions, output_folder):
    """
    Crop image into 6 shelf strips using improved boundary calculation.
    
    Key improvement: Shelf labels are typically at the TOP-LEFT of each shelf frame.
    So each shelf's content is BELOW its label, extending down to just BEFORE the next label.
    
    Boundary logic:
    - Shelf N top: N's label Y position (with small upward padding to catch product tops)
    - Shelf N bottom: N+1's label Y position (with small padding to not include next label)
    - Shelf 6 bottom: image bottom
    - Shelf 1 top: extend upward to include tall products above label
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    output_folder.mkdir(parents=True, exist_ok=True)
    crops = []
    positions = sorted(shelf_positions, key=lambda x: x["shelf"])
    
    # Calculate horizontal boundaries
    left_bound, right_bound = calculate_horizontal_bounds(image_path)
    
    print(f"   📊 Image size: {w}x{h}")
    print(f"   📊 Horizontal crop: x={left_bound} to x={right_bound} (width: {right_bound-left_bound}px)")
    
    # Calculate shelf content boundaries
    # Key insight: shelf labels are placed at approximately the TOP of each shelf's frame
    # But products extend BELOW the label into the shelf space
    # So we need to shift boundaries DOWNWARD from label positions
    
    LABEL_TO_CONTENT_OFFSET = 20   # Label is ~20px above the actual shelf content
    PRODUCT_HEIGHT_ESTIMATE = 100  # Products can be up to 100px tall above their base
    
    boundaries = []
    
    # For Shelf 1: extend upward to capture full product height
    # Products on Shelf 1 sit ON the shelf, tops extend upward from the shelf floor
    # The S-1 label is on the shelf frame (top of shelf), products are BELOW label going into shelf space
    # Actually, looking at your photo — products fill the space BETWEEN shelves
    # So Shelf 1 content = from top of image (0) to just above Shelf 2 label
    shelf1_top = 0
    boundaries.append(shelf1_top)
    
    # For internal shelves: content is between consecutive labels
    # Each shelf's content starts at its label position and ends at next label position
    for i in range(len(positions) - 1):
        # Boundary between shelf N and shelf N+1
        # Place it just above shelf N+1's label
        next_label_y = positions[i + 1]["y"]
        boundary = next_label_y - 10  # 10px above next label to not include it
        boundaries.append(boundary)
    
    # Last shelf extends to image bottom
    boundaries.append(h)
    
    print(f"   📊 Vertical boundaries: {boundaries}")
    
    for i, shelf in enumerate(positions):
        shelf_num = shelf["shelf"]
        y_start = boundaries[i]
        y_end = boundaries[i + 1]
        
        # Safety: ensure valid range
        y_start = max(0, y_start)
        y_end = min(h, y_end)
        
        if y_end <= y_start:
            print(f"   ⚠️  Shelf {shelf_num}: invalid boundaries [{y_start}:{y_end}], skipping")
            continue
        
        crop = img[y_start:y_end, left_bound:right_bound]
        crop_path = output_folder / f"shelf_{shelf_num}.jpg"
        cv2.imwrite(str(crop_path), crop)
        crop_h, crop_w = crop.shape[:2]
        print(f"   ✂️  Shelf {shelf_num}: {crop_w}x{crop_h}px (y={y_start}-{y_end})")
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
    Send ALL 6 shelf images in ONE API call.
    Uses slot-based positioning (each physical bottle position = 1 slot).
    """
    catalog_text = build_full_catalog_text(products_df)
    
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
- A single shelf typically has 5-10 unique products maximum
- If you find yourself listing 12+ products for one shelf, you are HALLUCINATING

SHELF EXPECTATIONS (what SHOULD be there — but report what you actually SEE):
{expectations_text}

⚠️ IMPORTANT: Products may be MISPLACED. If you see a soft drink on the energy drink shelf, 
report it correctly using the FULL catalog below. Do NOT restrict yourself to the shelf's 
expected commodity when identifying products.

FULL PRODUCT CATALOG (identify products from this ENTIRE list, regardless of which shelf):
{catalog_text}

YOUR TASK:
For EACH of the 6 shelf images, identify EVERY product visible, even if misplaced.

STEPS FOR EACH IMAGE:
1. Look at ONLY the current image
2. Identify EVERY distinct product visible from LEFT to RIGHT
3. Match to a product_id from the FULL catalog above (any commodity)
4. Only use "unknown_items" if the product is truly not in the catalog

5. Count SLOTS (each physical bottle/can position = 1 slot):
   - slot_start = leftmost slot the product occupies (1 = leftmost of shelf)
   - slot_end = rightmost slot (same as slot_start if only 1 facing)
   - Example: If Coca-Cola has 2 bottles side-by-side starting at slot 3,
     then slot_start=3 and slot_end=4
   - Next product starts at slot 5 (not 4)

6. Count facings = slot_end - slot_start + 1
7. Also assign zone: "left", "center", or "right"
8. Assign confidence: "high", "medium", "low"

IDENTIFICATION HINTS:
- Small carton pack with mango imagery = Maaza Mango
- Red/silver energy can = Red Bull (regular) or Red Bull Sugarfree
- Blue/silver energy can = often Red Bull Sugarfree
- Green pouch = Paper Boat Swing (various flavors)
- If uncertain, use "medium" or "low" confidence

Return ONLY this JSON (all 6 shelves included):

{{
  "shelves": [
    {{
      "shelf_number": 1,
      "products": [
        {{"product_id": "PRODUCT_ID", "slot_start": 1, "slot_end": 1, "zone": "left", "facings": 1, "confidence": "high"}}
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
    
    # Build multi-image content
    contents = [prompt]
    for crop in sorted(crops, key=lambda x: x["shelf_number"]):
        shelf_num = crop["shelf_number"]
        contents.append(f"\n=== IMAGE FOR SHELF {shelf_num} — analyze THIS image for Shelf {shelf_num} products only ===")
        contents.append(Image.open(crop["image_path"]))
    
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
                if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                    wait_time = 30 * attempt
                else:
                    wait_time = 2 ** attempt
                print(f"      ⏳ Attempt {attempt} failed ({error_str[:100]}...)")
                print(f"      ⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                raise
    raise Exception(f"Failed after {max_retries} retries")


def process_photo(image_path):
    """Main pipeline: photo → actual_map.json"""
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
    
    # Step 5: One API call for all shelves
    print(f"\n📋 Step 5: Analyzing ALL shelves in ONE API call to {MODEL_NAME}")
    all_shelves = []
    try:
        result = analyze_all_shelves_one_call(crops, products_df, shelf_commodity_map)
        all_shelves = result.get("shelves", [])
        
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
        for photo in photos:
            process_photo(str(photo))
    else:
        process_photo(sys.argv[1])