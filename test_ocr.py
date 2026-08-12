# test_ocr.py
import easyocr
import cv2

print("Loading EasyOCR...")
reader = easyocr.Reader(['en'], gpu=False)

IMAGE_PATH = "images/reference/BTM-CH01_reference.jpeg"

img = cv2.imread(IMAGE_PATH)
h, w = img.shape[:2]
print(f"\nImage dimensions: {w} x {h} pixels")

print("\nRunning OCR (full resolution, low threshold)...")

result = reader.readtext(
    IMAGE_PATH,
    text_threshold=0.3,
    low_text=0.3,
    width_ths=0.5,
    height_ths=0.5
)

print("\n=== Shelf Label Detection ===\n")

shelf_labels = []

for detection in result:
    box, text, confidence = detection
    x_center = int(sum(pt[0] for pt in box) / 4)
    y_center = int(sum(pt[1] for pt in box) / 4)
    
    # Normalize the text — handle common OCR mistakes
    # OCR often reads 'S' as '5' or '$'
    text_clean = text.upper().replace(" ", "").replace(".", "-")
    text_normalized = text_clean.replace("5-", "S-").replace("$-", "S-")
    
    # Check for S-1 through S-6 patterns
    for i in range(1, 7):
        patterns = [f"S-{i}", f"S{i}", f"5-{i}"]
        if text_clean in patterns or text_normalized in patterns:
            shelf_labels.append({
                "shelf": i,
                "raw_text": text,
                "y": y_center,
                "x": x_center,
                "confidence": confidence
            })
            print(f"🎯 Shelf S-{i}: detected as '{text}' at (x={x_center}, y={y_center}) confidence {confidence:.2f}")
            break

print(f"\n=== Summary: {len(shelf_labels)}/6 shelf labels detected ===\n")

# Sort by shelf number
shelf_labels.sort(key=lambda x: x["shelf"])
for s in shelf_labels:
    print(f"   Shelf {s['shelf']}: y={s['y']}")

# Check if we have all 6
missing = [i for i in range(1, 7) if not any(s['shelf'] == i for s in shelf_labels)]
if missing:
    print(f"\n⚠️  Missing shelves: {missing}")
else:
    print(f"\n✅ All 6 shelves detected! Ready for Stage 2 (shelf cropping)")

# Save shelf boundaries for the next stage
import json
with open("data/shelf_boundaries.json", "w") as f:
    json.dump({
        "image_path": IMAGE_PATH,
        "image_width": w,
        "image_height": h,
        "shelves": shelf_labels
    }, f, indent=2)

print(f"\n📁 Saved shelf boundaries to: data/shelf_boundaries.json")