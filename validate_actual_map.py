# validate_actual_map.py
"""
Post-AI Sanity Validation
Detects likely AI hallucinations in the actual_map JSON.
Rejects the audit if AI clearly failed.
"""

import json
import sys
from pathlib import Path


# Physical limits per shelf
MAX_PRODUCTS_PER_SHELF = 12       # Physical max products on one shelf
MAX_FACINGS_PER_PRODUCT = 5       # Max facings for one product

# Total chiller product count ranges
MIN_TOTAL_PRODUCTS = 5            # Below this = AI failure
LOW_TOTAL_PRODUCTS = 20           # Below this = warning
HIGH_TOTAL_PRODUCTS = 65          # Above this = likely hallucination
CRITICAL_HIGH_TOTAL = 75          # Definitely hallucination


def validate_actual_map(actual_map_file):
    """Validate an actual_map JSON for AI hallucination signs."""
    with open(actual_map_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    warnings = []
    critical_issues = []
    total_products = 0
    
    for shelf in data.get("shelves", []):
        shelf_num = shelf["shelf_number"]
        products = shelf.get("products", [])
        num_products = len(products)
        total_products += num_products
        
        # Check 1: Too many products on one shelf
        if num_products > MAX_PRODUCTS_PER_SHELF:
            critical_issues.append({
                "type": "impossible_product_count",
                "shelf": shelf_num,
                "detected_count": num_products,
                "message": f"Shelf {shelf_num} has {num_products} products detected — physically unlikely (max {MAX_PRODUCTS_PER_SHELF}). AI likely mixed shelves."
            })
        
        # Check 2: Duplicate product IDs on same shelf
        product_ids = [p["product_id"] for p in products]
        duplicates = {pid for pid in product_ids if product_ids.count(pid) > 1}
        if duplicates:
            warnings.append({
                "type": "duplicate_products_same_shelf",
                "shelf": shelf_num,
                "duplicates": list(duplicates),
                "message": f"Shelf {shelf_num} has duplicate detections: {list(duplicates)} (should use facings=2 instead)"
            })
        
        # Check 3: Excessive facings
        for p in products:
            if p.get("facings", 1) > MAX_FACINGS_PER_PRODUCT:
                warnings.append({
                    "type": "excessive_facings",
                    "shelf": shelf_num,
                    "product_id": p["product_id"],
                    "facings": p["facings"],
                    "message": f"Shelf {shelf_num} {p['product_id']}: {p['facings']} facings is unusual"
                })
    
    # Check 4: Total count too high (hallucination)
    if total_products >= CRITICAL_HIGH_TOTAL:
        critical_issues.append({
            "type": "total_count_impossibly_high",
            "total_detected": total_products,
            "message": f"Total {total_products} products across all shelves — impossible. AI clearly hallucinated."
        })
    elif total_products >= HIGH_TOTAL_PRODUCTS:
        warnings.append({
            "type": "total_count_high",
            "total_detected": total_products,
            "message": f"Total {total_products} products — unusually high (typical: 40-60)"
        })
    
    # Check 5: Total count too low (AI failure)
    if total_products < MIN_TOTAL_PRODUCTS:
        critical_issues.append({
            "type": "detection_failure",
            "total_detected": total_products,
            "message": f"Only {total_products} products detected — AI failed. Photo unusable."
        })
    elif total_products < LOW_TOTAL_PRODUCTS:
        warnings.append({
            "type": "total_count_too_low",
            "total_detected": total_products,
            "message": f"Only {total_products} products detected — chiller may be sparse or photo quality poor"
        })
    
    # Determine overall status
    if critical_issues:
        status = "REJECT"
    elif len(warnings) >= 3:
        status = "WARNING"
    else:
        status = "PASS"
    
    return {
        "status": status,
        "actual_map_file": str(actual_map_file),
        "total_products": total_products,
        "warnings": warnings,
        "critical_issues": critical_issues
    }


def get_staff_rejection_message(validation):
    """Generate a staff-friendly rejection message."""
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("❌ *AUDIT FAILED*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("The AI could not reliably analyze your photo.")
    lines.append("")
    lines.append("*Detected issues:*")
    
    for issue in validation["critical_issues"]:
        lines.append(f"• {issue['message']}")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📸 *Please retake the photo*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("*Check the following:*")
    lines.append("✅ All 6 shelf labels (S-1 to S-6) visible")
    lines.append("✅ Full chiller in frame (top to bottom)")
    lines.append("✅ Photo taken straight-on (not tilted)")
    lines.append("✅ Good lighting, no shadows/glare")
    lines.append("✅ Stand on the marked spot on floor")
    lines.append("")
    lines.append("Then upload again.")
    
    return "\n".join(lines)


def print_validation_report(validation):
    print(f"\n{'='*70}")
    print(f"SANITY VALIDATION REPORT")
    print(f"File: {validation['actual_map_file']}")
    print(f"{'='*70}\n")
    
    status = validation["status"]
    if status == "PASS":
        icon = "✅"
    elif status == "WARNING":
        icon = "⚠️"
    else:
        icon = "❌"
    
    print(f"{icon} Status: {status}")
    print(f"📊 Total products detected: {validation['total_products']}")
    print()
    
    if validation["critical_issues"]:
        print("🔴 CRITICAL ISSUES (audit should be rejected):")
        for issue in validation["critical_issues"]:
            print(f"   → {issue['message']}")
        print()
    
    if validation["warnings"]:
        print("🟡 WARNINGS (audit may be unreliable):")
        for warning in validation["warnings"]:
            print(f"   → {warning['message']}")
        print()
    
    if status == "PASS":
        print("✅ Data looks reasonable — proceed to comparison")
    elif status == "WARNING":
        print("⚠️  Some issues detected — comparison may be unreliable")
    else:
        print("❌ REJECT — Ask staff to retake photo. Do NOT show comparison to staff.")
        print("\nStaff-facing message that would be sent:")
        print("─" * 60)
        print(get_staff_rejection_message(validation))
        print("─" * 60)
    
    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        actual_dir = Path("data/actual_maps")
        files = sorted(actual_dir.glob("actual_map_*.json"))
        for f in files:
            v = validate_actual_map(f)
            print_validation_report(v)
    else:
        v = validate_actual_map(sys.argv[1])
        print_validation_report(v)