#!/usr/bin/env python3
"""
SMART PLANOGRAM — FINAL RECOMMENDATION ENGINE

Combines:
    1. correction_engine_v2 output
    2. occurrence_resolver output
    3. rearrangement_planner output
    4. cycle_planner output

Purpose:
    Produce one conservative, staff-facing recommendation report.

This script is an orchestration/presentation layer.
It does NOT modify the underlying analyzer, detector, correction engine,
rearrangement planner, or cycle planner.

Safety:
    - Safe actions must come from upstream evidence.
    - Ambiguous occurrence cases are always REVIEW.
    - Direct swaps are accepted only from rearrangement_planner.
    - Multi-product cycles are accepted only from cycle_planner.
    - No new destination, slot, capacity, or movement is invented here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set


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


def product_id(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_id")
        or item.get("id")
        or ""
    )


def product_name(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_name")
        or item.get("name")
        or product_id(item)
    )


def build_ambiguous_ids(
    occurrence_report: Dict[str, Any],
) -> Set[str]:
    ids: Set[str] = set()

    for item in occurrence_report.get("resolutions", []):
        if not isinstance(item, dict):
            continue

        if item.get("status") == "AMBIGUOUS":
            value = item.get("product_id")
            if value:
                ids.add(norm(value))

    return ids


def build_extra_occurrence_actions(
    occurrence_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    for item in occurrence_report.get("extra_occurrence_cases", []):
        if not isinstance(item, dict):
            continue

        if item.get("status") != "CORRECT_OCCURRENCE":
            continue

        extras = item.get("extra_occurrences", [])
        correct = item.get("correct_occurrence")

        for extra in extras:
            actions.append(
                {
                    "type": "REMOVE_EXTRA_OCCURRENCE",
                    "status": "SAFE",
                    "product_id": item.get("product_id"),
                    "product_name": item.get("product_name"),
                    "remove_location": extra,
                    "keep_location": correct,
                    "action": (
                        f"Remove extra {item.get('product_name')} from "
                        f"Shelf {extra.get('shelf')} slots "
                        f"{extra.get('slots')}. Keep the correct occurrence "
                        f"on Shelf {correct.get('shelf')} slots "
                        f"{correct.get('slots')}."
                    ),
                    "evidence": (
                        "Occurrence resolver found exactly one correct "
                        "occurrence and explicitly identified the other "
                        "occurrence as extra."
                    ),
                }
            )

    return actions


def build_swap_actions(
    rearrangement_report: Dict[str, Any],
    ambiguous_ids: Set[str],
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    for swap in rearrangement_report.get("direct_swaps", []):
        if not isinstance(swap, dict):
            continue

        products = swap.get("products", [])

        ids = {
            norm(product_id(item))
            for item in products
            if isinstance(item, dict)
        }

        # Never accept a swap involving an ambiguous occurrence.
        if ids & ambiguous_ids:
            continue

        actions.append(
            {
                "type": "DIRECT_SWAP",
                "status": "SAFE",
                "products": products,
                "action": swap.get("action"),
                "evidence": swap.get("evidence", []),
            }
        )

    return actions


def build_cycle_actions(
    cycle_report: Dict[str, Any],
    ambiguous_ids: Set[str],
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    for cycle in cycle_report.get("safe_cycles", []):
        if not isinstance(cycle, dict):
            continue

        ids = {
            norm(value)
            for value in cycle.get("product_ids", [])
            if value
        }

        if ids & ambiguous_ids:
            continue

        actions.append(
            {
                "type": "MULTI_PRODUCT_CYCLE",
                "status": "SAFE",
                "cycle_length": cycle.get("cycle_length"),
                "product_ids": cycle.get("product_ids", []),
                "products": cycle.get("products", []),
                "action": cycle.get("action"),
                "evidence": cycle.get("evidence", []),
            }
        )

    return actions


def build_review_items(
    occurrence_report: Dict[str, Any],
    rearrangement_report: Dict[str, Any],
    cycle_report: Dict[str, Any],
    safe_action_ids: Set[str],
) -> List[Dict[str, Any]]:
    reviews: List[Dict[str, Any]] = []

    # Occurrence ambiguity has the highest priority.
    for item in occurrence_report.get("resolutions", []):
        if not isinstance(item, dict):
            continue

        if item.get("status") != "AMBIGUOUS":
            continue

        pid = product_id(item)

        reviews.append(
            {
                "type": "OCCURRENCE_AMBIGUITY",
                "priority": "HIGH",
                "product_id": pid,
                "product_name": product_name(item),
                "reason": item.get("reason"),
                "instruction": (
                    f"Manually verify {product_name(item)} before moving "
                    "anything."
                ),
            }
        )

    # Blocked rearrangements that are not already covered by an ambiguity.
    ambiguous_ids = {
        norm(item.get("product_id"))
        for item in reviews
        if item.get("product_id")
    }

    for item in rearrangement_report.get("unresolved", []):
        if not isinstance(item, dict):
            continue

        pid = norm(item.get("product_id"))

        if pid in ambiguous_ids:
            continue

        if pid in safe_action_ids:
            continue

        reviews.append(
            {
                "type": "REARRANGEMENT_REVIEW",
                "priority": "MEDIUM",
                "product_id": item.get("product_id"),
                "product_name": item.get("product_name"),
                "reason": item.get("reason"),
                "instruction": (
                    f"Review {item.get('product_name')} manually; "
                    "no safe automatic rearrangement was proven."
                ),
            }
        )

    for item in cycle_report.get("unresolved_products", []):
        if not isinstance(item, dict):
            continue

        pid = norm(item.get("product_id"))

        if pid in ambiguous_ids or pid in safe_action_ids:
            continue

        # Avoid duplicating a review already generated from the
        # rearrangement planner.
        if any(
            norm(existing.get("product_id")) == pid
            and existing.get("type") == "REARRANGEMENT_REVIEW"
            for existing in reviews
        ):
            continue

        reviews.append(
            {
                "type": "CYCLE_REVIEW",
                "priority": "MEDIUM",
                "product_id": item.get("product_id"),
                "product_name": item.get("product_name"),
                "reason": item.get("reason"),
                "instruction": (
                    f"Review {item.get('product_id')} manually; "
                    "no safe multi-product cycle was proven."
                ),
            }
        )

    return reviews


def build_do_not_change(
    occurrence_report: Dict[str, Any],
    safe_actions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    safe_extra_ids = {
        norm(item.get("product_id"))
        for item in safe_actions
        if item.get("type") == "REMOVE_EXTRA_OCCURRENCE"
    }

    for item in occurrence_report.get("resolutions", []):
        if not isinstance(item, dict):
            continue

        if item.get("status") != "CORRECT_OCCURRENCE":
            continue

        pid = norm(item.get("product_id"))

        if pid not in safe_extra_ids:
            continue

        correct = item.get("correct_occurrence")
        if not correct:
            continue

        result.append(
            {
                "product_id": item.get("product_id"),
                "product_name": item.get("product_name"),
                "location": correct,
                "instruction": (
                    f"Keep {item.get('product_name')} at Shelf "
                    f"{correct.get('shelf')} slots {correct.get('slots')}."
                ),
            }
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create one conservative staff-facing planogram "
            "recommendation from upstream correction reports."
        )
    )

    parser.add_argument(
        "--corrections",
        required=True,
        help="correction_engine_v2 JSON",
    )
    parser.add_argument(
        "--occurrences",
        required=True,
        help="occurrence_resolver JSON",
    )
    parser.add_argument(
        "--rearrangements",
        required=True,
        help="rearrangement_planner JSON",
    )
    parser.add_argument(
        "--cycles",
        required=True,
        help="cycle_planner JSON",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path",
    )

    args = parser.parse_args()

    correction_path = Path(args.corrections)
    occurrence_path = Path(args.occurrences)
    rearrangement_path = Path(args.rearrangements)
    cycle_path = Path(args.cycles)

    for label, path in (
        ("corrections", correction_path),
        ("occurrences", occurrence_path),
        ("rearrangements", rearrangement_path),
        ("cycles", cycle_path),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    corrections = load_json(correction_path)
    occurrences = load_json(occurrence_path)
    rearrangements = load_json(rearrangement_path)
    cycles = load_json(cycle_path)

    ambiguous_ids = build_ambiguous_ids(occurrences)

    safe_actions: List[Dict[str, Any]] = []

    # 1. Explicit extra-occurrence removals.
    safe_actions.extend(
        build_extra_occurrence_actions(occurrences)
    )

    # 2. Proven direct swaps.
    safe_actions.extend(
        build_swap_actions(
            rearrangements,
            ambiguous_ids,
        )
    )

    # 3. Proven multi-product cycles.
    safe_actions.extend(
        build_cycle_actions(
            cycles,
            ambiguous_ids,
        )
    )

    safe_action_ids: Set[str] = set()

    for action in safe_actions:
        if action.get("product_id"):
            safe_action_ids.add(norm(action["product_id"]))

        for item in action.get("products", []):
            if isinstance(item, dict) and item.get("product_id"):
                safe_action_ids.add(norm(item["product_id"]))

        for value in action.get("product_ids", []):
            if value:
                safe_action_ids.add(norm(value))

    reviews = build_review_items(
        occurrences,
        rearrangements,
        cycles,
        safe_action_ids,
    )

    do_not_change = build_do_not_change(
        occurrences,
        safe_actions,
    )

    # Remove duplicate safe actions by a stable signature.
    unique_actions: Dict[str, Dict[str, Any]] = {}

    for action in safe_actions:
        signature = json.dumps(
            {
                "type": action.get("type"),
                "product_id": action.get("product_id"),
                "products": action.get("products"),
                "product_ids": action.get("product_ids"),
                "remove_location": action.get("remove_location"),
            },
            sort_keys=True,
            default=str,
        )
        unique_actions[signature] = action

    safe_actions = list(unique_actions.values())

    if safe_actions:
        decision = "ACTION_RECOMMENDED"
    elif reviews:
        decision = "REVIEW_NO_SAFE_ACTION"
    else:
        decision = "NO_ACTION_REQUIRED"

    rack = (
        corrections.get("rack")
        or occurrences.get("rack")
        or rearrangements.get("rack")
        or cycles.get("rack")
        or "UNKNOWN"
    )

    output = {
        "engine": "final_recommendation_engine",
        "engine_version": VERSION,
        "rack": rack,
        "decision": decision,
        "summary": {
            "safe_actions": len(safe_actions),
            "review_items": len(reviews),
            "do_not_change": len(do_not_change),
            "ambiguous_products": len(ambiguous_ids),
        },
        "staff_recommendation": {
            "do_these_actions": safe_actions,
            "review_required": reviews,
            "do_not_change": do_not_change,
        },
        "source_reports": {
            "corrections": str(correction_path),
            "occurrences": str(occurrence_path),
            "rearrangements": str(rearrangement_path),
            "cycles": str(cycle_path),
        },
        "safety_boundary": (
            "Only actions already proven by upstream structured evidence "
            "are presented as safe. Ambiguous products are routed to "
            "manual review. This layer never invents a shelf, slot, "
            "capacity assumption, or movement."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            correction_path.parent
            / f"final_recommendations_{correction_path.stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — FINAL RECOMMENDATION ENGINE")
    print("=" * 72)
    print(f"Rack: {rack}")
    print()
    print(f"Safe actions       : {len(safe_actions)}")
    print(f"Review required    : {len(reviews)}")
    print(f"Do not change      : {len(do_not_change)}")
    print(f"Ambiguous products : {len(ambiguous_ids)}")
    print(f"Decision           : {decision}")
    print("-" * 72)

    if safe_actions:
        print("DO THESE ACTIONS")
        for index, action in enumerate(safe_actions, start=1):
            print(f"{index}. {action.get('action')}")

    if reviews:
        print()
        print("REVIEW REQUIRED")
        for index, item in enumerate(reviews, start=1):
            print(
                f"{index}. {item.get('product_name') or item.get('product_id')}"
            )
            print(f"   {item.get('instruction')}")
            print(f"   Reason: {item.get('reason')}")

    if do_not_change:
        print()
        print("DO NOT CHANGE")
        for item in do_not_change:
            print(f"  - {item.get('instruction')}")

    print()
    print(f"Final recommendation written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())