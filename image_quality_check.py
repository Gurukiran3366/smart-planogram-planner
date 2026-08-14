# image_quality_check.py
import cv2
import numpy as np
from pathlib import Path

def check_image_quality(image_path):
    """
    Analyzes an image and returns a quality report.
    Returns dict with: {status, issues, metrics}
    Status: 'usable', 'warning', 'rejected'
    """
    img = cv2.imread(image_path)
    if img is None:
        return {
            "status": "rejected",
            "issues": ["Cannot read image file"],
            "metrics": {}
        }
    
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    issues = []
    metrics = {}
    
    # 1. Check resolution
    metrics["resolution"] = f"{w}x{h}"
    if w < 600 or h < 800:
        issues.append(f"Resolution too low: {w}x{h} (need at least 600x800)")
    
    # 2. Check blur (Laplacian variance)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    metrics["blur_score"] = round(blur_score, 1)
    if blur_score < 100:
        issues.append(f"Image is blurry (score {blur_score:.1f}, need ≥100)")
    
    # 3. Check brightness
    brightness = gray.mean()
    metrics["brightness"] = round(brightness, 1)
    if brightness < 50:
        issues.append(f"Image too dark (brightness {brightness:.1f}, need ≥50)")
    elif brightness > 220:
        issues.append(f"Image overexposed (brightness {brightness:.1f}, need ≤220)")
    
    # 4. Check contrast (standard deviation)
    contrast = gray.std()
    metrics["contrast"] = round(contrast, 1)
    if contrast < 30:
        issues.append(f"Image lacks contrast ({contrast:.1f}, need ≥30) — likely dim or flat lighting")
    
    # 5. Check aspect ratio (should be portrait for chiller)
    aspect_ratio = h / w
    metrics["aspect_ratio"] = round(aspect_ratio, 2)
    if aspect_ratio < 1.0:
        issues.append(f"Image is landscape (ratio {aspect_ratio:.2f}), chiller photos should be portrait")
    
    # Determine overall status
    if not issues:
        status = "usable"
    elif len(issues) == 1 and "brightness" in issues[0].lower():
        status = "warning"  # can proceed but flag it
    else:
        status = "rejected"
    
    return {
        "status": status,
        "issues": issues,
        "metrics": metrics
    }


# Test on all staff upload photos
if __name__ == "__main__":
    upload_dir = Path("images/staff_uploads")
    
    if not upload_dir.exists():
        print(f"❌ Folder not found: {upload_dir}")
        exit()
    
    print("=" * 70)
    print("IMAGE QUALITY REPORT for all staff uploads")
    print("=" * 70)
    
    photos = sorted(upload_dir.glob("*.jp*g")) + sorted(upload_dir.glob("*.png"))
    
    if not photos:
        print("No photos found in staff_uploads folder")
        exit()
    
    for photo in photos:
        print(f"\n📸 {photo.name}")
        print("-" * 60)
        
        result = check_image_quality(str(photo))
        
        # Status indicator
        icon = "✅" if result["status"] == "usable" else "⚠️" if result["status"] == "warning" else "❌"
        print(f"   {icon} Status: {result['status'].upper()}")
        
        # Metrics
        for key, val in result["metrics"].items():
            print(f"      {key}: {val}")
        
        # Issues
        if result["issues"]:
            print(f"\n   Issues found:")
            for issue in result["issues"]:
                print(f"      • {issue}")
    
    print("\n" + "=" * 70)
    print("Legend: ✅ usable  ⚠️ warning (proceed with caution)  ❌ rejected")
    print("=" * 70)