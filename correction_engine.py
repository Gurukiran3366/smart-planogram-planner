#!/usr/bin/env python3
"""
SMART PLANOGRAM — CORRECTION ENGINE

Consumes the structured output of shelf_analyzer.py and produces
physically executable correction recommendations.

Design principles:
- Never modify shelf_analyzer.py.
- Never correct an OOS product.
- Never remove a product that has no excess facing.
- Never add a product when physical space is not proven.
- Never treat preferred order as exact slot order.
- Prefer minimum physical movements.
- If safety cannot be proven, return REVIEW.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


ENGINE_VERSION = "1.1"


# ---------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )


def is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or is_nan(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# OOS
# ---------------------------------------------------------------------

def get_oos_ids(shelf: Dict[str, Any]) -> set[str]:
    result = set()

    for item in shelf.get("out_of_stock_products", []) or []:
        product_id = item.get("product_id")
        if product_id:
            result.add(product_id)

    return result


def is_oos_product(shelf: Dict[str, Any], product_id: str) -> bool:
    return product_id in get_oos_ids(shelf)


# ---------------------------------------------------------------------
# FACING ANALYSIS
# ---------------------------------------------------------------------

def get_facing_detail(
    shelf: Dict[str, Any],
    product_id: str,
) -> Optional[Dict[str, Any]]:
    facings = shelf.get("facings", {}) or {}

    for detail in facings.get("details", []) or []:
        if detail.get("product_id") == product_id:
            return detail

    return None


def excess_facing_available(
    shelf: Dict[str, Any],
    product_id: str,
) -> bool:
    """
    A product can only be displaced safely if it has a genuine
    excess facing.

    Example:
        expected = 1
        actual   = 2
        -> one facing may potentially be released.

    But:
        expected = 1
        actual   = 1
        -> cannot remove it merely to create space.
    """

    detail = get_facing_detail(shelf, product_id)

    if not detail:
        return False

    actual = safe_int(detail.get("actual_facings"))
    expected = safe_int(detail.get("expected_facings"))

    if actual is None or expected is None:
        return False

    return actual > expected


# ---------------------------------------------------------------------
# CAPACITY
# ---------------------------------------------------------------------

def get_capacity_info(shelf: Dict[str, Any]) -> Dict[str, Any]:
    capacity = shelf.get("capacity", {}) or {}

    return {
        "status": capacity.get("status"),
        "capacity": safe_int(capacity.get("capacity")),
        "occupied_slots": safe_int(capacity.get("occupied_slots")),
        "remaining_slots": safe_int(capacity.get("remaining_slots")),
    }


def proven_free_space(shelf: Dict[str, Any]) -> bool:
    """
    Returns True ONLY when the analysis explicitly proves that
    physical capacity remains.

    Unknown capacity is NOT treated as free space.
    """

    capacity = get_capacity_info(shelf)

    remaining = capacity.get("remaining_slots")

    if remaining is None:
        return False

    return remaining > 0


# ---------------------------------------------------------------------
# MISSING PRODUCTS
# ---------------------------------------------------------------------

def get_missing_products(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    missing = shelf.get("missing_products", {}) or {}
    return missing.get("details", []) or []


# ---------------------------------------------------------------------
# BLOCKED CORRECTION DIAGNOSTICS
# ---------------------------------------------------------------------

def diagnose_missing_product(
    shelf: Dict[str, Any],
    missing: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Explain why a missing-product correction can or cannot be made.

    This function intentionally does NOT create an action unless
    physical feasibility is proven.
    """

    product_id = missing.get("product_id")
    product_name = missing.get("product_name")
    expected_slot = safe_int(missing.get("expected_slot"))

    destination_id = missing.get("destination_occupant")
    destination_name = missing.get("destination_occupant_name")

    reasons = []
    checks = []

    # -------------------------------------------------------------
    # OOS check
    # -------------------------------------------------------------

    if product_id and is_oos_product(shelf, product_id):
        checks.append({
            "check": "oos_status",
            "result": "blocked",
            "detail": (
                f"{product_name or product_id} is marked out of stock "
                "and is excluded from correction."
            ),
        })

        return {
            "product_id": product_id,
            "product_name": product_name,
            "expected_slot": expected_slot,
            "decision": "BLOCKED_OOS",
            "safe_action": False,
            "checks": checks,
            "reasons": [
                "product_is_out_of_stock",
                "oos_products_are_excluded_from_correction",
            ],
        }

    checks.append({
        "check": "oos_status",
        "result": "pass",
        "detail": "Product is not marked OOS.",
    })

    # -------------------------------------------------------------
    # Destination occupancy
    # -------------------------------------------------------------

    if destination_id:
        checks.append({
            "check": "destination_occupancy",
            "result": "occupied",
            "detail": (
                f"Expected slot {expected_slot} is occupied by "
                f"{destination_name or destination_id}."
            ),
        })

        # ---------------------------------------------------------
        # Can occupant give up an excess facing?
        # ---------------------------------------------------------

        occupant_detail = get_facing_detail(
            shelf,
            destination_id,
        )

        if occupant_detail:
            actual = safe_int(
                occupant_detail.get("actual_facings")
            )
            expected = safe_int(
                occupant_detail.get("expected_facings")
            )

            excess = excess_facing_available(
                shelf,
                destination_id,
            )

            checks.append({
                "check": "destination_occupant_facing",
                "product_id": destination_id,
                "product_name": destination_name,
                "actual_facings": actual,
                "expected_facings": expected,
                "excess_facing_available": excess,
                "result": "pass" if excess else "blocked",
            })

            if not excess:
                reasons.append(
                    "destination_occupant_has_no_excess_facing"
                )

        else:
            checks.append({
                "check": "destination_occupant_facing",
                "product_id": destination_id,
                "product_name": destination_name,
                "result": "unknown",
                "detail": (
                    "No facing record exists for the destination occupant."
                ),
            })

            reasons.append(
                "destination_occupant_facing_unknown"
            )

    else:
        checks.append({
            "check": "destination_occupancy",
            "result": "free",
            "detail": (
                f"Expected slot {expected_slot} has no recorded occupant."
            ),
        })

    # -------------------------------------------------------------
    # Capacity
    # -------------------------------------------------------------

    capacity = get_capacity_info(shelf)

    if proven_free_space(shelf):
        checks.append({
            "check": "physical_capacity",
            "result": "pass",
            "capacity": capacity.get("capacity"),
            "occupied_slots": capacity.get("occupied_slots"),
            "remaining_slots": capacity.get("remaining_slots"),
        })

    else:
        checks.append({
            "check": "physical_capacity",
            "result": "unknown",
            "capacity": capacity.get("capacity"),
            "occupied_slots": capacity.get("occupied_slots"),
            "remaining_slots": capacity.get("remaining_slots"),
            "detail": (
                "Shelf capacity is not known sufficiently to prove "
                "that an additional physical position exists."
            ),
        })

        reasons.append(
            "physical_space_not_proven"
        )

    # -------------------------------------------------------------
    # Decision
    # -------------------------------------------------------------

    if not destination_id and proven_free_space(shelf):
        return {
            "product_id": product_id,
            "product_name": product_name,
            "expected_slot": expected_slot,
            "decision": "SAFE_ADD",
            "safe_action": True,
            "checks": checks,
            "reasons": [],
            "action": {
                "type": "add_product",
                "product_id": product_id,
                "product_name": product_name,
                "target_slot": expected_slot,
            },
        }

    # Occupant has excess facing AND the destination is occupied.
    if (
        destination_id
        and excess_facing_available(shelf, destination_id)
    ):
        return {
            "product_id": product_id,
            "product_name": product_name,
            "expected_slot": expected_slot,
            "decision": "SAFE_REDUCE_OCCUPANT",
            "safe_action": True,
            "checks": checks,
            "reasons": reasons,
            "action": {
                "type": "reduce_excess_facing_and_place",
                "remove_product_id": destination_id,
                "remove_product_name": destination_name,
                "target_product_id": product_id,
                "target_product_name": product_name,
                "target_slot": expected_slot,
            },
        }

    return {
        "product_id": product_id,
        "product_name": product_name,
        "expected_slot": expected_slot,
        "decision": "REVIEW_NO_SAFE_ACTION",
        "safe_action": False,
        "checks": checks,
        "reasons": list(dict.fromkeys(reasons)),
    }


