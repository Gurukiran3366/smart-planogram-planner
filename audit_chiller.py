# audit_chiller.py
"""
MAIN AUDIT PIPELINE — Milestone 5 Complete
The single entry point that runs the full audit end-to-end.

Flow:
  1. Image quality check (fail-fast)
  2. Shelf detection (fail-fast if <4 shelves)
  3. AI analysis
  4. Sanity validation (fail-fast if AI hallucinated)
  5. Comparison against reference
  6. Scoring + priority ranking
  7. Return staff-friendly report

If any stage fails → clear rejection message, no false results.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Import from our existing scripts
from process_staff_photo import process_photo
from validate_actual_map import validate_actual_map, get_staff_rejection_message
from compare_engine import compare_maps
from scoring_engine import generate_audit_report


# ============================================================
# CONFIG
# ============================================================
AUDIT_LOG_DIR = Path("data/audit_logs")


def run_full_audit(image_path):
    """
    End-to-end audit pipeline with fail-fast validation at every stage.
    Returns dict with status and either report OR rejection message.
    """
    audit_start = datetime.now()
    audit_id = audit_start.strftime("%Y%m%d_%H%M%S")
    photo_name = Path(image_path).stem
    
    print(f"\n{'#'*70}")
    print(f"# STARTING AUDIT")
    print(f"# Audit ID: {audit_id}")
    print(f"# Image: {image_path}")
    print(f"{'#'*70}\n")
    
    # ═════════════════════════════════════════════════════════
    # STAGE 1-3: Image processing + AI analysis
    # (These are handled inside process_photo)
    # ═════════════════════════════════════════════════════════
    print("┌" + "─"*68 + "┐")
    print("│ STAGE 1-3: IMAGE PROCESSING + AI ANALYSIS                          │")
    print("└" + "─"*68 + "┘")
    
    try:
        actual_map_file = process_photo(image_path)
        if actual_map_file is None:
            return {
                "status": "REJECTED_IMAGE_QUALITY",
                "audit_id": audit_id,
                "message": build_rejection_message([
                    "Image quality check failed",
                    "Photo may be blurry, too dark, or too low resolution"
                ]),
                "log_saved": save_audit_log(audit_id, image_path, "REJECTED_IMAGE_QUALITY", None, None, None)
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "audit_id": audit_id,
            "message": f"System error during image processing: {e}",
            "log_saved": save_audit_log(audit_id, image_path, "ERROR", None, None, str(e))
        }
    
    # ═════════════════════════════════════════════════════════
    # STAGE 4: Sanity validation on AI output
    # ═════════════════════════════════════════════════════════
    print("\n┌" + "─"*68 + "┐")
    print("│ STAGE 4: SANITY VALIDATION (AI hallucination check)                │")
    print("└" + "─"*68 + "┘")
    
    validation = validate_actual_map(str(actual_map_file))
    
    if validation["status"] == "REJECT":
        rejection_msg = get_staff_rejection_message(validation)
        print(f"\n❌ AI output failed sanity check — audit REJECTED")
        print(f"   Reasons:")
        for issue in validation["critical_issues"]:
            print(f"     → {issue['message']}")
        
        return {
            "status": "REJECTED_AI_UNRELIABLE",
            "audit_id": audit_id,
            "message": rejection_msg,
            "validation_details": validation,
            "log_saved": save_audit_log(
                audit_id, image_path, "REJECTED_AI_UNRELIABLE",
                str(actual_map_file), None, validation
            )
        }
    
    warning_level = validation["status"]
    print(f"\n✅ Sanity check {warning_level}")
    if warning_level == "WARNING":
        print(f"   Note: {len(validation['warnings'])} warnings detected but proceeding")
    
    # ═════════════════════════════════════════════════════════
    # STAGE 5: Comparison against reference
    # ═════════════════════════════════════════════════════════
    print("\n┌" + "─"*68 + "┐")
    print("│ STAGE 5: COMPARISON AGAINST REFERENCE                              │")
    print("└" + "─"*68 + "┘")
    
    try:
        comparison_result = compare_maps(str(actual_map_file))
        
        # Locate the saved comparison file
        comparison_file = Path("data/comparisons") / f"comparison_{photo_name}.json"
        
        if not comparison_file.exists():
            raise FileNotFoundError(f"Comparison file not created: {comparison_file}")
    except Exception as e:
        return {
            "status": "ERROR",
            "audit_id": audit_id,
            "message": f"System error during comparison: {e}",
            "log_saved": save_audit_log(audit_id, image_path, "ERROR", str(actual_map_file), None, str(e))
        }
    
    # ═════════════════════════════════════════════════════════
    # STAGE 6: Scoring + staff-friendly report
    # ═════════════════════════════════════════════════════════
    print("\n┌" + "─"*68 + "┐")
    print("│ STAGE 6: SCORING + REPORT GENERATION                               │")
    print("└" + "─"*68 + "┘")
    
    try:
        report_summary = generate_audit_report(str(comparison_file))
    except Exception as e:
        return {
            "status": "ERROR",
            "audit_id": audit_id,
            "message": f"System error during scoring: {e}",
            "log_saved": save_audit_log(audit_id, image_path, "ERROR", str(actual_map_file), str(comparison_file), str(e))
        }
    
    # ═════════════════════════════════════════════════════════
    # AUDIT COMPLETE
    # ═════════════════════════════════════════════════════════
    audit_duration = (datetime.now() - audit_start).total_seconds()
    
    print(f"\n{'#'*70}")
    print(f"# ✅ AUDIT COMPLETE in {audit_duration:.1f} seconds")
    print(f"# Score: {report_summary['score']}/10 — {report_summary['status']}")
    print(f"{'#'*70}\n")
    
    # Read the WhatsApp message that was generated
    whatsapp_file = Path("data/reports") / f"whatsapp_{photo_name}.txt"
    whatsapp_msg = whatsapp_file.read_text(encoding="utf-8") if whatsapp_file.exists() else ""
    
    return {
        "status": "SUCCESS",
        "audit_id": audit_id,
        "score": report_summary["score"],
        "score_status": report_summary["status"],
        "violation_counts": report_summary["violation_counts"],
        "top_fixes": report_summary["top_fixes"],
        "whatsapp_message": whatsapp_msg,
        "duration_seconds": audit_duration,
        "validation_warnings": validation.get("warnings", []),
        "log_saved": save_audit_log(
            audit_id, image_path, "SUCCESS",
            str(actual_map_file), str(comparison_file), report_summary
        )
    }


def build_rejection_message(reasons):
    """Build a generic rejection message when image quality fails."""
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("❌ *AUDIT FAILED*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("*Reasons:*")
    for reason in reasons:
        lines.append(f"• {reason}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📸 *Please retake the photo*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("*Checklist:*")
    lines.append("✅ Full chiller visible top-to-bottom")
    lines.append("✅ All 6 shelf labels (S-1 to S-6) readable")
    lines.append("✅ Photo taken straight-on (not tilted)")
    lines.append("✅ Good lighting, no shadows/glare")
    lines.append("✅ Stand on the marked spot on floor")
    return "\n".join(lines)


def save_audit_log(audit_id, image_path, status, actual_map_file, comparison_file, extra_info):
    """Save an audit log entry for history/dashboard use."""
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = AUDIT_LOG_DIR / f"audit_{audit_id}.json"
    
    log = {
        "audit_id": audit_id,
        "timestamp": datetime.now().isoformat(),
        "image_path": str(image_path),
        "status": status,
        "actual_map_file": actual_map_file,
        "comparison_file": comparison_file
    }
    
    if isinstance(extra_info, dict):
        if "score" in extra_info:
            log["score"] = extra_info["score"]
            log["score_status"] = extra_info.get("status")
            log["violation_counts"] = extra_info.get("violation_counts")
        elif "critical_issues" in extra_info:
            log["validation"] = extra_info
    elif isinstance(extra_info, str):
        log["error_message"] = extra_info
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    
    return str(log_file)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Test all staff uploads
        upload_dir = Path("images/staff_uploads")
        photos = sorted(upload_dir.glob("*.jp*g"))
        
        print(f"Running full audit pipeline on {len(photos)} test photos...\n")
        
        results_summary = []
        for photo in photos:
            result = run_full_audit(str(photo))
            results_summary.append({
                "photo": photo.name,
                "status": result["status"],
                "score": result.get("score", "N/A")
            })
        
        # Final summary
        print("\n" + "="*70)
        print("BATCH AUDIT SUMMARY")
        print("="*70)
        print(f"{'Photo':<30} {'Status':<25} {'Score':<10}")
        print("-"*70)
        for r in results_summary:
            score_str = f"{r['score']}/10" if isinstance(r['score'], (int, float)) else r['score']
            print(f"{r['photo']:<30} {r['status']:<25} {score_str:<10}")
    else:
        result = run_full_audit(sys.argv[1])
        
        print("\n" + "="*70)
        print("FINAL RESULT")
        print("="*70)
        print(f"Status: {result['status']}")
        
        if result["status"] == "SUCCESS":
            print(f"Score: {result['score']}/10 — {result['score_status']}")
            print(f"Duration: {result['duration_seconds']:.1f}s")
            print("\n" + "="*70)
            print("STAFF MESSAGE:")
            print("="*70)
            print(result["whatsapp_message"])
        else:
            print("\n" + "="*70)
            print("REJECTION MESSAGE FOR STAFF:")
            print("="*70)
            print(result["message"])