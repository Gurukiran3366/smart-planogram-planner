#!/usr/bin/env python3
"""Smart Planogram end-to-end demo runner.

Runs the existing pipeline in order and writes a compact demo report.
It intentionally does not modify any existing analyzer/correction modules.
"""

from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ANALYSES = DATA / "analyses"
ACTUAL_MAPS = DATA / "actual_maps"
DEMO_RUNS = DATA / "demo_runs"

def run_step(label, args):
    print("\n" + "=" * 76)
    print(label)
    print("=" * 76)
    print("$ " + " ".join(map(str, args)))
    p = subprocess.run(args, cwd=ROOT, text=True)
    if p.returncode:
        print(f"[FAILED] {label} (exit {p.returncode})")
        return False
    print(f"[OK] {label}")
    return True

def find_actual_map(photo):
    expected = ACTUAL_MAPS / f"actual_map_{photo.stem}.json"
    if expected.exists():
        return expected
    matches = sorted(ACTUAL_MAPS.glob(f"*{photo.stem}*.json"),
                     key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(
            f"No actual_map JSON found for {photo.name} in {ACTUAL_MAPS}"
        )
    return matches[0]

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--expected", required=True)
    ap.add_argument("--rules", default="data/merchandising_rules_v2.json")
    ap.add_argument("--skip-photo", action="store_true")
    a = ap.parse_args()

    photo = Path(a.photo)
    expected = Path(a.expected)
    rules = Path(a.rules)
    if not photo.is_absolute(): photo = ROOT / photo
    if not expected.is_absolute(): expected = ROOT / expected
    if not rules.is_absolute(): rules = ROOT / rules

    if not a.skip_photo and not photo.exists():
        print(f"ERROR: photo not found: {photo}"); return 2
    if not expected.exists():
        print(f"ERROR: expected map not found: {expected}"); return 2
    if not rules.exists():
        print(f"ERROR: rules not found: {rules}"); return 2

    print("=" * 76)
    print("SMART PLANOGRAM — END-TO-END DEMO")
    print("=" * 76)
    print(f"Photo   : {photo}")
    print(f"Expected: {expected}")
    print(f"Rules   : {rules}")

    if not a.skip_photo:
        if not run_step("1/8 PHOTO → ACTUAL MAP",
                        [sys.executable, "audit_chiller.py", str(photo)]):
            return 1

    try:
        actual = find_actual_map(photo)
    except FileNotFoundError as e:
        print(f"ERROR: {e}"); return 1

    stem = actual.stem
    analysis = ANALYSES / f"analysis_{stem}.json"
    misplacements = ANALYSES / f"misplacements_v2_analysis_{stem}.json"
    corrections = ANALYSES / f"corrections_v2_{misplacements.stem}.json"
    occurrences = ANALYSES / f"occurrences_corrections_v2_{misplacements.stem}.json"
    rearrangements = ANALYSES / f"rearrangements_corrections_v2_{misplacements.stem}.json"
    cycles = ANALYSES / f"cycles_corrections_v2_{misplacements.stem}.json"
    final = ANALYSES / f"final_recommendations_corrections_v2_{misplacements.stem}.json"

    steps = [
        ("2/8 ACTUAL MAP → SHELF ANALYSIS",
         [sys.executable, "shelf_analyzer.py", str(actual)]),
        ("3/8 SHELF ANALYSIS → MISPLACEMENTS",
         [sys.executable, "misplacement_detector_v2.py", str(analysis),
          "--actual", str(actual), "--expected", str(expected), "--rules", str(rules),
          "--output", str(misplacements)]),
        ("4/8 MISPLACEMENTS → CORRECTIONS",
         [sys.executable, "correction_engine_v2.py", str(misplacements),
          "--actual", str(actual), "--expected", str(expected), "--rules", str(rules)]),
        ("5/8 → OCCURRENCE RESOLUTION",
         [sys.executable, "occurrence_resolver.py", str(corrections),
          "--actual", str(actual), "--expected", str(expected), "--rules", str(rules)]),
        ("6/8 → REARRANGEMENT PLANNER",
         [sys.executable, "rearrangement_planner.py", str(corrections),
          "--actual", str(actual), "--expected", str(expected), "--rules", str(rules)]),
        ("7/8 → CYCLE PLANNER",
         [sys.executable, "cycle_planner.py", str(corrections),
          "--actual", str(actual), "--expected", str(expected), "--rules", str(rules)]),
        ("8/8 → FINAL STAFF RECOMMENDATION",
         [sys.executable, "final_recommendation_engine.py",
          "--corrections", str(corrections), "--occurrences", str(occurrences),
          "--rearrangements", str(rearrangements), "--cycles", str(cycles)]),
    ]

    for label, cmd in steps:
        if not run_step(label, cmd):
            return 1

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "actual_map": str(actual),
        "analysis": str(analysis),
        "misplacements": str(misplacements),
        "corrections": str(corrections),
        "occurrences": str(occurrences),
        "rearrangements": str(rearrangements),
        "cycles": str(cycles),
        "final_recommendation": str(final),
    }

    for key, path in [
        ("analysis", analysis), ("misplacements", misplacements),
        ("corrections", corrections), ("occurrences", occurrences),
        ("rearrangements", rearrangements), ("cycles", cycles),
        ("final_recommendation", final)
    ]:
        if path.exists():
            d = load(path)
            report[f"{key}_data"] = d

    DEMO_RUNS.mkdir(parents=True, exist_ok=True)
    rp = DEMO_RUNS / f"demo_report_{stem}_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n" + "#" * 76)
    print("DEMO COMPLETE")
    print("#" * 76)
    print(f"Actual map : {actual}")
    print(f"Report     : {rp}")

    r = report.get("rearrangements_data", {})
    f = report.get("final_recommendation_data", {})
    print(f"Safe swaps proven: {len(r.get('safe_rearrangements', []))}")
    print(f"Final safe actions: {len(f.get('safe_actions', []))}")
    print(f"Final reviews: {len(f.get('review_required', []))}")
    print("#" * 76)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
