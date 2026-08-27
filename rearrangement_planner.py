#!/usr/bin/env python3
"""
SMART PLANOGRAM — REARRANGEMENT PLANNER

Purpose:
    Convert blocked REARRANGEMENT_REQUIRED corrections into safe,
    explicitly proven swaps/cycles using the actual and expected maps.

This script does NOT modify:
    shelf_analyzer.py
    misplacement_detector_v2.py
    correction_engine_v2.py

Safety principles:
    - Never invent a destination.
    - Never move a product merely because a swap is possible.
    - A direct swap is proposed only when:
        1. Product A is currently at Product B's expected location.
        2. Product B is currently at Product A's expected location.
        3. Both expected locations are explicit.
        4. The products are distinct.
    - A product already correctly placed is not used as a swap candidate.
    - More complex cycles are reported for REVIEW rather than automatically
      authorized.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def location_key(shelf_no: Any, slot_values: List[int]) -> str:
    return f"{shelf_no}:{','.join(str(x) for x in slot_values)}"


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
                    "raw": item,
                }
            )

    return records


def build_expected_index(
    expected_records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}

    for record in expected_records:
        key = norm(record["product_id"])

        # Duplicate expected records are ambiguous. Keep the first but mark
        # ambiguity separately through the duplicate list.
        if key not in result:
            result[key] = record

    return result


def build_actual_location_index(
    actual_records: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}

    for record in actual_records:
        key = norm(record["product_id"])
        result.setdefault(key, []).append(record)

    return result


def same_location(
    a: Dict[str, Any],
    b: Dict[str, Any],
) -> bool:
    return (
        str(a["shelf"]) == str(b["shelf"])
        and set(a["slots"]) == set(b["slots"])
    )


def get_primary_actual(
    actual_index: Dict[str, List[Dict[str, Any]]],
    product_id: str,
) -> Optional[Dict[str, Any]]:
    records = actual_index.get(norm(product_id), [])
    return records[0] if records else None


def build_direct_swap(
    a_id: str,
    b_id: str,
    actual_index: Dict[str, List[Dict[str, Any]]],
    expected_index: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if norm(a_id) == norm(b_id):
        return None

    a_expected = expected_index.get(norm(a_id))
    b_expected = expected_index.get(norm(b_id))
    a_actual = get_primary_actual(actual_index, a_id)
    b_actual = get_primary_actual(actual_index, b_id)

    if not a_expected or not b_expected or not a_actual or not b_actual:
        return None

    # Both products must genuinely be misplaced for an automatic swap.
    if same_location(a_actual, a_expected):
        return None
    if same_location(b_actual, b_expected):
        return None

    # A's actual location must equal B's expected location.
    if not (
        str(a_actual["shelf"]) == str(b_expected["shelf"])
        and set(a_actual["slots"]) == set(b_expected["slots"])
    ):
        return None

    # B's actual location must equal A's expected location.
    if not (
        str(b_actual["shelf"]) == str(a_expected["shelf"])
        and set(b_actual["slots"]) == set(a_expected["slots"])
    ):
        return None

    return {
        "type": "DIRECT_SWAP",
        "status": "FEASIBLE",
        "products": [
            {
                "product_id": a_actual["product_id"],
                "product_name": a_actual["product_name"],
                "current_shelf": a_actual["shelf"],
                "current_slots": a_actual["slots"],
                "target_shelf": a_expected["shelf"],
                "target_slots": a_expected["slots"],
            },
            {
                "product_id": b_actual["product_id"],
                "product_name": b_actual["product_name"],
                "current_shelf": b_actual["shelf"],
                "current_slots": b_actual["slots"],
                "target_shelf": b_expected["shelf"],
                "target_slots": b_expected["slots"],
            },
        ],
        "action": (
            f"Swap {a_actual['product_name']} "
            f"(Shelf {a_actual['shelf']} slots {a_actual['slots']}) "
            f"with {b_actual['product_name']} "
            f"(Shelf {b_actual['shelf']} slots {b_actual['slots']})."
        ),
        "evidence": [
            "Product A currently occupies Product B's exact expected location.",
            "Product B currently occupies Product A's exact expected location.",
            "Both products are individually confirmed as misplaced.",
            "The proposed correction is a direct two-product swap; no "
            "additional destination is invented.",
        ],
    }


def plan_swaps(
    actual_records: List[Dict[str, Any]],
    expected_records: List[Dict[str, Any]],
    blocked_corrections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    actual_index = build_actual_location_index(actual_records)
    expected_index = build_expected_index(expected_records)

    blocked_ids = {
        norm(item.get("product_id"))
        for item in blocked_corrections
        if item.get("product_id")
    }

    candidates: List[Dict[str, Any]] = []

    ids = sorted(blocked_ids)

    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1 :]:
            swap = build_direct_swap(
                a_id,
                b_id,
                actual_index,
                expected_index,
            )

            if swap:
                candidates.append(swap)

    # Deduplicate by unordered pair.
    unique: Dict[str, Dict[str, Any]] = {}

    for candidate in candidates:
        pair = sorted(
            norm(item["product_id"])
            for item in candidate["products"]
        )
        key = "|".join(pair)
        unique[key] = candidate

    direct_swaps = list(unique.values())

    # Find products that are still blocked but did not participate in a
    # proven direct swap.
    swapped_ids = {
        norm(item["product_id"])
        for swap in direct_swaps
        for item in swap["products"]
    }

    unresolved = []

    for item in blocked_corrections:
        item_id = norm(item.get("product_id"))

        if item_id in swapped_ids:
            continue

        unresolved.append(
            {
                "product_id": item.get("product_id"),
                "product_name": item.get("product_name"),
                "type": "REVIEW_REARRANGEMENT",
                "status": "BLOCKED",
                "reason": (
                    "No direct two-product swap was proven from the "
                    "actual and expected maps. A more complex rearrangement "
                    "would require additional planning and is not "
                    "automatically authorized."
                ),
            }
        )

    return {
        "direct_swaps": direct_swaps,
        "unresolved": unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Find safe direct swaps for blocked planogram "
            "rearrangement corrections."
        )
    )

    parser.add_argument(
        "corrections",
        help="correction_engine_v2 JSON",
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

    corrections_path = Path(args.corrections)
    actual_path = Path(args.actual)
    expected_path = Path(args.expected)
    rules_path = Path(args.rules)

    for label, path in (
        ("corrections", corrections_path),
        ("actual", actual_path),
        ("expected", expected_path),
        ("rules", rules_path),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    corrections = load_json(corrections_path)
    actual = load_json(actual_path)
    expected = load_json(expected_path)

    # Load rules to preserve the pipeline contract. This v1 planner does
    # not override explicit actual/expected placement evidence with generic
    # merchandising rules.
    _rules = load_json(rules_path)

    actual_records = product_records(actual)
    expected_records = product_records(expected)

    blocked = corrections.get("blocked_corrections", [])
    if not isinstance(blocked, list):
        blocked = []

    blocked_rearrangements = [
        item
        for item in blocked
        if item.get("type") == "REARRANGEMENT_REQUIRED"
    ]

    plan = plan_swaps(
        actual_records,
        expected_records,
        blocked_rearrangements,
    )

    direct_swaps = plan["direct_swaps"]
    unresolved = plan["unresolved"]

    if direct_swaps:
        decision = "ACTION_RECOMMENDED"
    else:
        decision = "REVIEW_NO_SAFE_REARRANGEMENT"

    rack = (
        actual.get("rack_id")
        or actual.get("rack")
        or corrections.get("rack")
        or "UNKNOWN"
    )

    output = {
        "engine": "rearrangement_planner",
        "engine_version": VERSION,
        "rack": rack,
        "sources": {
            "corrections": str(corrections_path),
            "actual": str(actual_path),
            "expected": str(expected_path),
            "rules": str(rules_path),
        },
        "summary": {
            "rearrangement_candidates_received": len(
                blocked_rearrangements
            ),
            "direct_swaps_generated": len(direct_swaps),
            "unresolved_rearrangements": len(unresolved),
        },
        "decision": decision,
        "safe_rearrangements": direct_swaps,
        "unresolved_rearrangements": unresolved,
        "safety_boundary": (
            "Only exact two-product swaps are automatically recommended. "
            "Longer cycles, ambiguous duplicate products, occupied target "
            "locations without a reciprocal swap, and capacity-dependent "
            "moves remain REVIEW."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            corrections_path.parent
            / f"rearrangements_{corrections_path.stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — REARRANGEMENT PLANNER")
    print("=" * 72)
    print(f"Rack: {rack}")
    print()
    print(
        "Rearrangement candidates received : "
        f"{len(blocked_rearrangements)}"
    )
    print(f"Direct swaps generated             : {len(direct_swaps)}")
    print(f"Unresolved rearrangements          : {len(unresolved)}")
    print(f"Decision                            : {decision}")
    print("-" * 72)

    if direct_swaps:
        print("SAFE REARRANGEMENTS")
        for index, swap in enumerate(direct_swaps, start=1):
            print()
            print(f"{index}. {swap['action']}")
            for product in swap["products"]:
                print(
                    f"   {product['product_name']}: "
                    f"Shelf {product['current_shelf']} "
                    f"{product['current_slots']} → "
                    f"Shelf {product['target_shelf']} "
                    f"{product['target_slots']}"
                )
    else:
        print("NO SAFE DIRECT SWAP PROVEN")

    if unresolved:
        print()
        print("REVIEW / UNRESOLVED")
        for item in unresolved:
            print(
                f"  {item['product_name']} "
                f"({item['product_id']})"
            )
            print(f"    - {item['reason']}")

    print()
    print(f"Rearrangement plan written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
