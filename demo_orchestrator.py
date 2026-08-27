#!/usr/bin/env python3
"""
SMART PLANOGRAM — END-TO-END DEMO ORCHESTRATOR v2

Runs the existing 8-stage pipeline, then normalizes all proven physical
actions into one staff-facing action contract.

This file intentionally does not modify the individual analysis engines.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def run_stage(label, args):
    print("\n" + "=" * 78)
    print(label)
    print("=" * 78)
    print("$ " + " ".join(str(x) for x in args))
    proc = subprocess.run(args, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {proc.returncode}")
    print(f"[OK] {label}")
    return proc.returncode


def p(*parts):
    return str(ROOT.joinpath(*parts))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("photo")
    parser.add_argument("--expected", required=True)
    parser.add_argument("--rules", default=p("data", "merchandising_rules_v2.json"))
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    photo = str(Path(args.photo).resolve())
    expected = str(Path(args.expected).resolve())
    rules = str(Path(args.rules).resolve())

    if args.api_key:
        os.environ["GOOGLE_API_KEY"] = args.api_key

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(photo).stem
    actual = p("data", "actual_maps", f"actual_map_{stem}.json")
    analysis = p("data", "analyses", f"analysis_actual_map_{stem}.json")
    misplacements = p("data", "analyses", f"misplacements_v2_analysis_actual_map_{stem}.json")
    corrections = p("data", "analyses", f"corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    occurrences = p("data", "analyses", f"occurrences_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    rearrangements = p("data", "analyses", f"rearrangements_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    cycles = p("data", "analyses", f"cycles_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    dependencies = p("data", "analyses", f"dependencies_occurrences_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    final_recommendations = p("data", "analyses", f"final_recommendations_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    action_report = p("data", "analyses", f"staff_actions_{stem}.json")
    staff_message = p("data", "reports", f"staff_actions_{stem}.txt")

    run_stage(
        "1/9 PHOTO → ACTUAL MAP",
        [PYTHON, "audit_chiller.py", photo],
    )

    # audit_chiller writes its conventional actual-map filename. Copy/alias only if needed.
    conventional_actual = p("data", "actual_maps", "actual_map_wrongshelf.json")
    if Path(conventional_actual).exists() and not Path(actual).exists():
        Path(actual).write_text(Path(conventional_actual).read_text(encoding="utf-8"), encoding="utf-8")

    run_stage(
        "2/9 ACTUAL MAP → SHELF ANALYSIS",
        [PYTHON, "shelf_analyzer.py", conventional_actual],
    )

    conventional_analysis = p("data", "analyses", "analysis_actual_map_wrongshelf.json")
    run_stage(
        "3/9 SHELF ANALYSIS → MISPLACEMENTS",
        [
            PYTHON, "misplacement_detector_v2.py", conventional_analysis,
            "--actual", conventional_actual,
            "--expected", expected,
            "--rules", rules,
            "--output", p("data", "analyses", f"misplacements_v2_analysis_actual_map_{stem}.json"),
        ],
    )

    conventional_misplacements = p("data", "analyses", f"misplacements_v2_analysis_actual_map_{stem}.json")
    run_stage(
        "4/9 MISPLACEMENTS → CORRECTIONS",
        [
            PYTHON, "correction_engine_v2.py", conventional_misplacements,
            "--actual", conventional_actual,
            "--expected", expected,
            "--rules", rules,
        ],
    )

    conventional_corrections = p("data", "analyses", f"corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    run_stage(
        "5/9 → OCCURRENCE RESOLUTION",
        [
            PYTHON, "occurrence_resolver.py", conventional_corrections,
            "--actual", conventional_actual,
            "--expected", expected,
            "--rules", rules,
        ],
    )

    conventional_occurrences = p("data", "analyses", f"occurrences_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    run_stage(
        "6/9 → REARRANGEMENT PLANNER",
        [
            PYTHON, "rearrangement_planner.py", conventional_corrections,
            "--actual", conventional_actual,
            "--expected", expected,
            "--rules", rules,
        ],
    )

    conventional_rearrangements = p("data", "analyses", f"rearrangements_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    run_stage(
        "7/9 → CYCLE PLANNER",
        [
            PYTHON, "cycle_planner.py", conventional_corrections,
            "--actual", conventional_actual,
            "--expected", expected,
            "--rules", rules,
        ],
    )

    conventional_cycles = p("data", "analyses", f"cycles_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")

    # Dependency planner is optional for backward compatibility.
    if Path("dependency_planner.py").exists():
        run_stage(
            "8/9 → DEPENDENCY / PHYSICAL ACTION PLANNER",
            [
                PYTHON, "dependency_planner.py", conventional_occurrences,
                "--corrections", conventional_corrections,
                "--rearrangements", conventional_rearrangements,
                "--cycles", conventional_cycles,
            ],
        )
        conventional_dependencies = p("data", "analyses", f"dependencies_occurrences_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json")
    else:
        conventional_dependencies = ""

    run_stage(
        "9/9 → FINAL STAFF ACTIONS",
        [
            PYTHON, "staff_action_normalizer.py",
            "--rack", "BTM-CH01",
            "--occurrences", conventional_occurrences,
            "--rearrangements", conventional_rearrangements,
            "--dependencies", conventional_dependencies,
            "--final-recommendations", p("data", "analyses", f"final_recommendations_corrections_v2_misplacements_v2_analysis_actual_map_{stem}.json"),
            "--output", action_report,
            "--staff-output", staff_message,
        ],
    )

    print("\n" + "#" * 78)
    print("DEMO COMPLETE")
    print("#" * 78)
    print(f"Actual map       : {conventional_actual}")
    print(f"Staff action JSON: {action_report}")
    print(f"Staff message    : {staff_message}")
    print("#" * 78)


if __name__ == "__main__":
    main()
