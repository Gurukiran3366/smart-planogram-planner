#!/usr/bin/env python3
"""
SMART PLANOGRAM — CYCLE PLANNER

Finds safe multi-product rearrangement cycles from:
  - correction_engine_v2 output
  - actual_map
  - expected_map
  - merchandising_rules_v2

A cycle is only proposed when every product in the cycle currently occupies
the exact expected location of the next product.

Example:
    A is where B should be
    B is where C should be
    C is where A should be

Then the planner can recommend one 3-way rotation.

Safety:
  - Only products already flagged REARRANGEMENT_REQUIRED are considered.
  - Every product must have exactly one relevant actual occurrence.
  - Every expected location must be explicit.
  - Every edge in the cycle must match exact shelf + slot(s).
  - Direct 2-product swaps are left to rearrangement_planner.py.
  - Duplicate/ambiguous occurrences are REVIEW.
  - No capacity or new destination is invented.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


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
                    "raw": item,
                }
            )

    return records


def same_location(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (
        str(a["shelf"]) == str(b["shelf"])
        and set(a["slots"]) == set(b["slots"])
    )


def actual_index(
    records: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = {}

    for record in records:
        index.setdefault(norm(record["product_id"]), []).append(record)

    return index


def expected_index(
    records: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = {}

    for record in records:
        index.setdefault(norm(record["product_id"]), []).append(record)

    return index


def unique_record(
    index: Dict[str, List[Dict[str, Any]]],
    product_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    records = index.get(norm(product_id), [])

    if len(records) == 0:
        return None, "No map record exists."

    if len(records) > 1:
        return None, "Multiple map records exist; occurrence is ambiguous."

    return records[0], None


def build_rearrangement_ids(
    corrections: Dict[str, Any]
) -> Set[str]:
    ids: Set[str] = set()

    for item in corrections.get("blocked_corrections", []):
        if not isinstance(item, dict):
            continue

        if item.get("type") != "REARRANGEMENT_REQUIRED":
            continue

        product = item.get("product_id")
        if product:
            ids.add(norm(product))

    return ids


def build_next_edges(
    candidate_ids: Set[str],
    actual_idx: Dict[str, List[Dict[str, Any]]],
    expected_idx: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """
    Build a directed edge:
        current_product -> product_whose_expected_location_is_current_location

    Example:
        A is currently at B's expected location
        => A -> B
    """
    edges: Dict[str, str] = {}
    issues: List[Dict[str, Any]] = []

    expected_locations: Dict[str, List[str]] = {}

    for target_id in candidate_ids:
        expected_records = expected_idx.get(target_id, [])

        if len(expected_records) != 1:
            issues.append(
                {
                    "product_id": target_id,
                    "reason": (
                        "Expected-map occurrence is missing or ambiguous."
                    ),
                }
            )
            continue

        expected = expected_records[0]

        if not expected["slots"]:
            issues.append(
                {
                    "product_id": target_id,
                    "reason": "Expected destination slot is unknown.",
                }
            )
            continue

        expected_locations[target_id] = [
            f"{expected['shelf']}:{slot}"
            for slot in expected["slots"]
        ]

    # For every candidate product, identify which candidate's expected
    # location it currently occupies.
    for current_id in candidate_ids:
        actual_records = actual_idx.get(current_id, [])

        if len(actual_records) != 1:
            issues.append(
                {
                    "product_id": current_id,
                    "reason": (
                        "Actual occurrence is missing or duplicated; "
                        "cycle cannot be proven."
                    ),
                }
            )
            continue

        actual = actual_records[0]

        if not actual["slots"]:
            issues.append(
                {
                    "product_id": current_id,
                    "reason": "Actual slot is unknown.",
                }
            )
            continue

        actual_location = {
            f"{actual['shelf']}:{slot}"
            for slot in actual["slots"]
        }

        matching_targets = []

        for target_id, target_location in expected_locations.items():
            if actual_location == set(target_location):
                matching_targets.append(target_id)

        if len(matching_targets) == 1:
            target_id = matching_targets[0]

            if norm(target_id) == norm(current_id):
                continue

            edges[current_id] = target_id

        elif len(matching_targets) > 1:
            issues.append(
                {
                    "product_id": current_id,
                    "reason": (
                        "Current location matches multiple expected "
                        "locations; cycle is ambiguous."
                    ),
                    "matches": matching_targets,
                }
            )

    return edges, issues


def find_cycles(
    edges: Dict[str, str],
    minimum_length: int = 3,
) -> List[List[str]]:
    """
    Find directed cycles in a functional graph.

    Since every node has at most one outgoing edge, each discovered cycle
    can be canonicalized and deduplicated.
    """
    cycles: List[List[str]] = []
    seen_cycles: Set[Tuple[str, ...]] = set()

    for start in edges:
        path: List[str] = []
        position: Dict[str, int] = {}
        current = start

        while current in edges:
            if current in position:
                cycle = path[position[current]:]

                if len(cycle) >= minimum_length:
                    # Canonical rotation so A->B->C and B->C->A are same.
                    rotations = [
                        tuple(cycle[i:] + cycle[:i])
                        for i in range(len(cycle))
                    ]
                    canonical = min(rotations)

                    if canonical not in seen_cycles:
                        seen_cycles.add(canonical)
                        cycles.append(list(canonical))
                break

            if current in path:
                break

            position[current] = len(path)
            path.append(current)
            current = edges[current]

    return cycles


def validate_cycle(
    cycle: List[str],
    actual_idx: Dict[str, List[Dict[str, Any]]],
    expected_idx: Dict[str, List[Dict[str, Any]]],
) -> Tuple[bool, List[str]]:
    """
    For cycle:
        A -> B -> C -> A

    verify:
        A current == B expected
        B current == C expected
        C current == A expected
    """
    reasons: List[str] = []

    if len(cycle) < 3:
        return False, ["Cycle has fewer than 3 products."]

    for product_id in cycle:
        actual_records = actual_idx.get(product_id, [])
        expected_records = expected_idx.get(product_id, [])

        if len(actual_records) != 1:
            reasons.append(
                f"{product_id}: actual occurrence is missing or ambiguous."
            )

        if len(expected_records) != 1:
            reasons.append(
                f"{product_id}: expected occurrence is missing or ambiguous."
            )

    if reasons:
        return False, reasons

    for i, current_id in enumerate(cycle):
        next_id = cycle[(i + 1) % len(cycle)]

        current = actual_idx[current_id][0]
        next_expected = expected_idx[next_id][0]

        if not same_location(current, next_expected):
            reasons.append(
                f"{current_id} is not exactly at {next_id}'s expected "
                "location."
            )

    return len(reasons) == 0, reasons


def build_cycle_action(
    cycle: List[str],
    actual_idx: Dict[str, List[Dict[str, Any]]],
    expected_idx: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    products = []

    for product_id in cycle:
        current = actual_idx[product_id][0]
        expected = expected_idx[product_id][0]

        products.append(
            {
                "product_id": current["product_id"],
                "product_name": current["product_name"],
                "current_shelf": current["shelf"],
                "current_slots": current["slots"],
                "target_shelf": expected["shelf"],
                "target_slots": expected["slots"],
            }
        )

    names = [item["product_name"] for item in products]

    return {
        "type": "MULTI_PRODUCT_CYCLE",
        "status": "FEASIBLE",
        "cycle_length": len(cycle),
        "product_ids": cycle,
        "products": products,
        "action": (
            "Rotate the products in this cycle to their expected "
            "locations: " + " → ".join(names) + " → " + names[0] + "."
        ),
        "evidence": [
            "Every product has exactly one relevant actual occurrence.",
            "Every product has exactly one expected occurrence.",
            "Every current location exactly matches the next product's "
            "expected location.",
            "No new shelf, slot, or physical capacity is invented.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Find safe multi-product rearrangement cycles from "
            "correction_engine_v2 output."
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

    correction_path = Path(args.corrections)
    actual_path = Path(args.actual)
    expected_path = Path(args.expected)
    rules_path = Path(args.rules)

    for label, path in (
        ("corrections", correction_path),
        ("actual", actual_path),
        ("expected", expected_path),
        ("rules", rules_path),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    corrections = load_json(correction_path)
    actual = load_json(actual_path)
    expected = load_json(expected_path)

    # Preserve the pipeline contract. Rules are not used to override
    # explicit location evidence in this conservative cycle planner.
    _rules = load_json(rules_path)

    actual_records = product_records(actual)
    expected_records = product_records(expected)

    actual_idx = actual_index(actual_records)
    expected_idx = expected_index(expected_records)

    candidate_ids = build_rearrangement_ids(corrections)

    edges, graph_issues = build_next_edges(
        candidate_ids,
        actual_idx,
        expected_idx,
    )

    cycles = find_cycles(edges, minimum_length=3)

    safe_cycles: List[Dict[str, Any]] = []
    rejected_cycles: List[Dict[str, Any]] = []

    for cycle in cycles:
        valid, reasons = validate_cycle(
            cycle,
            actual_idx,
            expected_idx,
        )

        if valid:
            safe_cycles.append(
                build_cycle_action(
                    cycle,
                    actual_idx,
                    expected_idx,
                )
            )
        else:
            rejected_cycles.append(
                {
                    "cycle": cycle,
                    "status": "BLOCKED",
                    "reasons": reasons,
                }
            )

    used_ids = {
        norm(product_id)
        for cycle in safe_cycles
        for product_id in cycle["product_ids"]
    }

    unresolved = []

    for product_id in sorted(candidate_ids):
        if product_id in used_ids:
            continue

        unresolved.append(
            {
                "product_id": product_id,
                "type": "REVIEW_REARRANGEMENT",
                "status": "BLOCKED",
                "reason": (
                    "Product is not part of a proven 3+ product cycle. "
                    "A more complex or partial rearrangement is not "
                    "automatically authorized."
                ),
            }
        )

    if safe_cycles:
        decision = "ACTION_RECOMMENDED"
        recommendation = "SAFE MULTI-PRODUCT REARRANGEMENT"
    else:
        decision = "REVIEW_NO_SAFE_CYCLE"
        recommendation = "REVIEW / NO SAFE CYCLE PROVEN"

    rack = (
        actual.get("rack_id")
        or actual.get("rack")
        or corrections.get("rack")
        or "UNKNOWN"
    )

    output = {
        "engine": "cycle_planner",
        "engine_version": VERSION,
        "rack": rack,
        "sources": {
            "corrections": str(correction_path),
            "actual": str(actual_path),
            "expected": str(expected_path),
            "rules": str(rules_path),
        },
        "summary": {
            "rearrangement_candidates_received": len(candidate_ids),
            "graph_edges_proven": len(edges),
            "safe_cycles": len(safe_cycles),
            "rejected_cycles": len(rejected_cycles),
            "unresolved_products": len(unresolved),
        },
        "decision": decision,
        "recommendation": recommendation,
        "safe_cycles": safe_cycles,
        "rejected_cycles": rejected_cycles,
        "graph_issues": graph_issues,
        "unresolved_products": unresolved,
        "safety_boundary": (
            "Only exact 3+ product cycles are automatically recommended. "
            "Every edge must map a product's current location exactly to "
            "the next product's expected location. Direct swaps remain "
            "the responsibility of rearrangement_planner.py. Ambiguous "
            "duplicates, partial chains, and cycles requiring a new "
            "destination remain REVIEW."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            correction_path.parent
            / f"cycles_{correction_path.stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — CYCLE PLANNER")
    print("=" * 72)
    print(f"Rack: {rack}")
    print()
    print(
        "Rearrangement candidates received : "
        f"{len(candidate_ids)}"
    )
    print(f"Graph edges proven                 : {len(edges)}")
    print(f"Safe cycles generated              : {len(safe_cycles)}")
    print(f"Rejected cycles                    : {len(rejected_cycles)}")
    print(f"Unresolved products                : {len(unresolved)}")
    print(f"Decision                            : {decision}")
    print("-" * 72)

    if safe_cycles:
        print("SAFE MULTI-PRODUCT CYCLES")
        for index, cycle in enumerate(safe_cycles, start=1):
            print()
            print(f"{index}. {cycle['action']}")

            for product in cycle["products"]:
                print(
                    f"   {product['product_name']}: "
                    f"Shelf {product['current_shelf']} "
                    f"{product['current_slots']} → "
                    f"Shelf {product['target_shelf']} "
                    f"{product['target_slots']}"
                )
    else:
        print("NO SAFE 3+ PRODUCT CYCLE PROVEN")

    if unresolved:
        print()
        print("REVIEW / UNRESOLVED")
        for item in unresolved:
            print(
                f"  {item['product_id']}: "
                f"{item['reason']}"
            )

    if graph_issues:
        print()
        print("GRAPH DATA ISSUES")
        for issue in graph_issues:
            print(
                f"  {issue['product_id']}: "
                f"{issue['reason']}"
            )

    print()
    print(f"Cycle plan written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
