# scoring_engine.py
"""
Milestone 5: Scoring + Correction Engine
Turns raw violations into staff-friendly audit reports.
"""

import json
import sys
from pathlib import Path
import json as _json
from pathlib import Path
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
COMPARISONS_DIR = Path("data/comparisons")
REPORTS_DIR = Path("data/reports")

# Scoring weights per violation type
# Higher weight = bigger score deduction
VIOLATION_WEIGHTS = {
    "wrong_commodity_on_shelf": 15,
    "missing_product": 10,
    "wrong_shelf": 8,
    "duplicate_on_wrong_shelf": 6,
    "missing_product_partial": 5,
    "wrong_zone": 4,
    "low_facing": 3,
    "excess_facing_non_fast_moving": 2,
    "unknown_product": 2,
    "expected_but_out_of_stock": 0,  # ← NEW: no penalty for OOS
    "low_confidence_detection": 0
}

# Priority ranking for display order
# Lower number = higher priority (shown first)
PRIORITY_ORDER = {
    "wrong_commodity_on_shelf": 1,
    "missing_product": 2,
    "wrong_shelf": 3,
    "duplicate_on_wrong_shelf": 4,
    "missing_product_partial": 5,
    "wrong_zone": 6,
    "low_facing": 7,
    "excess_facing_non_fast_moving": 8,
    "unknown_product": 9,
    "expected_but_out_of_stock": 10,  # ← NEW
    "low_confidence_detection": 11
}

# Score thresholds and status
def get_score_status(score):
    if score >= 9.0:
        return "🌟 EXCELLENT", "Rack meets high standards"
    elif score >= 7.5:
        return "✅ GOOD", "Minor improvements needed"
    elif score >= 6.0:
        return "🟡 NEEDS ATTENTION", "Several issues to address"
    elif score >= 4.0:
        return "🟠 POOR", "Major reorganization needed"
    else:
        return "🔴 CRITICAL", "Immediate action required"


def calculate_score(violations, total_expected_products=46):
    """
    Percentage-based scoring aligned with real retail audit systems.
    
    Base score = percentage of products correctly placed
    Then apply penalties for structural issues (wrong commodity, etc.)
    
    This produces intuitive scores:
      - Perfect chiller: 10.0
      - Minor issues: 8-9
      - Some misplacements: 6-7
      - Significant issues: 4-5
      - Very poor: 2-3
    """
    if not violations:
        return 10.0
    
    # ─────────────────────────────────────────────
    # Step 1: Count "properly placed" products
    # A product is properly placed if it has NO high/medium violations
    # ─────────────────────────────────────────────
    problem_products = set()
    
    for v in violations:
        # OOS is expected behavior, not a problem
        if v["type"] == "expected_but_out_of_stock":
            continue
        
        # These violations mean the product isn't properly placed
        blocking_violations = [
            "missing_product",
            "missing_product_partial",
            "wrong_shelf",
            "wrong_commodity_on_shelf",
            "duplicate_on_wrong_shelf"
        ]
        if v["type"] in blocking_violations:
            problem_products.add(v.get("product_id", v.get("description", "")))
    
    problem_count = len(problem_products)
    properly_placed = max(0, total_expected_products - problem_count)
    placement_ratio = properly_placed / total_expected_products
    
    # Base score from placement (out of 10)
    base_score = placement_ratio * 10
    
    # ─────────────────────────────────────────────
    # Step 2: Deduct for minor issues (zone/facing)
    # These are less critical but still affect score
    # ─────────────────────────────────────────────
    minor_deductions = 0
    for v in violations:
        if v["type"] in ["wrong_zone"]:
            minor_deductions += 0.15  # -0.15 per zone issue
        elif v["type"] in ["low_facing", "excess_facing_non_fast_moving"]:
            minor_deductions += 0.10  # -0.10 per facing issue
    
    # Cap total minor deductions at 2.0 points
    minor_deductions = min(2.0, minor_deductions)
    
    # ─────────────────────────────────────────────
    # Step 3: Apply structural penalty for wrong commodity
    # (products on completely wrong shelf-type)
    # ─────────────────────────────────────────────
    wrong_commodity_count = sum(1 for v in violations if v["type"] == "wrong_commodity_on_shelf")
    commodity_penalty = min(1.5, wrong_commodity_count * 0.5)
    
    # ─────────────────────────────────────────────
    # Step 4: Final score with floor and ceiling
    # ─────────────────────────────────────────────
    score = base_score - minor_deductions - commodity_penalty
    score = round(max(1.0, min(10.0, score)), 1)  # Floor at 1.0, ceiling at 10.0
    
    return score



