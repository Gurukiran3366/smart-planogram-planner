#!/usr/bin/env python3
"""
SMART PLANOGRAM — CORRECTION ENGINE v1.2

Adds conservative shelf-wide rearrangement simulation on top of the frozen
shelf_analyzer.py output.

Important:
- shelf_analyzer.py is NOT modified.
- A rearrangement never creates physical capacity.
- A missing product can only be inserted when an actual free physical slot
  is proven or an excess facing is explicitly available.
- Products with unknown fast-moving status are never removed automatically.
- OOS products are immovable/excluded from correction.
- Preferred order is soft; hard constraints always win.
- Colour sequence is not used as a hard constraint when the analyzer reports
  catalog colour granularity limitations.

V1.2 can:
1. Explain blocked corrections.
2. Detect true physical free slots from slot_start + actual_facings.
3. Generate one-move / one-facing candidate rearrangements.
4. Simulate the resulting shelf order.
5. Compare before/after preferred-order inversion counts.
6. Reject candidates that require removing an OOS product or a non-excess
   facing.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ENGINE_VERSION = "1.2"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def norm(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def get_oos_ids(shelf: Dict[str, Any]) -> set[str]:
    return {
        str(x.get("product_id"))
        for x in (shelf.get("out_of_stock_products") or [])
        if isinstance(x, dict) and x.get("product_id")
    }


def get_colour_details(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(
        (shelf.get("colour_sequence") or {}).get("details") or []
    )


def get_facing_details(shelf: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    details = (shelf.get("facings") or {}).get("details") or []
    return {
        str(x.get("product_id")): x
        for x in details
        if isinstance(x, dict) and x.get("product_id")
    }


def physical_units(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Expand product facings into physical slot units.

    Example:
      Limonata slot_start=6, actual_facings=2
      becomes physical slots 6 and 7.

    This prevents us from incorrectly interpreting slot 7 as free.
    """
    facing_map = get_facing_details(shelf)
    units: List[Dict[str, Any]] = []

    for item in get_colour_details(shelf):
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue

        start = safe_int(item.get("slot_start"))
        if start is None:
            continue

        facing = facing_map.get(pid, {})
        count = safe_int(facing.get("actual_facings")) or 1

        for offset in range(count):
            units.append({
                "slot": start + offset,
                "product_id": pid,
                "product_name": item.get("product_name", pid),
                "unit_index": offset + 1,
            })

    units.sort(key=lambda x: x["slot"])
    return units


def occupied_slots(shelf: Dict[str, Any]) -> List[int]:
    return [x["slot"] for x in physical_units(shelf)]


def proven_free_slots(shelf: Dict[str, Any]) -> List[int]:
    """
    A slot is considered free only when:
    - the analyzer provides a finite capacity, OR
    - the physical slot numbering itself contains a gap within a known
      physical range.

    With unknown capacity and no internal gap, we do not assume free space.
    """
    units = physical_units(shelf)
    if not units:
        return []

    capacity = safe_int((shelf.get("capacity") or {}).get("capacity"))
    if capacity is not None:
        occupied = set(occupied_slots(shelf))
        return [slot for slot in range(1, capacity + 1) if slot not in occupied]

    slots = occupied_slots(shelf)
    if not slots:
        return []

    # Only infer internal gaps. Do not infer slots after the last observed
    # position because shelf length/capacity is unknown.
    max_slot = max(slots)
    occupied = set(slots)
    return [slot for slot in range(1, max_slot + 1) if slot not in occupied]


def facing_excess(
    shelf: Dict[str, Any],
    product_id: str,
) -> bool:
    detail = get_facing_details(shelf).get(product_id)
    if not detail:
        return False

    actual = safe_int(detail.get("actual_facings"))
    expected = safe_int(detail.get("expected_facings"))

    return (
        actual is not None
        and expected is not None
        and actual > expected
    )


def preferred_rank_map(
    shelf: Dict[str, Any],
) -> Dict[str, int]:
    """
    The analyzer exposes the actual preferred-order score/inversions, but
    not the full preferred-rank mapping. V1.2 therefore derives a stable
    local ranking from the colour-sequence order when sequence_rank is
    available.

    If sequence_rank is unavailable (the current catalog has that limitation),
    this returns an empty map and we do not pretend to know exact product rank.
    """
    result = {}

    for item in get_colour_details(shelf):
        pid = str(item.get("product_id") or "").strip()
        rank = safe_int(item.get("sequence_rank"))
        if pid and rank is not None:
            result[pid] = rank

    return result


