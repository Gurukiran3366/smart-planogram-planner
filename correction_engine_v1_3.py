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

ENGINE_VERSION = "1.3"


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
# SHELF-WIDE REARRANGEMENT v1.3
# ---------------------------------------------------------------------

def product_attributes(shelf: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for item in get_colour_details(shelf):
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue
        result[pid] = {
            "product_id": pid,
            "product_name": item.get("product_name", pid),
            "colour": item.get("colour"),
            "brand": item.get("brand"),
            "flavour": item.get("flavour"),
            "price_group": item.get("price_group"),
            "category": item.get("category"),
            "package_type": item.get("package_type"),
        }
    return result


def shelf_unit_groups(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    units = physical_units(shelf)
    if not units:
        return []

    groups = []
    for unit in units:
        if groups and groups[-1]["product_id"] == unit["product_id"]:
            groups[-1]["slots"].append(unit["slot"])
        else:
            groups.append({
                "product_id": unit["product_id"],
                "product_name": unit["product_name"],
                "slots": [unit["slot"]],
            })
    return groups


def simulate_group_move(
    shelf: Dict[str, Any],
    source_product_id: str,
    destination_before_product_id: str,
) -> Optional[List[Dict[str, Any]]]:
    units = physical_units(shelf)
    if not units or source_product_id in get_oos_ids(shelf):
        return None

    source_units = [x for x in units if x["product_id"] == source_product_id]
    remaining = [x for x in units if x["product_id"] != source_product_id]

    if not source_units:
        return None

    target_index = next(
        (i for i, x in enumerate(remaining)
         if x["product_id"] == destination_before_product_id),
        None,
    )
    if target_index is None:
        return None

    simulated = (
        remaining[:target_index]
        + deepcopy(source_units)
        + remaining[target_index:]
    )

    for slot, unit in enumerate(simulated, start=1):
        unit["slot"] = slot

    return simulated


def grouping_score(
    shelf: Dict[str, Any],
    units: List[Dict[str, Any]],
) -> int:
    attrs = product_attributes(shelf)
    ordered = sorted(units, key=lambda x: x["slot"])
    score = 0

    for left, right in zip(ordered, ordered[1:]):
        a = attrs.get(left["product_id"], {})
        b = attrs.get(right["product_id"], {})

        for key in ("flavour", "brand", "category"):
            av = norm(a.get(key))
            bv = norm(b.get(key))
            if av and bv and av == bv:
                score += 1
                break

    return score


def shelf_quality(
    shelf: Dict[str, Any],
    units: List[Dict[str, Any]],
) -> Dict[str, Any]:
    rank_map = preferred_rank_map(shelf)
    before_units = physical_units(shelf)

    before_inversions = order_inversions(before_units, rank_map)
    after_inversions = order_inversions(units, rank_map)

    before_grouping = grouping_score(shelf, before_units)
    after_grouping = grouping_score(shelf, units)

    return {
        "preferred_order_inversions_before": before_inversions,
        "preferred_order_inversions_after": after_inversions,
        "preferred_order_improvement": before_inversions - after_inversions,
        "grouping_score_before": before_grouping,
        "grouping_score_after": after_grouping,
        "grouping_improvement": after_grouping - before_grouping,
        "sequence_rank_data_available": bool(rank_map),
    }


def hard_shelf_integrity_check(
    shelf: Dict[str, Any],
    before: List[Dict[str, Any]],
    after: List[Dict[str, Any]],
) -> Dict[str, Any]:
    before_counts: Dict[str, int] = {}
    after_counts: Dict[str, int] = {}

    for unit in before:
        before_counts[unit["product_id"]] = before_counts.get(unit["product_id"], 0) + 1
    for unit in after:
        after_counts[unit["product_id"]] = after_counts.get(unit["product_id"], 0) + 1

    if before_counts != after_counts:
        return {"feasible": False, "reason": "product_facing_counts_changed"}

    oos = get_oos_ids(shelf)
    for pid in oos:
        before_oos = [x["slot"] for x in before if x["product_id"] == pid]
        after_oos = [x["slot"] for x in after if x["product_id"] == pid]
        if before_oos != after_oos:
            return {
                "feasible": False,
                "reason": "oos_product_was_moved",
                "product_id": pid,
            }

    return {"feasible": True, "reason": "all_hard_integrity_checks_passed"}


def generate_shelf_rearrangement_candidates(
    shelf: Dict[str, Any],
) -> List[Dict[str, Any]]:
    before = physical_units(shelf)
    groups = shelf_unit_groups(shelf)

    if len(groups) < 2:
        return []

    candidates = []

    for group in groups:
        source_pid = group["product_id"]

        if source_pid in get_oos_ids(shelf):
            continue

        for destination_group in groups:
            destination_pid = destination_group["product_id"]

            if destination_pid == source_pid:
                continue

            simulated = simulate_group_move(
                shelf,
                source_pid,
                destination_pid,
            )
            if not simulated:
                continue

            integrity = hard_shelf_integrity_check(
                shelf,
                before,
                simulated,
            )
            if not integrity["feasible"]:
                continue

            quality = shelf_quality(shelf, simulated)

            order_gain = quality["preferred_order_improvement"]
            grouping_gain = quality["grouping_improvement"]

            # We need measurable improvement. If colour/preferred-rank data
            # is unavailable, we do not invent a sequence improvement.
            if order_gain <= 0 and grouping_gain <= 0:
                continue

            if quality["sequence_rank_data_available"] and order_gain < 0:
                continue

            if grouping_gain < 0:
                continue

            candidates.append({
                "action_type": "REARRANGE_PRODUCT_GROUP",
                "shelf_number": shelf.get("shelf_number"),
                "product_id": source_pid,
                "product_name": group["product_name"],
                "move_before_product_id": destination_pid,
                "move_before_product_name": destination_group["product_name"],
                "from_slots": group["slots"],
                "simulated_after_slots": [
                    x["slot"] for x in simulated
                    if x["product_id"] == source_pid
                ],
                "reason": (
                    "Move the complete product group to improve the shelf "
                    "without changing total facings or physical capacity."
                ),
                "quality": quality,
                "hard_check": integrity,
                "confidence": (
                    "medium"
                    if quality["sequence_rank_data_available"]
                    else "low"
                ),
                "requires_human_confirmation": True,
            })

    candidates.sort(
        key=lambda x: (
            x["quality"]["preferred_order_improvement"],
            x["quality"]["grouping_improvement"],
        ),
        reverse=True,
    )
    return candidates

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
            diagnosis = diagnose_missing(shelf, missing)
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

        rearrangements = generate_shelf_rearrangement_candidates(shelf)

        for candidate in rearrangements:
            candidates.append({
                "shelf_number": shelf.get("shelf_number"),
                "source": "rearrangement",
                **candidate,
            })

        shelf_results.append({
            "shelf_number": shelf.get("shelf_number"),
            "shelf_name": shelf.get("shelf_name"),
            "physical_occupied_slots": occupied_slots(shelf),
            "proven_free_slots": proven_free_slots(shelf),
            "missing_diagnostics": missing_results,
            "rearrangement_candidates": rearrangements,
        })

    candidates.sort(
        key=lambda x: (
            0 if x.get("source") == "missing_product" else 1,
            -x.get("quality", {}).get("preferred_order_improvement", 0),
            -x.get("quality", {}).get("grouping_improvement", 0),
        )
    )

    primary = candidates[0] if candidates else None

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
            "rearrangement_preserves_total_facings": True,
            "rearrangement_requires_measurable_improvement": True,
        },
        "summary": {
            "shelves_analyzed": len(analysis.get("shelves", [])),
            "candidates_generated": len(candidates),
            "blocked_corrections": len(blocked),
            "rearrangement_candidates": sum(
                1 for x in candidates if x.get("source") == "rearrangement"
            ),
            "decision": "ACTION_RECOMMENDED" if primary else "REVIEW",
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
        description="Smart Planogram conservative correction and rearrangement engine."
    )
    parser.add_argument("analysis", type=Path)
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("data/merchandising_rules_v2.json"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.analysis.exists():
        raise FileNotFoundError(f"Analysis file not found: {args.analysis}")

    analysis = load_json(args.analysis)
    rules = load_json(args.rules) if args.rules.exists() else None
    result = run_engine(analysis, rules)

    output = args.output or (
        args.analysis.parent / f"corrections_{args.analysis.name}"
    )
    save_json(result, output)

    print()
    print("=" * 72)
    print("SMART PLANOGRAM — CORRECTION ENGINE v1.3")
    print("=" * 72)
    print(f"Rack: {result.get('rack_id')}")
    print(f"Candidates generated : {result['summary']['candidates_generated']}")
    print(f"Blocked corrections  : {result['summary']['blocked_corrections']}")
    print(f"Rearrangement candidates: {result['summary']['rearrangement_candidates']}")
    print(f"Decision              : {result['summary']['decision']}")
    print("-" * 72)

    primary = result.get("primary_recommendation")

    if not primary:
        print("RECOMMENDATION: REVIEW / NO SAFE ACTION")
        for item in result.get("blocked_corrections", []):
            print()
            print(
                f"Shelf {item.get('shelf_number')} — "
                f"{item.get('product_name')}"
            )
            for reason in item.get("reasons", []):
                if reason == "destination_occupant_has_no_excess_facing":
                    print("  - Destination occupant has no excess facing.")
                elif reason == "physical_space_not_proven":
                    print("  - Physical space is not proven.")
                else:
                    print(f"  - {reason}")
    elif primary.get("source") == "missing_product":
        print("RECOMMENDATION: ACTIONABLE CORRECTION")
        print(f"Shelf {primary['shelf_number']}:")
        print(json.dumps(primary.get("action", {}), indent=2, ensure_ascii=False))
    else:
        print("RECOMMENDATION: SHELF-WIDE REARRANGEMENT")
        print(f"Shelf {primary['shelf_number']}")
        print(f"Move: {primary.get('product_name')}")
        print(f"Move before: {primary.get('move_before_product_name')}")
        print(f"Current slots: {primary.get('from_slots')}")
        print(f"Simulated slots: {primary.get('simulated_after_slots')}")

        quality = primary.get("quality", {})
        print(
            "Preferred-order improvement: "
            f"{quality.get('preferred_order_improvement', 0)}"
        )
        print(
            "Grouping improvement: "
            f"{quality.get('grouping_improvement', 0)}"
        )
        print(f"Confidence: {primary.get('confidence')}")
        print("HUMAN CONFIRMATION: required")

    print()
    print(f"Correction analysis written to: {output}")
    print("=" * 72)


if __name__ == "__main__":
    main()
