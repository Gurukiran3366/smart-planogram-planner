#!/usr/bin/env python3
"""
SMART PLANOGRAM — REAL CASE TEST HARNESS

Runs the existing pipeline without modifying:
    1. process_staff_photo.py / photo-recognition stage (optional)
    2. shelf_analyzer.py
    3. correction_engine.py

The harness is deliberately separate from the production analyzers.

Typical project structure:
    smart-planogram-planner/
      test_real_cases.py
      shelf_analyzer.py
      correction_engine.py
      process_staff_photo.py
      data/
        actual_maps/
        analyses/
        test_cases/

Example:
    python test_real_cases.py

Or, after creating test cases:
    python test_real_cases.py --case TEST-001
    python test_real_cases.py --case TEST-001 --skip-photo
    python test_real_cases.py --all

A test case JSON can define the expected behavior:
{
  "case_id": "TEST-001",
  "name": "Shelf missing product",
  "photo": "images/staff_uploads/shelfmessing.jpeg",
  "actual_map": "data/actual_maps/actual_map_shelfmessing.json",
  "expected": {
    "decision": "ACTION_RECOMMENDED",
    "must_contain": ["THUMSUP_250"],
    "must_not_contain": ["REVIEW_NO_SAFE_ACTION"]
  }
}

IMPORTANT:
- This script does not decide whether the merchandising answer is correct.
- It compares observed engine output with human-defined expected behavior.
- "REVIEW" is a valid expected result.
- A false physical correction is treated as a serious failure.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent

ANALYZER = PROJECT_ROOT / "shelf_analyzer.py"
CORRECTION_ENGINE = PROJECT_ROOT / "correction_engine.py"

DEFAULT_CASE_DIR = PROJECT_ROOT / "data" / "test_cases"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "test_runs"

# These are the first real cases discussed for the chiller project.
DEFAULT_CASES = [
    {
        "case_id": "TEST-001",
        "name": "Shelf messing baseline",
        "photo": "images/staff_uploads/shelfmessing.jpeg",
        "actual_map": "data/actual_maps/actual_map_shelfmessing.json",
        "expected": {
            "decision": "ACTION_RECOMMENDED",
            "note": "At least one safe correction should be found; current known case includes Shelf 3 and/or Shelf 5.",
            "must_not_contain": [
                "unsafe",
                "invented_capacity",
            ],
        },
    },
]


@dataclass
class CaseResult:
    case_id: str
    name: str
    status: str
    reason: str
    analyzer_returncode: Optional[int] = None
    correction_returncode: Optional[int] = None
    analysis_path: Optional[str] = None
    correction_path: Optional[str] = None
    observed_decision: Optional[str] = None
    expected_decision: Optional[str] = None
    output_text: str = ""
    failures: List[str] = field(default_factory=list)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_path(value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def run_command(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )


def extract_decision(correction_json: Dict[str, Any]) -> Optional[str]:
    primary = correction_json.get("primary_recommendation") or {}
    if isinstance(primary, dict):
        decision = primary.get("decision")
        if decision:
            return str(decision)

    summary = correction_json.get("summary") or {}
    if isinstance(summary, dict):
        decision = summary.get("decision")
        if decision:
            return str(decision)

    return None


def flatten_json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).lower()


def check_expectations(
    correction_json: Dict[str, Any],
    expected: Dict[str, Any],
) -> List[str]:
    failures: List[str] = []
    text = flatten_json_text(correction_json)

    observed = extract_decision(correction_json)
    expected_decision = expected.get("decision")

    if expected_decision and observed != expected_decision:
        failures.append(
            f"Expected decision {expected_decision!r}, "
            f"but observed {observed!r}."
        )

    for item in expected.get("must_contain", []):
        if str(item).lower() not in text:
            failures.append(
                f"Required value not found in correction output: {item!r}"
            )

    for item in expected.get("must_not_contain", []):
        if str(item).lower() in text:
            failures.append(
                f"Forbidden value found in correction output: {item!r}"
            )

    # Optional strict checks for physical safety.
    safety = expected.get("safety", {})
    if isinstance(safety, dict):
        if safety.get("no_capacity_invention"):
            for candidate in correction_json.get("candidates", []):
                action = candidate.get("action") or {}
                if action.get("type") in {
                    "insert_missing_product_and_shift",
                    "place_missing_product",
                }:
                    checks = candidate.get("checks") or []
                    capacity_ok = any(
                        c.get("check") == "physical_capacity"
                        and c.get("status") == "capacity_proven"
                        for c in checks
                        if isinstance(c, dict)
                    )
                    if not capacity_ok:
                        failures.append(
                            "Physical insertion was recommended without "
                            "a proven capacity check."
                        )

        if safety.get("oos_untouched"):
            oos_ids = {
                str(x).lower()
                for x in expected.get("oos_product_ids", [])
            }
            if oos_ids:
                for candidate in correction_json.get("candidates", []):
                    action = candidate.get("action") or {}
                    action_text = json.dumps(
                        action,
                        ensure_ascii=False,
                    ).lower()
                    for oid in oos_ids:
                        if oid in action_text:
                            failures.append(
                                f"OOS product {oid!r} appears in an "
                                "action recommendation."
                            )

    return failures


def run_case(
    case: Dict[str, Any],
    skip_photo: bool,
) -> CaseResult:
    case_id = case["case_id"]
    name = case.get("name", case_id)
    expected = case.get("expected", {})

    actual_map = resolve_path(case["actual_map"])
    if not actual_map.exists():
        return CaseResult(
            case_id=case_id,
            name=name,
            status="BLOCKED",
            reason=f"Actual map not found: {actual_map}",
        )

    if not ANALYZER.exists():
        return CaseResult(
            case_id=case_id,
            name=name,
            status="BLOCKED",
            reason=f"shelf_analyzer.py not found: {ANALYZER}",
        )

    if not CORRECTION_ENGINE.exists():
        return CaseResult(
            case_id=case_id,
            name=name,
            status="BLOCKED",
            reason=f"correction_engine.py not found: {CORRECTION_ENGINE}",
        )

    # Photo processing is intentionally optional. The first test cycle
    # can use an already-created actual_map.json so that recognition errors
    # do not get confused with analyzer/correction-engine errors.
    photo = resolve_path(case["photo"]) if case.get("photo") else None
    if not skip_photo and photo and not photo.exists():
        return CaseResult(
            case_id=case_id,
            name=name,
            status="BLOCKED",
            reason=f"Photo not found: {photo}",
        )

    out_dir = DEFAULT_OUTPUT_DIR / case_id
    out_dir.mkdir(parents=True, exist_ok=True)

    analysis_path = out_dir / "analysis.json"
    correction_path = out_dir / "corrections.json"

    analyzer_cmd = [
        sys.executable,
        str(ANALYZER),
        str(actual_map),
        "--output",
        str(analysis_path),
    ]

    analyzer = run_command(analyzer_cmd)

    if analyzer.returncode != 0:
        return CaseResult(
            case_id=case_id,
            name=name,
            status="FAIL",
            reason="shelf_analyzer.py failed",
            analyzer_returncode=analyzer.returncode,
            analysis_path=str(analysis_path),
            output_text=analyzer.stdout + "\n" + analyzer.stderr,
        )

    if not analysis_path.exists():
        return CaseResult(
            case_id=case_id,
            name=name,
            status="FAIL",
            reason="Analyzer completed but analysis JSON was not created",
            analyzer_returncode=analyzer.returncode,
            analysis_path=str(analysis_path),
            output_text=analyzer.stdout + "\n" + analyzer.stderr,
        )

    correction_cmd = [
        sys.executable,
        str(CORRECTION_ENGINE),
        str(analysis_path),
        "--output",
        str(correction_path),
    ]

    # Pass through optional project files if the test case specifies them.
    if case.get("rules"):
        correction_cmd.extend(["--rules", str(resolve_path(case["rules"]))])

    if case.get("products"):
        correction_cmd.extend(["--products", str(resolve_path(case["products"]))])

    if case.get("oos"):
        correction_cmd.extend(["--oos", *[str(x) for x in case["oos"]]])

    correction = run_command(correction_cmd)

    combined_output = (
        analyzer.stdout
        + "\n"
        + analyzer.stderr
        + "\n"
        + correction.stdout
        + "\n"
        + correction.stderr
    )

    if correction.returncode != 0:
        return CaseResult(
            case_id=case_id,
            name=name,
            status="FAIL",
            reason="correction_engine.py failed",
            analyzer_returncode=analyzer.returncode,
            correction_returncode=correction.returncode,
            analysis_path=str(analysis_path),
            correction_path=str(correction_path),
            output_text=combined_output,
        )

    if not correction_path.exists():
        return CaseResult(
            case_id=case_id,
            name=name,
            status="FAIL",
            reason="Correction engine completed but output JSON was not created",
            analyzer_returncode=analyzer.returncode,
            correction_returncode=correction.returncode,
            analysis_path=str(analysis_path),
            correction_path=str(correction_path),
            output_text=combined_output,
        )

    correction_json = load_json(correction_path)
    observed = extract_decision(correction_json)
    failures = check_expectations(correction_json, expected)

    if failures:
        status = "FAIL"
        reason = "Expectation mismatch"
    else:
        status = "PASS"
        reason = "Observed behavior matches the test case expectations"

    return CaseResult(
        case_id=case_id,
        name=name,
        status=status,
        reason=reason,
        analyzer_returncode=analyzer.returncode,
        correction_returncode=correction.returncode,
        analysis_path=str(analysis_path),
        correction_path=str(correction_path),
        observed_decision=observed,
        expected_decision=expected.get("decision"),
        output_text=combined_output,
        failures=failures,
    )


def load_cases(case_dir: Path) -> List[Dict[str, Any]]:
    case_files = sorted(case_dir.glob("TEST-*.json"))

    if not case_files:
        return DEFAULT_CASES

    cases = []
    for path in case_files:
        data = load_json(path)
        if "case_id" not in data:
            data["case_id"] = path.stem
        cases.append(data)

    return cases


def print_case(result: CaseResult) -> None:
    print("-" * 76)
    print(f"{result.case_id}: {result.name}")
    print(f"STATUS    : {result.status}")
    print(f"REASON    : {result.reason}")

    if result.expected_decision is not None:
        print(f"EXPECTED  : {result.expected_decision}")

    if result.observed_decision is not None:
        print(f"OBSERVED  : {result.observed_decision}")

    if result.failures:
        for failure in result.failures:
            print(f"FAILURE   : {failure}")

    if result.analysis_path:
        print(f"ANALYSIS  : {result.analysis_path}")

    if result.correction_path:
        print(f"CORRECTION: {result.correction_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run real merchandising cases through the frozen pipeline."
    )
    parser.add_argument(
        "--case",
        help="Run one case ID, e.g. TEST-001",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all test cases",
    )
    parser.add_argument(
        "--case-dir",
        default=str(DEFAULT_CASE_DIR),
        help="Directory containing TEST-*.json definitions",
    )
    parser.add_argument(
        "--skip-photo",
        action="store_true",
        help=(
            "Use the existing actual_map.json and do not require "
            "the original photo."
        ),
    )

    args = parser.parse_args()

    case_dir = resolve_path(args.case_dir)
    cases = load_cases(case_dir)

    if args.case and not args.all:
        cases = [
            c for c in cases
            if c.get("case_id") == args.case
        ]
        if not cases:
            print(f"Case not found: {args.case}")
            return 2

    print("=" * 76)
    print("SMART PLANOGRAM — REAL CASE TEST HARNESS")
    print("=" * 76)
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Cases        : {len(cases)}")
    print(f"Photo stage  : {'SKIPPED' if args.skip_photo else 'NOT RUN'}")
    print()
    print(
        "NOTE: The harness currently uses existing actual_map.json files. "
        "This isolates analyzer + correction-engine behavior."
    )

    results: List[CaseResult] = []

    for case in cases:
        result = run_case(case, skip_photo=args.skip_photo)
        results.append(result)
        print_case(result)

    passed = sum(r.status == "PASS" for r in results)
    failed = sum(r.status == "FAIL" for r in results)
    blocked = sum(r.status == "BLOCKED" for r in results)

    report = {
        "harness_version": "1.0",
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "pass_rate": round(
                passed / len(results), 4
            ) if results else 0.0,
        },
        "results": [
            {
                "case_id": r.case_id,
                "name": r.name,
                "status": r.status,
                "reason": r.reason,
                "expected_decision": r.expected_decision,
                "observed_decision": r.observed_decision,
                "analysis_path": r.analysis_path,
                "correction_path": r.correction_path,
                "failures": r.failures,
            }
            for r in results
        ],
    }

    report_path = DEFAULT_OUTPUT_DIR / "real_case_test_report.json"
    write_json(report_path, report)

    print()
    print("=" * 76)
    print("TEST SUMMARY")
    print("=" * 76)
    print(f"PASS     : {passed}")
    print(f"FAIL     : {failed}")
    print(f"BLOCKED  : {blocked}")
    print(
        f"PASS RATE: {passed / len(results) * 100:.1f}%"
        if results
        else "PASS RATE: 0.0%"
    )
    print(f"REPORT   : {report_path}")
    print("=" * 76)

    # CI-friendly exit code.
    return 0 if failed == 0 and blocked == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