def order_inversions(units: List[Dict[str, Any]], rank_map: Dict[str, int]) -> int:
    if not rank_map:
        return 0

    ranks = [
        rank_map[u["product_id"]]
        for u in sorted(units, key=lambda x: x["slot"])
        if u["product_id"] in rank_map
    ]

    inversions = 0
    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):
            if ranks[i] > ranks[j]:
                inversions += 1

    return inversions


def move_unit(
    units: List[Dict[str, Any]],
    source_slot: int,
    destination_slot: int,
) -> List[Dict[str, Any]]:
    """
    Move one physical facing by shifting the intervening units.

    This is a simulation only. It does not alter the input analysis.
    """
    result = deepcopy(units)

    source_index = next(
        (i for i, x in enumerate(result) if x["slot"] == source_slot),
        None,
    )

    if source_index is None:
        return result

    unit = result.pop(source_index)

    if destination_slot < source_slot:
        # Insert before the first unit currently at/after destination.
        insert_at = next(
            (i for i, x in enumerate(result) if x["slot"] >= destination_slot),
            len(result),
        )
        result.insert(insert_at, unit)
    else:
        insert_at = next(
            (i for i, x in enumerate(result) if x["slot"] > destination_slot),
            len(result),
        )
        result.insert(insert_at, unit)

    # Re-number consecutive physical positions.
    for i, item in enumerate(result, start=1):
        item["slot"] = i

    return result


def score_rearrangement(
    before_units: List[Dict[str, Any]],
    after_units: List[Dict[str, Any]],
    shelf: Dict[str, Any],
) -> Dict[str, Any]:
    rank_map = preferred_rank_map(shelf)

    before = order_inversions(before_units, rank_map)
    after = order_inversions(after_units, rank_map)

    return {
        "preferred_order_inversions_before": before,
        "preferred_order_inversions_after": after,
        "inversion_improvement": before - after,
        "sequence_rank_data_available": bool(rank_map),
    }


