# debug_shelf_positions.py
import cv2
import easyocr
import json
import sys
from pathlib import Path

image_path = sys.argv[1] if len(sys.argv) > 1 else "images/staff_uploads/shelfmessing.jpeg"

print(f"Analyzing: {image_path}\n")

img = cv2.imread(image_path)
h, w = img.shape[:2]
print(f"Image dimensions: {w} x {h}\n")

reader = easyocr.Reader(['en'], gpu=False, verbose=False)
result = reader.readtext(image_path, text_threshold=0.3, low_text=0.3, width_ths=0.5, height_ths=0.5)

# Load reference shelf positions
with open("data/shelf_boundaries.json", "r") as f:
    ref = json.load(f)

ref_shelves = {s["shelf"]: s["y"] for s in ref["shelves"]}

print("=" * 70)
print("COMPARISON: Reference photo Y-positions vs This staff photo")
print("=" * 70)
print(f"{'Shelf':<8} {'Ref Y':<10} {'Staff Y':<10} {'Difference':<12}")
print("-" * 40)

# Find shelf labels in this photo
staff_shelves = {}
for detection in result:
    box, text, confidence = detection
    text_clean = text.upper().replace(" ", "").replace(".", "-")
    text_normalized = text_clean.replace("5-", "S-").replace("$-", "S-")
    
    for i in range(1, 7):
        if text_clean in [f"S-{i}", f"S{i}", f"5-{i}"] or text_normalized == f"S-{i}":
            y = int(sum(pt[1] for pt in box) / 4)
            if i not in staff_shelves:
                staff_shelves[i] = y

for i in range(1, 7):
    ref_y = ref_shelves.get(i, "?")
    staff_y = staff_shelves.get(i, "NOT DETECTED")
    if isinstance(staff_y, int) and isinstance(ref_y, int):
        diff = staff_y - ref_y
        diff_str = f"{diff:+d} px"
    else:
        diff_str = "N/A"
    print(f"S-{i:<6} {ref_y:<10} {str(staff_y):<10} {diff_str}")

# Also compute average spacing between shelves in this photo
print("\n" + "=" * 70)
print("SHELF SPACING in this staff photo:")
print("=" * 70)
sorted_shelves = sorted(staff_shelves.items())
for i in range(len(sorted_shelves) - 1):
    s1, y1 = sorted_shelves[i]
    s2, y2 = sorted_shelves[i+1]
    print(f"  S-{s1} → S-{s2}: {y2 - y1} pixels")

# Draw debug visualization
debug_img = img.copy()
for i, y in staff_shelves.items():
    cv2.line(debug_img, (0, y), (w, y), (0, 255, 0), 2)
    cv2.putText(debug_img, f"S-{i} y={y}", (10, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

# Also draw where crops would be with current LABEL_HEIGHT=45
LABEL_HEIGHT = 45
sorted_ys = sorted(staff_shelves.values())
for i, label_y in enumerate(sorted_ys):
    crop_start = label_y + LABEL_HEIGHT
    cv2.line(debug_img, (0, crop_start), (w, crop_start), (0, 0, 255), 1)
    cv2.putText(debug_img, f"crop start", (w - 200, crop_start - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

Path("images/debug").mkdir(parents=True, exist_ok=True)
output = f"images/debug/positions_{Path(image_path).stem}.jpg"
cv2.imwrite(output, debug_img)
print(f"\n📸 Debug image saved: {output}")
print("   Green lines = OCR-detected label positions")
print("   Red lines   = where cropping would start (label_y + 45)")