# ---------------------------------------------------------------------
# SHELF CANDIDATES
# ---------------------------------------------------------------------

def generate_shelf_candidates(
    shelf: Dict[str, Any],
) -> Dict[str, Any]:

    shelf_number = safe_int(shelf.get("shelf_number"))
    shelf_name = shelf.get("shelf_name")

    missing = get_missing_products(shelf)

    candidates = []
    blocked_diagnostics = []

    for item in missing:
        diagnosis = diagnose_missing_product(
            shelf,
            item,
        )

        blocked_diagnostics.append(diagnosis)

        if diagnosis.get("safe_action"):
            candidates.append({
                "shelf_number": shelf_number,
                "shelf_name": shelf_name,
                "decision": diagnosis["decision"],
                "action": diagnosis["action"],
                "reason": diagnosis.get("reasons", []),
            })

    return {
        "shelf_number": shelf_number,
        "shelf_name": shelf_name,
        "candidates": candidates,
        "blocked_diagnostics": blocked_diagnostics,
    }


# ---------------------------------------------------------------------
# MAIN ENGINE
# ---------------------------------------------------------------------

def run_correction_engine(
    analysis: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    shelves = analysis.get("shelves", []) or []

    all_candidates = []
    feasible_candidates = []
    blocked_diagnostics = []

    shelf_results = []

    for shelf in shelves:

        result = generate_shelf_candidates(shelf)

        shelf_results.append(result)

        all_candidates.extend(
            result.get("candidates", [])
        )

        blocked_diagnostics.extend(
            result.get("blocked_diagnostics", [])
        )

    # -------------------------------------------------------------
    # Feasibility
    # -------------------------------------------------------------

    for candidate in all_candidates:

        action = candidate.get("action", {})

        if action.get("type") in {
            "add_product",
            "reduce_excess_facing_and_place",
        }:
            feasible_candidates.append(candidate)

    # -------------------------------------------------------------
    # Decision
    # -------------------------------------------------------------

    if feasible_candidates:
        decision = "ACTION_RECOMMENDED"
    else:
        decision = "REVIEW"

    # -------------------------------------------------------------
    # Human-readable explanation
    # -------------------------------------------------------------

    explanation = []

    if not feasible_candidates:

        explanation.append(
            "No safe physical correction can be proven from "
            "the structured diagnosis."
        )

        for blocked in blocked_diagnostics:

            if blocked.get("decision") != "REVIEW_NO_SAFE_ACTION":
                continue

            name = (
                blocked.get("product_name")
                or blocked.get("product_id")
                or "Unknown product"
            )

            reasons = blocked.get("reasons", [])

            explanation.append(
                f"{name}:"
            )

            if "destination_occupant_has_no_excess_facing" in reasons:
                explanation.append(
                    "  - Destination occupant has no excess facing; "
                    "removing it would create a new merchandising violation."
                )

            if "physical_space_not_proven" in reasons:
                explanation.append(
                    "  - Physical shelf capacity is unknown; "
                    "additional space cannot be assumed."
                )

            if "destination_occupant_facing_unknown" in reasons:
                explanation.append(
                    "  - Destination occupant facing data is unknown."
                )

        explanation.append(
            "Do not invent an action."
        )

    else:
        explanation.append(
            f"{len(feasible_candidates)} physically feasible "
            "correction candidate(s) identified."
        )

    output = {
        "engine_version": ENGINE_VERSION,
        "analyzer_version": analysis.get("analyzer_version"),
        "rack_id": analysis.get("rack_id"),

        "principles": {
            "minimum_physical_movements": True,
            "never_add_without_proven_space": True,
            "never_remove_non_excess_facing": True,
            "never_correct_oos_products": True,
            "unknown_capacity_means_review": True,
            "preferred_order_is_not_exact_slot_order": True,
        },

        "summary": {
            "shelves_analyzed": len(shelves),
            "candidates_generated": len(all_candidates),
            "feasible_candidates": len(feasible_candidates),
            "blocked_diagnostics": len(blocked_diagnostics),
            "decision": decision,
        },

        "shelves": shelf_results,

        "candidates": all_candidates,

        "feasible_candidates": feasible_candidates,

        "blocked_corrections": blocked_diagnostics,

        "recommendation": {
            "decision": decision,
            "summary": (
                " / ".join(explanation)
            ),
            "details": explanation,
        },
    }

    return output


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "SMART PLANOGRAM — Correction Engine"
        )
    )

    parser.add_argument(
        "analysis",
        help="Path to shelf_analyzer analysis JSON",
    )

    parser.add_argument(
        "--rules",
        default="merchandising_rules_v2.json",
        help="Path to merchandising rules JSON",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path",
    )

    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    rules_path = Path(args.rules)

    analysis = load_json(analysis_path)

    rules = None

    if rules_path.exists():
        rules = load_json(rules_path)

    result = run_correction_engine(
        analysis,
        rules,
    )

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            analysis_path.parent
            / f"corrections_{analysis_path.name}"
        )

    save_json(
        result,
        output_path,
    )

    # -------------------------------------------------------------
    # Console output
    # -------------------------------------------------------------

    summary = result["summary"]
    recommendation = result["recommendation"]

    print()
    print("=" * 72)
    print("SMART PLANOGRAM — CORRECTION ENGINE")
    print("=" * 72)

    print(
        f"Rack: {result.get('rack_id')}"
    )

    print(
        f"Candidates generated : "
        f"{summary['candidates_generated']}"
    )

    print(
        f"Feasible candidates  : "
        f"{summary['feasible_candidates']}"
    )

    print(
        f"Blocked diagnostics  : "
        f"{summary['blocked_diagnostics']}"
    )

    print(
        f"Decision              : "
        f"{summary['decision']}"
    )

    print("-" * 72)

    if summary["decision"] == "ACTION_RECOMMENDED":

        print(
            "RECOMMENDATION: SAFE PHYSICAL CORRECTION"
        )

        for candidate in result["feasible_candidates"]:

            action = candidate["action"]

            print()

            if action["type"] == "add_product":

                print(
                    f"Shelf {candidate['shelf_number']}: "
                    f"ADD {action['product_name']} "
                    f"at slot {action['target_slot']}"
                )

            elif (
                action["type"]
                == "reduce_excess_facing_and_place"
            ):

                print(
                    f"Shelf {candidate['shelf_number']}: "
                    f"reduce excess facing of "
                    f"{action['remove_product_name']} "
                    f"and place "
                    f"{action['target_product_name']} "
                    f"at slot {action['target_slot']}"
                )

    else:

        print(
            "RECOMMENDATION: REVIEW / NO SAFE ACTION"
        )

        print()

        for line in recommendation["details"]:
            print(line)

    print()
    print(
        f"Correction analysis written to: "
        f"{output_path}"
    )
    print("=" * 72)


if __name__ == "__main__":
    main()