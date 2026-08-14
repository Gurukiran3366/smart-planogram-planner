# test_crop_only.py
"""
Standalone cropping test — no AI, no API calls.
Tests only the shelf cropping logic so we can iterate quickly.

Usage:
    python test_crop_only.py images/staff_uploads/shelfmessing.jpeg
    python test_crop_only.py images/reference/BTM-CH01_reference.jpeg
"""

import sys
import cv2
import easyocr
from pathlib import Path


# ============================================================
# CONFIG — Tune these values to fix cropping
# ============================================================
FALLBACK_SHELF_YS = [96, 380, 630, 867, 1110, 1345]

# Horizontal crop percentages
LEFT_BOUND_PCT = 0.18   # Start crop at 18% from left
RIGHT_BOUND_PCT = 0.95  # End crop at 95% from left

# Boundary calculation offsets (in pixels)
LABEL_OFFSET_ABOVE = 10  # How many pixels above next label to end current shelf


# ============================================================
# OCR — Detect shelf labels
# ============================================================
def detect_shelves_via_ocr(image_path):
    """Detect S-1 through S-6 shelf labels using OCR."""
    print("🔍 Running OCR to find shelf labels...")
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
                x_center = int(sum(pt[0] for pt in box) / 4)
                shelf_labels.append({
                    "shelf": i,
                    "y": y_center,
                    "x": x_center,
                    "confidence": confidence
                })
                break
    
    # Dedupe (keep first occurrence)
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
        print(f"✅ All 6 shelf labels detected via OCR:")
        for s in detected:
            print(f"   Shelf {s['shelf']}: y={s['y']}, x={s['x']}")
        return [{"shelf": i, "y": detected_shelves[i]} for i in range(1, 7)]
    
    print(f"⚠️  Only {len(detected)}/6 shelves detected — using fallback for missing")
    result = []
    for i in range(1, 7):
        if i in detected_shelves:
            result.append({"shelf": i, "y": detected_shelves[i]})
            print(f"   Shelf {i}: y={detected_shelves[i]} (OCR)")
        else:
            result.append({"shelf": i, "y": FALLBACK_SHELF_YS[i-1]})
            print(f"   Shelf {i}: y={FALLBACK_SHELF_YS[i-1]} (fallback)")
    return result