def prioritize_violations(violations, top_n=5):
    """
    Rank violations by priority, return top N most important.
    """
    def sort_key(v):
        # Sort by: priority order, then by severity, then by type
        severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
        return (
            PRIORITY_ORDER.get(v["type"], 99),
            severity_rank.get(v["severity"], 99)
        )
    
    sorted_violations = sorted(violations, key=sort_key)
    return sorted_violations[:top_n]


def format_whatsapp_message(comparison_data, score, top_fixes):
    """
    Format audit report as WhatsApp-ready message.
    Mobile-friendly, emoji-based, short and actionable.
    """
    counts = comparison_data["violation_counts"]
    rack_id = comparison_data.get("rack_id", "Unknown")
    total = counts["total"]
    
    status, status_desc = get_score_status(score)
    
    # Build message
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 *CHILLER AUDIT*")
    lines.append(f"Rack: {rack_id}")
    lines.append(f"Time: {datetime.now().strftime('%d %b %Y, %H:%M')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"⭐ *Score: {score}/10*")
    lines.append(f"{status}")
    lines.append(f"_{status_desc}_")
    lines.append("")
    
    if total == 0:
        lines.append("✅ *Perfect assortment!*")
        lines.append("No corrections needed.")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    
    lines.append(f"📋 *Issues found:* {total}")
    if counts["high"] > 0:
        lines.append(f"  🔴 Critical: {counts['high']}")
    if counts["medium"] > 0:
        lines.append(f"  🟡 Moderate: {counts['medium']}")
    if counts["low"] > 0:
        lines.append(f"  🟢 Minor: {counts['low']}")
    lines.append("")
    
    # Top 5 fixes section
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🎯 *TOP FIXES* (do these first):")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    
    for i, v in enumerate(top_fixes, 1):
        icon = "🔴" if v["severity"] == "high" else "🟡" if v["severity"] == "medium" else "🟢"
        lines.append(f"{i}. {icon} {v['correction']}")
        lines.append("")
    
    remaining = total - len(top_fixes)
    if remaining > 0:
        lines.append(f"_...plus {remaining} more improvements_")
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📸 *Fix top items and resend photo*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    
    return "\n".join(lines)


def format_detailed_report(comparison_data, score, all_violations):
    """
    Full detailed report for review by manager or for audit history.
    """
    counts = comparison_data["violation_counts"]
    rack_id = comparison_data.get("rack_id", "Unknown")
    status, status_desc = get_score_status(score)
    
    lines = []
    lines.append("=" * 70)
    lines.append("DETAILED CHILLER AUDIT REPORT")
    lines.append("=" * 70)
    lines.append(f"Rack ID:      {rack_id}")
    lines.append(f"Date:         {datetime.now().strftime('%d %B %Y, %H:%M')}")
    lines.append(f"Source:       {comparison_data.get('actual_source', 'N/A')}")
    lines.append("")
    lines.append(f"OVERALL SCORE: {score}/10 — {status}")
    lines.append(f"Status:       {status_desc}")
    lines.append("")
    lines.append(f"Total issues: {counts['total']}")
    lines.append(f"  🔴 High:    {counts['high']}")
    lines.append(f"  🟡 Medium:  {counts['medium']}")
    lines.append(f"  🟢 Low:     {counts['low']}")
    lines.append(f"  ℹ️  Info:    {counts['info']}")
    lines.append("")
    
    # Group violations by type
    by_type = {}
    for v in all_violations:
        vtype = v["type"]
        if vtype not in by_type:
            by_type[vtype] = []
        by_type[vtype].append(v)
    
    # Print in priority order
    type_labels = {
        "wrong_commodity_on_shelf": "❌ Wrong Commodity on Shelf",
        "missing_product": "📦 Missing Products",
        "wrong_shelf": "🔀 Wrong Shelf Placement",
        "duplicate_on_wrong_shelf": "👥 Duplicate on Wrong Shelf",
        "missing_product_partial": "📦 Partially Missing",
        "wrong_zone": "🎯 Wrong Zone",
        "low_facing": "⬆️  Facing Too Low",
        "excess_facing_non_fast_moving": "⬇️  Facing Too High",
        "unknown_product": "❓ Unknown Products",
        "low_confidence_detection": "⚠️  Low Confidence Detections"
    }
    
    sorted_types = sorted(by_type.keys(), key=lambda t: PRIORITY_ORDER.get(t, 99))
    
    for vtype in sorted_types:
        label = type_labels.get(vtype, vtype)
        issues = by_type[vtype]
        weight = VIOLATION_WEIGHTS.get(vtype, 0)
        
        lines.append("-" * 70)
        lines.append(f"{label}  ({len(issues)} issues, -{weight} points each)")
        lines.append("-" * 70)
        
        for v in issues:
            lines.append(f"  • {v['description']}")
            lines.append(f"    → {v['correction']}")
        lines.append("")
    
    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)
    
    return "\n".join(lines)


