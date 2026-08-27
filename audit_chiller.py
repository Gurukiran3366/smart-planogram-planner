# audit_chiller.py
"""
MAIN AUDIT PIPELINE — Production Orchestrator
The application entry point that runs the complete audit and physical-action pipeline.

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


def run_full_audit(image_path, expected_map=None, rules=None):
    """Production application entry point for the complete planogram pipeline."""
    import subprocess
    import sys

    audit_start = datetime.now()
    audit_id = audit_start.strftime("%Y%m%d_%H%M%S")
    root = Path(__file__).resolve().parent
    photo = Path(image_path).resolve()
    expected = Path(expected_map).resolve() if expected_map else root / "data" / "expected_map_BTM_CH01.json"
    rules_path = Path(rules).resolve() if rules else root / "data" / "merchandising_rules_v2.json"

    actual = root / "data" / "actual_maps" / "actual_map_wrongshelf.json"
    analysis = root / "data" / "analyses" / "analysis_actual_map_wrongshelf.json"
    misplacements = root / "data" / "analyses" / "misplacements_v2_analysis_actual_map_wrongshelf.json"
    corrections = root / "data" / "analyses" / "corrections_v2_misplacements_v2_analysis_actual_map_wrongshelf.json"
    occurrences = root / "data" / "analyses" / "occurrences_corrections_v2_misplacements_v2_analysis_actual_map_wrongshelf.json"
    rearrangements = root / "data" / "analyses" / "rearrangements_corrections_v2_misplacements_v2_analysis_actual_map_wrongshelf.json"
    cycles = root / "data" / "analyses" / "cycles_corrections_v2_misplacements_v2_analysis_actual_map_wrongshelf.json"
    dependencies = root / "data" / "analyses" / "dependencies_occurrences_corrections_v2_misplacements_v2_analysis_actual_map_wrongshelf.json"
    final_recommendations = root / "data" / "analyses" / "final_recommendations_corrections_v2_misplacements_v2_analysis_actual_map_wrongshelf.json"
    staff_actions = root / "data" / "analyses" / f"staff_actions_{photo.stem}.json"
    staff_message = root / "data" / "reports" / f"staff_actions_{photo.stem}.txt"

    def fail(status, message, actual_file=None, comparison_file=None, extra=None):
        return {
            "status": status,
            "audit_id": audit_id,
            "message": message,
            "duration_seconds": (datetime.now() - audit_start).total_seconds(),
            "actual_map_file": str(actual_file) if actual_file else None,
            "comparison_file": str(comparison_file) if comparison_file else None,
            "log_saved": save_audit_log(audit_id, image_path, status,
                str(actual_file) if actual_file else None,
                str(comparison_file) if comparison_file else None,
                extra if extra is not None else message),
        }

    def stage(label, args):
        print("\n" + "=" * 78)
        print(label)
        print("=" * 78)
        print("$ " + " ".join(str(x) for x in args))
        proc = subprocess.run(args, cwd=root)
        if proc.returncode != 0:
            raise RuntimeError(f"{label} failed with exit code {proc.returncode}")

    if not photo.exists():
        return fail("REJECTED_IMAGE_QUALITY", f"Photo not found: {photo}")
    if not expected.exists():
        return fail("ERROR", f"Expected map not found: {expected}")
    if not rules_path.exists():
        return fail("ERROR", f"Merchandising rules not found: {rules_path}")

    print("\n" + "#" * 70)
    print("# SMART PLANOGRAM — PRODUCTION AUDIT PIPELINE")
    print(f"# Audit ID: {audit_id}")
    print(f"# Image: {photo}")
    print("#" * 70)

    # 1. Photo -> actual map. Keep the existing AI/image-processing implementation.
    try:
        actual_result = process_photo(str(photo))
        if actual_result is None:
            return fail("REJECTED_IMAGE_QUALITY", build_rejection_message([
                "Image quality check failed",
                "Photo may be blurry, too dark, or too low resolution",
            ]))
    except Exception as e:
        return fail("ERROR", f"System error during image processing: {e}", extra=str(e))

    produced_actual = Path(actual_result)
    if produced_actual.exists() and produced_actual.resolve() != actual.resolve():
        actual.parent.mkdir(parents=True, exist_ok=True)
        actual.write_text(produced_actual.read_text(encoding="utf-8"), encoding="utf-8")
    if not actual.exists():
        return fail("ERROR", f"Actual map was not created: {actual}")

    # 2. Validate the AI output before any downstream decisioning.
    try:
        validation = validate_actual_map(str(actual))
    except Exception as e:
        return fail("ERROR", f"System error during sanity validation: {e}", actual, extra=str(e))
    if validation["status"] == "REJECT":
        return fail("REJECTED_AI_UNRELIABLE", get_staff_rejection_message(validation), actual, extra=validation)

    try:
        # 3. Actual map -> shelf analysis
        stage("3/9 ACTUAL MAP -> SHELF ANALYSIS", [sys.executable, "shelf_analyzer.py", str(actual)])
        # 4. Shelf analysis -> misplacements
        stage("4/9 SHELF ANALYSIS -> MISPLACEMENTS", [sys.executable, "misplacement_detector_v2.py", str(analysis), "--actual", str(actual), "--expected", str(expected), "--rules", str(rules_path), "--output", str(misplacements)])
        # 5. Misplacements -> corrections
        stage("5/9 MISPLACEMENTS -> CORRECTIONS", [sys.executable, "correction_engine_v2.py", str(misplacements), "--actual", str(actual), "--expected", str(expected), "--rules", str(rules_path)])
        # 6. Occurrence resolution
        stage("6/9 OCCURRENCE RESOLUTION", [sys.executable, "occurrence_resolver.py", str(corrections), "--actual", str(actual), "--expected", str(expected), "--rules", str(rules_path)])
        # 7. Rearrangement planning and cycle planning
        stage("7/9 REARRANGEMENT PLANNING", [sys.executable, "rearrangement_planner.py", str(corrections), "--actual", str(actual), "--expected", str(expected), "--rules", str(rules_path)])
        stage("7/9 CYCLE PLANNING", [sys.executable, "cycle_planner.py", str(corrections), "--actual", str(actual), "--expected", str(expected), "--rules", str(rules_path)])
        # 8. Dependency / physical action planning
        stage("8/9 DEPENDENCY / PHYSICAL ACTION PLANNING", [sys.executable, "dependency_planner.py", str(occurrences), "--corrections", str(corrections), "--rearrangements", str(rearrangements), "--cycles", str(cycles)])
        # 9. Final staff-facing normalization
        stage("9/9 FINAL STAFF ACTION NORMALIZATION", [sys.executable, "staff_action_normalizer.py", "--rack", "BTM-CH01", "--occurrences", str(occurrences), "--rearrangements", str(rearrangements), "--dependencies", str(dependencies), "--final-recommendations", str(final_recommendations), "--output", str(staff_actions), "--staff-output", str(staff_message)])
    except Exception as e:
        return fail("ERROR", f"System error during action-planning pipeline: {e}", actual, extra=str(e))

    # Preserve the legacy score/report contract used by the current Streamlit UI.
    # compare_maps() writes the comparison using the actual-map stem,
    # e.g. actual_map_wrongshelf.json -> comparison_wrongshelf.json.
    comparison_dir = root / "data" / "comparisons"
    comparison_file = comparison_dir / (
        f"comparison_{Path(actual).stem.replace("actual_map_", "")}.json"
    )

    try:
        compare_maps(str(actual))

        # The comparison engine may use its own output naming convention.
        # First use the deterministic expected path, then fall back to the
        # newest comparison file if the engine chose a different name.
        if not comparison_file.exists():
            candidates = sorted(
                comparison_dir.glob("comparison_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                comparison_file = candidates[0]
            else:
                raise FileNotFoundError(
                    f"Comparison file not created: {comparison_file}"
                )

        report_summary = generate_audit_report(str(comparison_file))
    except Exception as e:
        return fail("ERROR", f"System error during scoring/report generation: {e}", actual, comparison_file, str(e))

    staff_data = {}
    if staff_actions.exists():
        try:
            staff_data = json.loads(staff_actions.read_text(encoding="utf-8"))
        except Exception:
            pass
    staff_text = staff_message.read_text(encoding="utf-8") if staff_message.exists() else ""
    duration = (datetime.now() - audit_start).total_seconds()

    result = {
        "status": "SUCCESS",
        "audit_id": audit_id,
        "score": report_summary["score"],
        "score_status": report_summary["status"],
        "violation_counts": report_summary["violation_counts"],
        "top_fixes": report_summary["top_fixes"],
        "whatsapp_message": staff_text,
        "staff_actions": staff_data.get("safe_actions", []),
        "review_required": staff_data.get("review_required", []),
        "staff_action_report": staff_data,
        "staff_action_message": staff_text,
        "actual_map_file": str(actual),
        "analysis_file": str(analysis),
        "misplacements_file": str(misplacements),
        "corrections_file": str(corrections),
        "occurrences_file": str(occurrences),
        "rearrangements_file": str(rearrangements),
        "cycles_file": str(cycles),
        "dependencies_file": str(dependencies),
        "final_recommendations_file": str(final_recommendations),
        "staff_actions_file": str(staff_actions),
        "duration_seconds": duration,
        "validation_warnings": validation.get("warnings", []),
    }
    result["log_saved"] = save_audit_log(audit_id, image_path, "SUCCESS", str(actual), str(comparison_file), result)

    print("\n" + "#" * 70)
    print(f"# AUDIT COMPLETE — {duration:.1f}s")
    print(f"# Score: {result['score']}/10 — {result['score_status']}")
    print(f"# Safe actions: {len(result['staff_actions'])}")
    print(f"# Manual reviews: {len(result['review_required'])}")
    print("#" * 70)
    return result

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