# ============================================================
# CROP LOGIC — This is what we're testing
# ============================================================
def crop_shelves(image_path, shelf_positions, output_folder):
    """
    Crop image into 6 shelf strips.
    
    Boundary logic:
    - Shelf 1 top: y=0 (top of image)
    - Between shelves: 10px ABOVE the next label
    - Shelf 6 bottom: bottom of image
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    output_folder.mkdir(parents=True, exist_ok=True)
    positions = sorted(shelf_positions, key=lambda x: x["shelf"])
    
    # Horizontal boundaries
    left_bound = int(w * LEFT_BOUND_PCT)
    right_bound = int(w * RIGHT_BOUND_PCT)
    
    print(f"\n📊 Image size: {w}x{h}")
    print(f"📊 Horizontal crop: x={left_bound} to x={right_bound} (width: {right_bound-left_bound}px)")
    
    # Vertical boundaries
    boundaries = [0]  # Shelf 1 starts at top
    for i in range(len(positions) - 1):
        next_label_y = positions[i + 1]["y"]
        boundary = next_label_y - LABEL_OFFSET_ABOVE
        boundaries.append(boundary)
    boundaries.append(h)  # Last shelf goes to bottom
    
    print(f"📊 Vertical boundaries: {boundaries}")
    print()
    
    for i, shelf in enumerate(positions):
        shelf_num = shelf["shelf"]
        y_start = max(0, boundaries[i])
        y_end = min(h, boundaries[i + 1])
        
        if y_end <= y_start:
            print(f"⚠️  Shelf {shelf_num}: invalid boundaries [{y_start}:{y_end}]")
            continue
        
        crop = img[y_start:y_end, left_bound:right_bound]
        crop_path = output_folder / f"shelf_{shelf_num}.jpg"
        cv2.imwrite(str(crop_path), crop)
        crop_h, crop_w = crop.shape[:2]
        label_y = shelf["y"]
        print(f"✂️  Shelf {shelf_num}: {crop_w}x{crop_h}px  (label at y={label_y}, crop y={y_start}-{y_end})")


# ============================================================
# VISUAL DEBUG — Draw boundaries on original image
# ============================================================
def create_debug_visualization(image_path, shelf_positions, output_folder):
    """
    Create a debug image showing:
    - Green lines: crop boundaries
    - Red dots: detected label positions
    - Blue vertical lines: horizontal crop bounds
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    debug = img.copy()
    positions = sorted(shelf_positions, key=lambda x: x["shelf"])
    
    left_bound = int(w * LEFT_BOUND_PCT)
    right_bound = int(w * RIGHT_BOUND_PCT)
    
    # Draw horizontal crop bounds (blue vertical lines)
    cv2.line(debug, (left_bound, 0), (left_bound, h), (255, 0, 0), 3)
    cv2.line(debug, (right_bound, 0), (right_bound, h), (255, 0, 0), 3)
    cv2.putText(debug, f"L:{left_bound}", (left_bound + 5, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
    cv2.putText(debug, f"R:{right_bound}", (right_bound - 100, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
    
    # Draw crop boundaries (green horizontal lines)
    boundaries = [0]
    for i in range(len(positions) - 1):
        next_label_y = positions[i + 1]["y"]
        boundary = next_label_y - LABEL_OFFSET_ABOVE
        boundaries.append(boundary)
    boundaries.append(h)
    
    for i, y in enumerate(boundaries):
        color = (0, 255, 0)  # Green
        cv2.line(debug, (0, y), (w, y), color, 3)
        cv2.putText(debug, f"Y={y}", (10, y - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    # Draw shelf label positions (red circles + text)
    for shelf in positions:
        y = shelf["y"]
        cv2.circle(debug, (50, y), 8, (0, 0, 255), -1)
        cv2.putText(debug, f"S-{shelf['shelf']} (y={y})", (65, y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    
    debug_path = output_folder / "_DEBUG_boundaries.jpg"
    cv2.imwrite(str(debug_path), debug)
    print(f"\n🎨 Debug visualization saved: {debug_path}")
    print("   RED dots = detected shelf labels")
    print("   GREEN lines = crop boundaries")
    print("   BLUE lines = horizontal crop bounds")


# ============================================================
# MAIN
# ============================================================
def main(image_path):
    print(f"\n{'='*70}")
    print(f"CROP TEST: {image_path}")
    print(f"{'='*70}\n")
    
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        return
    
    photo_name = Path(image_path).stem
    output_folder = Path("images/crop_test") / photo_name
    
    # Step 1: Detect shelf positions
    shelf_positions = get_shelf_positions(image_path)
    
    # Step 2: Crop shelves
    print("\n" + "="*70)
    print("CROPPING SHELVES")
    print("="*70)
    crop_shelves(image_path, shelf_positions, output_folder)
    
    # Step 3: Create debug visualization
    print("\n" + "="*70)
    print("CREATING DEBUG VISUALIZATION")
    print("="*70)
    create_debug_visualization(image_path, shelf_positions, output_folder)
    
    # Summary
    print(f"\n{'='*70}")
    print(f"✅ CROP TEST COMPLETE")
    print(f"{'='*70}")
    print(f"\n📁 Check results in: {output_folder}")
    print(f"\n📸 To view:")
    print(f"   start {output_folder}\\_DEBUG_boundaries.jpg   (shows where cuts are made)")
    print(f"   start {output_folder}\\shelf_1.jpg              (verify shelf 1 crop)")
    print(f"   start {output_folder}\\shelf_2.jpg              (verify shelf 2 crop)")
    print(f"   ... etc for shelf_3, shelf_4, shelf_5, shelf_6")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_crop_only.py <image_path>")
        print("Example: python test_crop_only.py images/staff_uploads/shelfmessing.jpeg")
        sys.exit(1)
    
    main(sys.argv[1])