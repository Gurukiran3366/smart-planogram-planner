#!/usr/bin/env python3
"""
SMART PLANOGRAM — OCCURRENCE RESOLVER

Purpose:
    Reconcile product occurrences between the expected and actual maps
    before correction/rearrangement planning.

For each detected/misplaced product, classify actual occurrences as:
    - CORRECT_OCCURRENCE
    - EXTRA_OCCURRENCE
    - MISPLACED_OCCURRENCE
    - MISSING_EXPECTED_OCCURRENCE
    - AMBIGUOUS

This is a reconciliation layer, not a correction engine.

Safety:
    - Does not move, remove, swap, or authorize any product.
    - Does not assume that the first occurrence is correct.
    - Uses exact shelf + slot evidence.
    - Duplicate actual occurrences are explicitly surfaced.
    - Duplicate expected occurrences are explicitly surfaced.
    - A product is only classified as having a correct occurrence when
      an actual occurrence exactly matches its expected shelf and slots.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


VERSION = "1.0"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def pid(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_id")
        or item.get("id")
        or item.get("sku")
        or ""
    )


def pname(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_name")
        or item.get("name")
        or item.get("product")
        or pid(item)
    )


def shelf(item: Dict[str, Any]) -> Any:
    return (
        item.get("shelf_number")
        or item.get("shelf")
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


def product_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for shelf_obj in data.get("shelves", []):
        shelf_no = shelf(shelf_obj)

        for item in shelf_obj.get("products", []):
            if not isinstance(item, dict):
                continue

            product = pid(item)
            if not product:
                continue

            records.append(
                {
                    "product_id": product,
                    "product_name": pname(item),
                    "shelf": shelf(item) or shelf_no,
                    "slot_start": slot_start(item),
                    "slot_end": slot_end(item),
                    "slots": slots(item),
                    "facings": item.get("facings"),
                    "raw": item,
                }
            )

    return records


def index_records(
    records: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}

    for record in records:
        result.setdefault(norm(record["product_id"]), []).append(record)

    return result


def location_matches(
    actual: Dict[str, Any],
    expected: Dict[str, Any],
) -> bool:
    actual_slots = set(actual.get("slots", []))
    expected_slots = set(expected.get("slots", []))

    if not actual_slots or not expected_slots:
        return False

    return (
        str(actual.get("shelf")) == str(expected.get("shelf"))
        and actual_slots == expected_slots
    )


def compact_location(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "shelf": record.get("shelf"),
        "slot_start": record.get("slot_start"),
        "slot_end": record.get("slot_end"),
        "slots": record.get("slots", []),
        "facings": record.get("facings"),
    }


def resolve_product(
    product_id: str,
    actual_occurrences: List[Dict[str, Any]],
    expected_occurrences: List[Dict[str, Any]],
) -> Dict[str, Any]:
    name = (
        actual_occurrences[0]["product_name"]
        if actual_occurrences
        else expected_occurrences[0]["product_name"]
        if expected_occurrences
        else product_id
    )

    if len(expected_occurrences) == 0:
        return {
            "product_id": product_id,
            "product_name": name,
            "status": "AMBIGUOUS",
            "reason": "No expected-map occurrence exists for this product.",
            "expected_occurrences": [],
            "actual_occurrences": [
                compact_location(x) for x in actual_occurrences
            ],
        }

    if len(expected_occurrences) > 1:
        return {
            "product_id": product_id,
            "product_name": name,
            "status": "AMBIGUOUS",
            "reason": (
                "Multiple expected-map occurrences exist for this product; "
                "the correct expected location cannot be uniquely resolved."
            ),
            "expected_occurrences": [
                compact_location(x) for x in expected_occurrences
            ],
            "actual_occurrences": [
                compact_location(x) for x in actual_occurrences
            ],
        }

    expected = expected_occurrences[0]

    if len(actual_occurrences) == 0:
        return {
            "product_id": product_id,
            "product_name": name,
            "status": "MISSING_EXPECTED_OCCURRENCE",
            "reason": "Expected occurrence is not present in the actual map.",
            "expected_occurrence": compact_location(expected),
            "actual_occurrences": [],
        }

    if not expected.get("slots"):
        return {
            "product_id": product_id,
            "product_name": name,
            "status": "AMBIGUOUS",
            "reason": "Expected occurrence has no explicit slot information.",
            "expected_occurrence": compact_location(expected),
            "actual_occurrences": [
                compact_location(x) for x in actual_occurrences
            ],
        }

    matching = [
        occurrence
        for occurrence in actual_occurrences
        if location_matches(occurrence, expected)
    ]

    non_matching = [
        occurrence
        for occurrence in actual_occurrences
        if occurrence not in matching
    ]

    if len(matching) == 1:
        result = {
            "product_id": product_id,
            "product_name": name,
            "status": "CORRECT_OCCURRENCE",
            "reason": (
                "Exactly one actual occurrence matches the expected "
                "shelf and slot."
            ),
            "expected_occurrence": compact_location(expected),
            "correct_occurrence": compact_location(matching[0]),
            "extra_occurrences": [
                compact_location(x) for x in non_matching
            ],
        }

        if non_matching:
            result["secondary_status"] = "EXTRA_OCCURRENCE_PRESENT"

        return result

    if len(matching) > 1:
        return {
            "product_id": product_id,
            "product_name": name,
            "status": "AMBIGUOUS",
            "reason": (
                "Multiple actual occurrences match the same expected "
                "location."
            ),
            "expected_occurrence": compact_location(expected),
            "matching_occurrences": [
                compact_location(x) for x in matching
            ],
            "other_occurrences": [
                compact_location(x) for x in non_matching
            ],
        }

    # No actual occurrence matches expected.
    if len(actual_occurrences) == 1:
        return {
            "product_id": product_id,
            "product_name": name,
            "status": "MISPLACED_OCCURRENCE",
            "reason": (
                "Exactly one actual occurrence exists, but it is not "
                "at the expected shelf and slot."
            ),
            "expected_occurrence": compact_location(expected),
            "misplaced_occurrence": compact_location(actual_occurrences[0]),
        }

    return {
        "product_id": product_id,
        "product_name": name,
        "status": "AMBIGUOUS",
        "reason": (
            "Multiple actual occurrences exist and none matches the "
            "expected shelf and slot."
        ),
        "expected_occurrence": compact_location(expected),
        "misplaced_occurrences": [
            compact_location(x) for x in actual_occurrences
        ],
    }


def candidate_product_ids(
    corrections: Dict[str, Any]
) -> Set[str]:
    ids: Set[str] = set()

    for key in ("feasible_corrections", "blocked_corrections"):
        values = corrections.get(key, [])

        if not isinstance(values, list):
            continue

        for item in values:
            if not isinstance(item, dict):
                continue

            value = item.get("product_id")
            if value:
                ids.add(norm(value))

            for product in item.get("products", []):
                if isinstance(product, dict) and product.get("product_id"):
                    ids.add(norm(product["product_id"]))

    # Also accept a misplacement-detector JSON directly.
    for item in corrections.get("misplaced_products", []):
        if isinstance(item, dict) and item.get("product_id"):
            ids.add(norm(item["product_id"]))

    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve product occurrences between expected and actual "
            "planograms."
        )
    )

    parser.add_argument(
        "corrections",
        help=(
            "correction_engine_v2 JSON or "
            "misplacement_detector_v2 JSON"
        ),
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

    source_path = Path(args.corrections)
    actual_path = Path(args.actual)
    expected_path = Path(args.expected)
    rules_path = Path(args.rules)

    for label, path in (
        ("source", source_path),
        ("actual", actual_path),
        ("expected", expected_path),
        ("rules", rules_path),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    source = load_json(source_path)
    actual = load_json(actual_path)
    expected = load_json(expected_path)

    # Preserve pipeline compatibility. This resolver does not use generic
    # merchandising rules to override explicit location evidence.
    _rules = load_json(rules_path)

    actual_records = product_records(actual)
    expected_records = product_records(expected)

    actual_idx = index_records(actual_records)
    expected_idx = index_records(expected_records)

    candidate_ids = candidate_product_ids(source)

    # If no candidate IDs were supplied, reconcile every product present in
    # either map. This makes the utility useful for standalone auditing.
    if not candidate_ids:
        candidate_ids = set(actual_idx) | set(expected_idx)

    resolutions: List[Dict[str, Any]] = []

    for product_id in sorted(candidate_ids):
        resolutions.append(
            resolve_product(
                product_id,
                actual_idx.get(product_id, []),
                expected_idx.get(product_id, []),
            )
        )

    status_counts: Dict[str, int] = {}

    for resolution in resolutions:
        status = resolution["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    actionable_extra = [
        item
        for item in resolutions
        if item.get("status") == "CORRECT_OCCURRENCE"
        and item.get("extra_occurrences")
    ]

    ambiguous = [
        item
        for item in resolutions
        if item.get("status") == "AMBIGUOUS"
    ]

    missing = [
        item
        for item in resolutions
        if item.get("status") == "MISSING_EXPECTED_OCCURRENCE"
    ]

    misplaced = [
        item
        for item in resolutions
        if item.get("status") == "MISPLACED_OCCURRENCE"
    ]

    correct = [
        item
        for item in resolutions
        if item.get("status") == "CORRECT_OCCURRENCE"
    ]

    rack = (
        actual.get("rack_id")
        or actual.get("rack")
        or source.get("rack")
        or "UNKNOWN"
    )

    output = {
        "engine": "occurrence_resolver",
        "engine_version": VERSION,
        "rack": rack,
        "sources": {
            "source": str(source_path),
            "actual": str(actual_path),
            "expected": str(expected_path),
            "rules": str(rules_path),
        },
        "summary": {
            "products_reconciled": len(resolutions),
            "correct_occurrences": len(correct),
            "extra_occurrence_cases": len(actionable_extra),
            "misplaced_occurrences": len(misplaced),
            "missing_expected_occurrences": len(missing),
            "ambiguous_occurrences": len(ambiguous),
            "status_counts": status_counts,
        },
        "resolutions": resolutions,
        "extra_occurrence_cases": actionable_extra,
        "safety_boundary": (
            "This resolver only reconciles evidence. It does not authorize "
            "moves, removals, swaps, or cycle rotations. Ambiguous "
            "occurrences remain explicitly unresolved."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            source_path.parent
            / f"occurrences_{source_path.stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — OCCURRENCE RESOLVER")
    print("=" * 72)
    print(f"Rack: {rack}")
    print()
    print(f"Products reconciled       : {len(resolutions)}")
    print(f"Correct occurrences       : {len(correct)}")
    print(f"Extra-occurrence cases    : {len(actionable_extra)}")
    print(f"Misplaced occurrences     : {len(misplaced)}")
    print(f"Missing expected          : {len(missing)}")
    print(f"Ambiguous                 : {len(ambiguous)}")
    print("-" * 72)

    for resolution in resolutions:
        status = resolution["status"]
        if status == "CORRECT_OCCURRENCE":
            if resolution.get("extra_occurrences"):
                print(
                    f"EXTRA_OCCURRENCE: "
                    f"{resolution['product_name']} "
                    f"({resolution['product_id']})"
                )
                print(
                    "  Correct : Shelf "
                    f"{resolution['correct_occurrence']['shelf']} "
                    f"slots {resolution['correct_occurrence']['slots']}"
                )
                for extra in resolution["extra_occurrences"]:
                    print(
                        "  Extra   : Shelf "
                        f"{extra['shelf']} slots {extra['slots']}"
                    )

        elif status == "MISPLACED_OCCURRENCE":
            item = resolution["misplaced_occurrence"]
            expected_item = resolution["expected_occurrence"]
            print(
                f"MISPLACED_OCCURRENCE: "
                f"{resolution['product_name']} "
                f"({resolution['product_id']})"
            )
            print(
                f"  Current : Shelf {item['shelf']} "
                f"slots {item['slots']}"
            )
            print(
                f"  Expected: Shelf {expected_item['shelf']} "
                f"slots {expected_item['slots']}"
            )

        elif status == "MISSING_EXPECTED_OCCURRENCE":
            item = resolution["expected_occurrence"]
            print(
                f"MISSING_EXPECTED_OCCURRENCE: "
                f"{resolution['product_name']} "
                f"({resolution['product_id']})"
            )
            print(
                f"  Expected: Shelf {item['shelf']} "
                f"slots {item['slots']}"
            )

        elif status == "AMBIGUOUS":
            print(
                f"AMBIGUOUS: "
                f"{resolution['product_name']} "
                f"({resolution['product_id']})"
            )
            print(f"  Reason: {resolution['reason']}")

    print()
    print(f"Occurrence report written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