def generate_rearrangement_candidates(
    shelf: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Generate conservative one-facing movements.

    We only consider movements of products that have a proven excess facing.
    This avoids removing a required facing merely to improve a soft preference.
    """
    units = physical_units(shelf)
    if not units:
        return []

    oos = get_oos_ids(shelf)
    free_slots = proven_free_slots(shelf)
    candidates: List[Dict[str, Any]] = []

    # Current engine does not invent a product replacement when capacity is
    # full. Rearrangement is only considered if a real free slot exists.
    if not free_slots:
        return []

    facing_map = get_facing_details(shelf)

    for pid, detail in facing_map.items():
        if pid in oos:
            continue

        if not facing_excess(shelf, pid):
            continue

        product_units = [
            x for x in units if x["product_id"] == pid
        ]

        if not product_units:
            continue

        # Move only the last facing of the product, preserving at least its
        # expected facings.
        source = product_units[-1]

        for destination in free_slots:
            simulated = deepcopy(units)

            source_index = next(
                (i for i, x in enumerate(simulated)
                 if x["slot"] == source["slot"]),
                None,
            )

            if source_index is None:
                continue

            unit = simulated.pop(source_index)
            unit["slot"] = destination

            # Keep the remaining slot identities sorted. We do not invent
            # additional capacity.
            simulated.sort(key=lambda x: x["slot"])

            quality = score_rearrangement(
                units,
                simulated,
                shelf,
            )

            if quality["inversion_improvement"] <= 0:
                continue

            candidates.append({
                "action_type": "MOVE_EXCESS_FACING",
                "shelf_number": shelf.get("shelf_number"),
                "product_id": pid,
                "product_name": source["product_name"],
                "from_slot": source["slot"],
                "to_slot": destination,
                "reason": (
                    "Move one proven excess facing into a physically free "
                    "slot to improve preferred ordering."
                ),
                "quality": quality,
                "confidence": (
                    "high"
                    if quality["sequence_rank_data_available"]
                    else "low"
                ),
                "requires_human_confirmation": True,
            })

    candidates.sort(
        key=lambda x: x["quality"]["inversion_improvement"],
        reverse=True,
    )

    return candidates


# ---------------------------------------------------------------------
# Missing-product diagnosis
# ---------------------------------------------------------------------

def diagnose_missing(
    shelf: Dict[str, Any],
    missing: Dict[str, Any],
) -> Dict[str, Any]:

    product_id = missing.get("product_id")
    product_name = missing.get("product_name")
    expected_slot = safe_int(missing.get("expected_slot"))

    destination_id = missing.get("destination_occupant")
    destination_name = missing.get("destination_occupant_name")

    if product_id in get_oos_ids(shelf):
        return {
            "product_id": product_id,
            "product_name": product_name,
            "decision": "BLOCKED_OOS",
            "safe_action": False,
            "reasons": [
                "product_is_out_of_stock",
                "oos_products_are_excluded_from_correction",
            ],
        }

    checks = []

    if destination_id:
        checks.append({
            "check": "destination",
            "status": "occupied",
            "product_id": destination_id,
            "product_name": destination_name,
            "slot": expected_slot,
        })

        if facing_excess(shelf, destination_id):
            checks.append({
                "check": "destination_facing",
                "status": "excess_available",
            })

            return {
                "product_id": product_id,
                "product_name": product_name,
                "decision": "ACTION_RECOMMENDED",
                "safe_action": True,
                "checks": checks,
                "action": {
                    "type": "reduce_excess_facing_and_place",
                    "remove_product_id": destination_id,
                    "remove_product_name": destination_name,
                    "target_product_id": product_id,
                    "target_product_name": product_name,
                    "target_slot": expected_slot,
                },
            }

        checks.append({
            "check": "destination_facing",
            "status": "no_excess_available",
        })

    free_slots = proven_free_slots(shelf)

    if free_slots:
        checks.append({
            "check": "physical_capacity",
            "status": "free_slot_proven",
            "free_slots": free_slots,
        })

        return {
            "product_id": product_id,
            "product_name": product_name,
            "decision": "ACTION_RECOMMENDED",
            "safe_action": True,
            "checks": checks,
            "action": {
                "type": "add_product_to_free_slot",
                "product_id": product_id,
                "product_name": product_name,
                "preferred_slot": expected_slot,
                "available_slot": free_slots[0],
            },
        }

    checks.append({
        "check": "physical_capacity",
        "status": "not_proven",
    })

    reasons = []

    if destination_id:
        reasons.append(
            "destination_occupant_has_no_excess_facing"
        )

    reasons.append(
        "physical_space_not_proven"
    )

    return {
        "product_id": product_id,
        "product_name": product_name,
        "decision": "REVIEW_NO_SAFE_ACTION",
        "safe_action": False,
        "checks": checks,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------
# MAIN ENGINE
# ---------------------------------------------------------------------

def run_engine(
    analysis: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    shelf_results = []
    candidates = []
    blocked = []

    for shelf in analysis.get("shelves", []):

        missing_results = []

        for missing in (
            (shelf.get("missing_products") or {}).get("details") or []
        ):
            diagnosis = diagnose_missing(
                shelf,
                missing,
            )

            missing_results.append(diagnosis)

            if diagnosis.get("safe_action"):
                candidates.append({
                    "shelf_number": shelf.get("shelf_number"),
                    "source": "missing_product",
                    **diagnosis,
                })
            elif diagnosis.get("decision") == "REVIEW_NO_SAFE_ACTION":
                blocked.append({
                    "shelf_number": shelf.get("shelf_number"),
                    **diagnosis,
                })

        rearrangements = generate_rearrangement_candidates(
            shelf
        )

        candidates.extend(
            {
                "shelf_number": shelf.get("shelf_number"),
                "source": "rearrangement",
                **candidate,
            }
            for candidate in rearrangements
        )

        shelf_results.append({
            "shelf_number": shelf.get("shelf_number"),
            "shelf_name": shelf.get("shelf_name"),
            "physical_occupied_slots": occupied_slots(shelf),
            "proven_free_slots": proven_free_slots(shelf),
            "missing_diagnostics": missing_results,
            "rearrangement_candidates": rearrangements,
        })

    # Prefer direct missing-product corrections over pure soft-order moves.
    candidates.sort(
        key=lambda x: (
            0 if x.get("source") == "missing_product" else 1,
            -(
                x.get("quality", {})
                .get("inversion_improvement", 0)
            ),
        )
    )

    if candidates:
        decision = "ACTION_RECOMMENDED"
        primary = candidates[0]
    else:
        decision = "REVIEW"
        primary = None

    return {
        "engine_version": ENGINE_VERSION,
        "analyzer_version": analysis.get("analyzer_version"),
        "rack_id": analysis.get("rack_id"),

        "principles": {
            "shelf_analyzer_frozen": True,
            "never_correct_oos": True,
            "never_remove_required_facing": True,
            "never_assume_capacity": True,
            "never_create_physical_space": True,
            "hard_constraints_dominate_soft_preferences": True,
            "unknown_colour_sequence_is_not_optimized_as_exact": True,
            "rearrangement_is_simulated_before_recommendation": True,
        },

        "summary": {
            "shelves_analyzed": len(
                analysis.get("shelves", [])
            ),
            "candidates_generated": len(candidates),
            "blocked_corrections": len(blocked),
            "decision": decision,
        },

        "primary_recommendation": primary,

        "candidates": candidates,

        "blocked_corrections": blocked,

        "shelves": shelf_results,
    }


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Smart Planogram conservative correction and "
            "rearrangement engine."
        )
    )

    parser.add_argument(
        "analysis",
        type=Path,
        help="Analysis JSON produced by shelf_analyzer.py",
    )

    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("data/merchandising_rules_v2.json"),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )

    args = parser.parse_args()

    if not args.analysis.exists():
        raise FileNotFoundError(
            f"Analysis file not found: {args.analysis}"
        )

    analysis = load_json(args.analysis)

    rules = None

    if args.rules.exists():
        rules = load_json(args.rules)

    result = run_engine(
        analysis,
        rules,
    )

    output = args.output

    if output is None:
        output = (
            args.analysis.parent
            / f"corrections_{args.analysis.name}"
        )

    save_json(
        result,
        output,
    )

    print()
    print("=" * 72)
    print("SMART PLANOGRAM — CORRECTION ENGINE v1.2")
    print("=" * 72)

    print(
        f"Rack: {result.get('rack_id')}"
    )

    print(
        f"Candidates generated : "
        f"{result['summary']['candidates_generated']}"
    )

    print(
        f"Blocked corrections  : "
        f"{result['summary']['blocked_corrections']}"
    )

    print(
        f"Decision              : "
        f"{result['summary']['decision']}"
    )

    print("-" * 72)

    primary = result.get(
        "primary_recommendation"
    )

    if primary:

        print(
            "RECOMMENDATION: ACTIONABLE CORRECTION"
        )

        if primary.get("source") == "missing_product":

            action = primary.get("action", {})

            print(
                f"Shelf {primary['shelf_number']}: "
                f"{action.get('type')}"
            )

            print(
                json.dumps(
                    action,
                    indent=2,
                    ensure_ascii=False,
                )
            )

        else:

            print(
                f"Shelf {primary['shelf_number']}: "
                f"{primary.get('action_type')}"
            )

            print(
                f"Move: {primary.get('product_name')}"
            )

            print(
                f"Slot {primary.get('from_slot')} "
                f"→ slot {primary.get('to_slot')}"
            )

            quality = primary.get(
                "quality",
                {},
            )

            print(
                "Preferred-order inversion improvement: "
                f"{quality.get('inversion_improvement', 0)}"
            )

            print(
                f"Confidence: "
                f"{primary.get('confidence')}"
            )

    else:

        print(
            "RECOMMENDATION: REVIEW / NO SAFE ACTION"
        )

        for blocked_item in result.get(
            "blocked_corrections",
            [],
        ):

            print()

            print(
                f"Shelf {blocked_item.get('shelf_number')} — "
                f"{blocked_item.get('product_name')}"
            )

            for reason in blocked_item.get(
                "reasons",
                [],
            ):

                if reason == (
                    "destination_occupant_has_no_excess_facing"
                ):
                    print(
                        "  - Destination occupant has no "
                        "excess facing."
                    )

                elif reason == (
                    "physical_space_not_proven"
                ):
                    print(
                        "  - Physical space is not proven."
                    )

                else:
                    print(
                        f"  - {reason}"
                    )

    print()
    print(
        f"Correction analysis written to: "
        f"{output}"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
