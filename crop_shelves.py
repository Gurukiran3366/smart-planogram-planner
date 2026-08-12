# crop_shelves.py
import cv2
import json
import os
from pathlib import Path

# Load shelf boundaries from Stage 1
with open("data/shelf_boundaries.json", "r") as f:
    boundaries = json.load(f)

IMAGE_PATH = boundaries["image_path"]
IMAGE_HEIGHT = boundaries["image_height"]
IMAGE_WIDTH = boundaries["image_width"]
shelves = sorted(boundaries["shelves"], key=lambda x: x["shelf"])

# Load the original image
img = cv2.imread(IMAGE_PATH)
if img is None:
    print(f"❌ Could not load image: {IMAGE_PATH}")
    exit()

print(f"✅ Loaded image: {IMAGE_WIDTH} x {IMAGE_HEIGHT}\n")

# Create output folder
output_dir = Path("images/shelves")
output_dir.mkdir(parents=True, exist_ok=True)

# Calculate crop boundaries
# Strategy: each shelf's content is from its label Y-coordinate down to the NEXT shelf's label Y-coordinate
# For the last shelf (S-6), extend to the bottom of the image

# We also crop horizontally to skip the label area on the left (labels are around x=300-350)
# The chiller content itself starts around x=350 and ends near the right side
# Looking at typical chiller image: crop from x=350 to x=1150 (removes label column and right edge)
CROP_LEFT = 350   # skip the shelf label column
CROP_RIGHT = 1150  # skip glass edge on the right

# Add a small padding to include products that sit at the very top/bottom of the shelf
Y_PADDING = 15

print("=== Cropping shelves ===\n")

shelf_crops = []

for i, shelf in enumerate(shelves):
    shelf_num = shelf["shelf"]
    y_start = shelf["y"] - Y_PADDING  # small padding above
    
    # y_end = next shelf's Y, or image bottom for last shelf
    if i + 1 < len(shelves):
        y_end = shelves[i + 1]["y"] - Y_PADDING
    else:
        y_end = IMAGE_HEIGHT
    
    # Clamp to image bounds
    y_start = max(0, y_start)
    y_end = min(IMAGE_HEIGHT, y_end)
    
    # Crop the shelf strip
    shelf_img = img[y_start:y_end, CROP_LEFT:CROP_RIGHT]
    
    # Save the crop
    output_path = output_dir / f"shelf_{shelf_num}.jpg"
    cv2.imwrite(str(output_path), shelf_img)
    
    h, w = shelf_img.shape[:2]
    print(f"✅ Shelf {shelf_num}: cropped {w}x{h} px  →  saved to {output_path}")
    
    shelf_crops.append({
        "shelf_number": shelf_num,
        "image_path": str(output_path),
        "y_start_original": y_start,
        "y_end_original": y_end,
        "width": w,
        "height": h
    })

# Also create a "debug" version of original image with shelf boundaries drawn on it
# This helps verify the crops visually
debug_img = img.copy()
for shelf in shelves:
    y = shelf["y"]
    cv2.line(debug_img, (0, y), (IMAGE_WIDTH, y), (0, 255, 0), 3)
    cv2.putText(debug_img, f"S-{shelf['shelf']}", (10, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)

# Draw the horizontal crop boundaries
cv2.line(debug_img, (CROP_LEFT, 0), (CROP_LEFT, IMAGE_HEIGHT), (255, 0, 0), 2)
cv2.line(debug_img, (CROP_RIGHT, 0), (CROP_RIGHT, IMAGE_HEIGHT), (255, 0, 0), 2)

cv2.imwrite("images/shelves/_debug_boundaries.jpg", debug_img)
print(f"\n📸 Debug image with visible boundaries: images/shelves/_debug_boundaries.jpg")

# Save crop info
with open("data/shelf_crops.json", "w") as f:
    json.dump({
        "original_image": IMAGE_PATH,
        "crops": shelf_crops
    }, f, indent=2)

print(f"📁 Crop metadata saved to: data/shelf_crops.json")
print(f"\n✅ Stage 2 complete! Open the images in images/shelves/ to verify.")