def generate_audit_report(comparison_file):
    """
    Main function: read comparison JSON, produce score + reports.
    """
    print(f"\n{'='*70}")
    print(f"GENERATING AUDIT REPORT")
    print(f"Source: {comparison_file}")
    print(f"{'='*70}\n")
    
    # Load comparison data
    with open(comparison_file, "r", encoding="utf-8") as f:
        comparison = json.load(f)
    
    violations = comparison.get("violations", [])
    counts = comparison["violation_counts"]
    
    print(f"📊 Loaded {counts['total']} violations")
    print(f"   🔴 High: {counts['high']}")
    print(f"   🟡 Medium: {counts['medium']}")
    print(f"   🟢 Low: {counts['low']}")
    print(f"   ℹ️  Info: {counts['info']}")
    print()
    
    # Load expected map to get total product count for percentage calculation
    expected_map_file = Path("data/expected_map_BTM_CH01.json")
    if expected_map_file.exists():
        with open(expected_map_file, "r", encoding="utf-8") as f:
            expected = json.load(f)
        total_expected = sum(len(s.get("products", [])) for s in expected.get("shelves", []))
    else:
        total_expected = 46  # fallback
    
    # Calculate score
    score = calculate_score(violations, total_expected)
    status, status_desc = get_score_status(score)
    
    print(f"⭐ Calculated Score: {score}/10")
    print(f"   Based on: {total_expected} expected products")
    print(f"   Status: {status}")
    print(f"   {status_desc}")
    print()
    
    # Get top 5 priority fixes
    top_fixes = prioritize_violations(violations, top_n=5)
    
    print(f"🎯 Top {len(top_fixes)} priority fixes identified")
    print()
    
    # Generate WhatsApp message
    whatsapp_msg = format_whatsapp_message(comparison, score, top_fixes)
    
    # Generate detailed report
    detailed_report = format_detailed_report(comparison, score, violations)
    
    # Save outputs
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    audit_name = Path(comparison_file).stem.replace("comparison_", "")
    
    whatsapp_file = REPORTS_DIR / f"whatsapp_{audit_name}.txt"
    with open(whatsapp_file, "w", encoding="utf-8") as f:
        f.write(whatsapp_msg)
    
    detailed_file = REPORTS_DIR / f"detailed_{audit_name}.txt"
    with open(detailed_file, "w", encoding="utf-8") as f:
        f.write(detailed_report)
    
    # Save JSON summary
    summary_file = REPORTS_DIR / f"summary_{audit_name}.json"
    summary = {
        "rack_id": comparison.get("rack_id"),
        "audit_date": datetime.now().isoformat(),
        "score": score,
        "status": status,
        "status_description": status_desc,
        "violation_counts": counts,
        "total_expected_products": total_expected,
        "top_fixes": [
            {
                "priority": i + 1,
                "type": v["type"],
                "severity": v["severity"],
                "correction": v["correction"]
            }
            for i, v in enumerate(top_fixes)
        ],
        "source_comparison": str(comparison_file)
    }
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"📁 Files saved:")
    print(f"   📱 WhatsApp:  {whatsapp_file}")
    print(f"   📄 Detailed:  {detailed_file}")
    print(f"   📊 Summary:   {summary_file}")
    print()
    
    # Print the WhatsApp message so user can see it immediately
    print("=" * 70)
    print("STAFF-FACING MESSAGE (WhatsApp format):")
    print("=" * 70)
    print()
    print(whatsapp_msg)
    print()
    
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Process all comparison files
        comparison_files = sorted(COMPARISONS_DIR.glob("comparison_*.json"))
        if not comparison_files:
            print("❌ No comparison files found. Run compare_engine.py first.")
            sys.exit(1)
        
        print(f"Processing {len(comparison_files)} comparison files...\n")
        for cf in comparison_files:
            generate_audit_report(str(cf))
    else:
        generate_audit_report(sys.argv[1])