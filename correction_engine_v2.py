#!/usr/bin/env python3
"""
SMART PLANOGRAM — CORRECTION ENGINE v2

Consumes:
  - misplacement_detector_v2 analysis JSON
  - actual_map JSON
  - expected_map JSON
  - merchandising_rules_v2 JSON

Important safety model:
  Detection and correction are separate.
  A product that is "misplaced" may already have another correct
  occurrence at its expected location. In that case the correction is
  removal of the extra occurrence, not a move.

Supported correction types:
  1. REMOVE_EXTRA_OCCURRENCE
  2. MOVE_TO_EXPECTED_SLOT
  3. REARRANGEMENT_REQUIRED
  4. REVIEW_NO_SAFE_ACTION

Example:
  python correction_engine_v2.py ^
    data\analyses\misplacements_v2_analysis_actual_map_wrongshelf.json ^
    --actual data\actual_maps\actual_map_wrongshelf.json ^
    --expected data\expected_map_BTM_CH01.json ^
    --rules data\merchandising_rules_v2.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION = "2.2"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def product_id(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_id")
        or item.get("id")
        or item.get("sku")
        or ""
    )


def product_name(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_name")
        or item.get("name")
        or item.get("product")
        or product_id(item)
    )


def shelf_number(item: Dict[str, Any]) -> Any:
    return (
        item.get("shelf_number")
        or item.get("shelf")
        or item.get("number")
        or item.get("shelf_id")
    )


def slot_start(item: Dict[str, Any]) -> Optional[int]:
    for key in (
        "slot_start",
        "slot",
        "position",
        "actual_slot",
        "expected_slot",
        "index",
    ):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def slot_end(item: Dict[str, Any]) -> Optional[int]:
    for key in ("slot_end", "slot"):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

    return slot_start(item)


def slots(item: Dict[str, Any]) -> List[int]:
    start = slot_start(item)
    end = slot_end(item)

    if start is None:
        return []

    if end is None or end < start:
        end = start

    return list(range(start, end + 1))


def shelf_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = data.get("shelves")
    return value if isinstance(value, list) else []


def products_in_shelf(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = shelf.get("products")
    return value if isinstance(value, list) else []


def product_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    for shelf in shelf_list(data):
        shelf_no = shelf_number(shelf)

        for item in products_in_shelf(shelf):
            if not isinstance(item, dict):
                continue

            pid = product_id(item)
            if not pid:
                continue

            result.append(
                {
                    "product_id": pid,
                    "product_name": product_name(item),
                    "shelf": (
                        item.get("shelf_number")
                        or item.get("shelf")
                        or shelf_no
                    ),
                    "slot_start": slot_start(item),
                    "slot_end": slot_end(item),
                    "slots": slots(item),
                    "facings": item.get("facings"),
                    "zone": item.get("zone"),
                    "raw": item,
                }
            )

    return result


def shelf_records(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}

    for shelf in shelf_list(data):
        number = shelf_number(shelf)
        if number is not None:
            result[str(number)] = shelf

    return result


def find_expected_record(
    expected_records: List[Dict[str, Any]],
    pid: str,
) -> Optional[Dict[str, Any]]:
    for record in expected_records:
        if norm(record["product_id"]) == norm(pid):
            return record
    return None


def actual_occurrences(
    actual_records: List[Dict[str, Any]],
    pid: str,
) -> List[Dict[str, Any]]:
    return [
        record
        for record in actual_records
        if norm(record["product_id"]) == norm(pid)
    ]


def occupant_at_slots(
    actual_records: List[Dict[str, Any]],
    shelf_no: Any,
    target_slots: List[int],
    exclude_pid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    target = set(target_slots)
    occupants = []

    for record in actual_records:
        if str(record["shelf"]) != str(shelf_no):
            continue

        if exclude_pid and norm(record["product_id"]) == norm(exclude_pid):
            continue

        if target.intersection(record["slots"]):
            occupants.append(record)

    return occupants


def target_slot_matches_expected(
    expected_record: Dict[str, Any],
    target_shelf: Any,
    target_slots: List[int],
) -> bool:
    return (
        str(expected_record["shelf"]) == str(target_shelf)
        and set(expected_record["slots"]) == set(target_slots)
    )


def classify_misplacement(
    misplacement: Dict[str, Any],
    actual_records: List[Dict[str, Any]],
    expected_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pid = str(misplacement.get("product_id") or "")
    name = str(misplacement.get("product_name") or pid)

    occurrences = actual_occurrences(actual_records, pid)
    expected = find_expected_record(expected_records, pid)

    if expected is None:
        return {
            "type": "REVIEW_NO_SAFE_ACTION",
            "status": "BLOCKED",
            "product_id": pid,
            "product_name": name,
            "blocked_reasons": [
                "Product has no matching expected-map record."
            ],
        }

    expected_shelf = expected["shelf"]
    expected_slots = expected["slots"]

    # Identify whether the product already exists at its correct
    # expected shelf and slot.
    correct_occurrences = [
        occurrence
        for occurrence in occurrences
        if target_slot_matches_expected(
            expected,
            occurrence["shelf"],
            occurrence["slots"],
        )
    ]

    # If there is a correct occurrence and another occurrence elsewhere,
    # the safe correction is removal of the extra occurrence.
    extra_occurrences = [
        occurrence
        for occurrence in occurrences
        if occurrence not in correct_occurrences
    ]

    if correct_occurrences and extra_occurrences:
        extra = extra_occurrences[0]

        return {
            "type": "REMOVE_EXTRA_OCCURRENCE",
            "status": "FEASIBLE",
            "product_id": pid,
            "product_name": name,
            "current_shelf": extra["shelf"],
            "current_slot_start": extra["slot_start"],
            "current_slot_end": extra["slot_end"],
            "correct_shelf": expected_shelf,
            "correct_slot_start": expected["slot_start"],
            "correct_slot_end": expected["slot_end"],
            "action": (
                f"Remove extra {name} from Shelf {extra['shelf']} "
                f"slot(s) {extra['slot_start']}-{extra['slot_end']}. "
                f"Keep the correct occurrence on Shelf {expected_shelf} "
                f"slot(s) {expected['slot_start']}-{expected['slot_end']}."
            ),
            "evidence": [
                "Product already exists at its expected shelf and slot.",
                "A second occurrence exists outside the expected location.",
            ],
        }

    # If no correct occurrence exists, determine whether moving the
    # misplaced occurrence to the expected slot is safe.
    if not occurrences:
        return {
            "type": "REVIEW_NO_SAFE_ACTION",
            "status": "BLOCKED",
            "product_id": pid,
            "product_name": name,
            "blocked_reasons": [
                "Detector reported a misplaced product, but no actual "
                "occurrence was found in the actual map."
            ],
        }

    current = occurrences[0]

    occupants = occupant_at_slots(
        actual_records,
        expected_shelf,
        expected_slots,
        exclude_pid=pid,
    )

    if occupants:
        occupant_text = ", ".join(
            f"{x['product_name']} ({x['product_id']})"
            for x in occupants
        )

        return {
            "type": "REARRANGEMENT_REQUIRED",
            "status": "BLOCKED",
            "product_id": pid,
            "product_name": name,
            "current_shelf": current["shelf"],
            "current_slot_start": current["slot_start"],
            "current_slot_end": current["slot_end"],
            "target_shelf": expected_shelf,
            "target_slot_start": expected["slot_start"],
            "target_slot_end": expected["slot_end"],
            "blocked_reasons": [
                f"Expected destination slot is occupied by: {occupant_text}.",
                "A swap/rearrangement plan is required; the engine will "
                "not invent one.",
            ],
        }

    return {
        "type": "MOVE_TO_EXPECTED_SLOT",
        "status": "FEASIBLE",
        "product_id": pid,
        "product_name": name,
        "current_shelf": current["shelf"],
        "current_slot_start": current["slot_start"],
        "current_slot_end": current["slot_end"],
        "target_shelf": expected_shelf,
        "target_slot_start": expected["slot_start"],
        "target_slot_end": expected["slot_end"],
        "action": (
            f"Move {name} from Shelf {current['shelf']} "
            f"slot(s) {current['slot_start']}-{current['slot_end']} "
            f"to Shelf {expected_shelf} "
            f"slot(s) {expected['slot_start']}-{expected['slot_end']}."
        ),
        "evidence": [
            "Product has a verified expected shelf and slot.",
            "Expected destination slot is not occupied by another "
            "currently detected product.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate safe physical corrections for detected misplacements."
    )

    parser.add_argument(
        "misplacements",
        help="misplacement_detector_v2 analysis JSON",
    )
    parser.add_argument(
        "--actual",
        required=True,
        help="actual_map JSON",
    )
    parser.add_argument(
        "--expected",
        required=True,
        help="expected_map JSON",
    )
    parser.add_argument(
        "--rules",
        required=True,
        help="merchandising_rules_v2.json",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path",
    )

    args = parser.parse_args()

    paths = {
        "misplacements": Path(args.misplacements),
        "actual": Path(args.actual),
        "expected": Path(args.expected),
        "rules": Path(args.rules),
    }

    for label, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    misplacement_data = load_json(paths["misplacements"])
    actual = load_json(paths["actual"])
    expected = load_json(paths["expected"])
    rules = load_json(paths["rules"])

    # Rules are loaded deliberately so the interface remains compatible
    # with the merchandising-rule layer. v2 correction decisions are
    # currently based on explicit actual/expected slot evidence.
    _ = rules

    actual_records = product_records(actual)
    expected_records = product_records(expected)

    detected = misplacement_data.get("misplaced_products", [])
    if not isinstance(detected, list):
        detected = []

    candidates: List[Dict[str, Any]] = []

    for item in detected:
        if not isinstance(item, dict):
            continue

        if item.get("status") not in (None, "MISPLACED"):
            continue

        candidates.append(
            classify_misplacement(
                item,
                actual_records,
                expected_records,
            )
        )

    feasible = [
        candidate
        for candidate in candidates
        if candidate["status"] == "FEASIBLE"
    ]

    blocked = [
        candidate
        for candidate in candidates
        if candidate["status"] == "BLOCKED"
    ]

    if feasible:
        decision = "ACTION_RECOMMENDED"
        recommendation = "SAFE PHYSICAL CORRECTION"
    else:
        decision = "REVIEW_NO_SAFE_ACTION"
        recommendation = "REVIEW / NO SAFE ACTION"

    rack = (
        actual.get("rack_id")
        or actual.get("rack")
        or misplacement_data.get("rack")
        or "UNKNOWN"
    )

    type_counts: Dict[str, int] = {}
    for candidate in candidates:
        kind = candidate["type"]
        type_counts[kind] = type_counts.get(kind, 0) + 1

    output = {
        "engine": "correction_engine_v2",
        "engine_version": VERSION,
        "rack": rack,
        "sources": {
            "misplacements": str(paths["misplacements"]),
            "actual": str(paths["actual"]),
            "expected": str(paths["expected"]),
            "rules": str(paths["rules"]),
        },
        "summary": {
            "misplacements_received": len(detected),
            "candidates_generated": len(candidates),
            "feasible_candidates": len(feasible),
            "blocked_candidates": len(blocked),
            "correction_types": type_counts,
        },
        "decision": decision,
        "recommendation": recommendation,
        "feasible_corrections": feasible,
        "blocked_corrections": blocked,
        "safety_boundary": (
            "A product already present at its expected shelf/slot is "
            "treated as a correct occurrence; an additional occurrence "
            "elsewhere is classified as REMOVE_EXTRA_OCCURRENCE. "
            "Moves are allowed only when the verified expected slot is "
            "not occupied by another product. Occupied target slots are "
            "REARRANGEMENT_REQUIRED rather than automatically overwritten."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            paths["misplacements"].parent
            / f"corrections_v2_{paths['misplacements'].stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — CORRECTION ENGINE v2")
    print("=" * 72)
    print(f"Rack: {rack}")
    print()
    print(f"Candidates generated : {len(candidates)}")
    print(f"Feasible candidates  : {len(feasible)}")
    print(f"Blocked candidates   : {len(blocked)}")
    print(f"Decision              : {decision}")
    print("-" * 72)
    print(f"RECOMMENDATION: {recommendation}")

    if feasible:
        print()
        print("ACTIONABLE CORRECTIONS")
        for candidate in feasible:
            print(f"  {candidate['action']}")

    if blocked:
        print()
        print("BLOCKED / REVIEW CORRECTIONS")
        for candidate in blocked:
            print()
            print(
                f"{candidate['type']}: "
                f"{candidate.get('product_name', candidate.get('product_id'))}"
            )

            if "current_shelf" in candidate:
                print(
                    f"  Current : Shelf {candidate['current_shelf']} "
                    f"slots {candidate.get('current_slot_start')}-"
                    f"{candidate.get('current_slot_end')}"
                )

            if "target_shelf" in candidate:
                print(
                    f"  Target  : Shelf {candidate['target_shelf']} "
                    f"slots {candidate.get('target_slot_start')}-"
                    f"{candidate.get('target_slot_end')}"
                )

            for reason in candidate.get("blocked_reasons", []):
                print(f"  - {reason}")

    print()
    print(f"Correction analysis written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
