#!/usr/bin/env python3
"""
SMART PLANOGRAM — PHYSICAL ACTION PLANNER v2

Converts upstream detection/correction/rearrangement reports into
staff-facing physical instructions.

Important:
- REMOVE_EXTRA: only from a proven extra occurrence.
- SWAP: only from a proven direct two-product swap.
- MOVE: only when an upstream report explicitly proves an empty target.
- REARRANGE: only when an upstream report exposes a proven sequence.
- REVIEW: everything else.

v2 fixes:
1. Supports the occurrence_resolver schemas that store extra occurrences
   in separate lists and use current/expected/correct/extra location fields.
2. Extracts shelf/slot information from nested occurrence structures.
3. Prevents "Unknown location" when valid location data exists upstream.
4. Produces a plain string decision, not a one-element tuple.
5. Keeps the safety boundary conservative.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def first(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def product_id_of(item: dict[str, Any]) -> str | None:
    return first(
        item.get("product_id"),
        item.get("id"),
        item.get("sku"),
    )


def product_name_of(item: dict[str, Any]) -> str:
    return str(first(
        item.get("product_name"),
        item.get("name"),
        item.get("product_id"),
        item.get("id"),
        "Unknown product",
    ))


def as_int_or_original(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def normalize_slots(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [as_int_or_original(x) for x in value]
    return [as_int_or_original(value)]


def location_from_dict(item: Any) -> tuple[Any, list[Any] | None]:
    """
    Extract shelf/slots from a variety of upstream schemas.

    Supported examples:
      {"shelf": 1, "slots": [2]}
      {"current_shelf": 1, "current_slots": [2]}
      {"shelf_id": 1, "slot": 2}
      {"location": {"shelf": 1, "slots": [2]}}
    """
    if not isinstance(item, dict):
        return None, None

    # Direct fields.
    shelf = first(
        item.get("shelf"),
        item.get("shelf_number"),
        item.get("shelf_id"),
    )
    slots = first(
        item.get("slots"),
        item.get("slot"),
        item.get("slot_number"),
    )

    if shelf is not None or slots is not None:
        return as_int_or_original(shelf), normalize_slots(slots)

    # Common nested location.
    for key in ("location", "current", "occurrence", "position"):
        nested = item.get(key)
        if isinstance(nested, dict):
            nshelf, nslots = location_from_dict(nested)
            if nshelf is not None or nslots is not None:
                return nshelf, nslots

    return None, None


def extract_location(item: Any, kind: str = "current") -> tuple[Any, list[Any] | None]:
    """
    Extract a location while respecting a requested semantic:
    current / expected / correct / extra / target.

    This intentionally checks semantic-specific fields first.
    """
    if not isinstance(item, dict):
        return None, None

    if kind == "current":
        pairs = (
            ("current_shelf", "current_slots"),
            ("actual_shelf", "actual_slots"),
            ("observed_shelf", "observed_slots"),
        )
    elif kind in ("expected", "target"):
        pairs = (
            ("expected_shelf", "expected_slots"),
            ("target_shelf", "target_slots"),
        )
    elif kind == "correct":
        pairs = (
            ("correct_shelf", "correct_slots"),
            ("expected_shelf", "expected_slots"),
        )
    elif kind == "extra":
        pairs = (
            ("extra_shelf", "extra_slots"),
            ("current_shelf", "current_slots"),
            ("actual_shelf", "actual_slots"),
        )
    else:
        pairs = ()

    for shelf_key, slots_key in pairs:
        if shelf_key in item or slots_key in item:
            return (
                as_int_or_original(item.get(shelf_key)),
                normalize_slots(item.get(slots_key)),
            )

    return location_from_dict(item)


def location_text(shelf: Any, slots: list[Any] | None) -> str:
    if shelf is None and not slots:
        return "Unknown location"
    if shelf is None:
        return "Slot " + ", ".join(str(x) for x in slots)
    if not slots:
        return f"Shelf {shelf}"
    return f"Shelf {shelf} • Slot {', '.join(str(x) for x in slots)}"


def occurrence_key(item: dict[str, Any]) -> str:
    return str(first(
        product_id_of(item),
        product_name_of(item),
        "",
    )).strip().lower()


def find_product_container(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            return value
    return None


def make_remove_action(item: dict[str, Any]) -> dict[str, Any]:
    product_id = product_id_of(item)
    product = product_name_of(item)

    # Occurrence resolver can expose the locations in nested objects.
    correct_obj = find_product_container(
        item,
        ("correct", "correct_occurrence", "expected_occurrence"),
    ) or {}
    extra_obj = find_product_container(
        item,
        ("extra", "extra_occurrence"),
    ) or {}

    # Prefer semantic fields on nested objects, then on the parent.
    correct_shelf, correct_slots = extract_location(correct_obj, "correct")
    if correct_shelf is None and correct_slots is None:
        correct_shelf, correct_slots = extract_location(item, "correct")
    if correct_shelf is None and correct_slots is None:
        correct_shelf, correct_slots = extract_location(item, "expected")

    extra_shelf, extra_slots = extract_location(extra_obj, "extra")
    if extra_shelf is None and extra_slots is None:
        extra_shelf, extra_slots = extract_location(item, "extra")
    if extra_shelf is None and extra_slots is None:
        extra_shelf, extra_slots = extract_location(item, "current")

    correct_location = location_text(correct_shelf, correct_slots)
    extra_location = location_text(extra_shelf, extra_slots)

    # Do not call a removal SAFE if we cannot identify where the extra unit is.
    safe = extra_shelf is not None or bool(extra_slots)
    status = "SAFE" if safe else "REVIEW"

    action = {
        "action_type": "REMOVE_EXTRA" if safe else "REVIEW",
        "status": status,
        "priority": "HIGH" if safe else "MEDIUM",
        "product_id": product_id,
        "product_name": product,
        "from": {
            "shelf": extra_shelf,
            "slots": extra_slots,
        },
        "keep": {
            "shelf": correct_shelf,
            "slots": correct_slots,
        },
        "destination": "DESIGNATED_BACKSTOCK" if safe else None,
        "instruction": (
            f"Remove the extra {product} from {extra_location}. "
            f"Keep the correct {product} already at {correct_location}. "
            "Do not place the extra unit into the occupied correct slot; "
            "move it to the store's designated backstock/return area."
            if safe
            else
            f"Manually verify the extra {product} occurrence before moving it. "
            "The upstream report did not provide a reliable physical location."
        ),
        "evidence": [
            "Occurrence resolver identified an extra occurrence.",
            "A separate correct occurrence was identified."
            if correct_shelf is not None or correct_slots
            else "Correct occurrence location was not available in the report.",
        ],
    }

    if not safe:
        action["reason"] = "Extra occurrence location could not be resolved from the upstream report."

    return action


def make_swap_action(swap: dict[str, Any]) -> dict[str, Any] | None:
    products = swap.get("products") or []
    if len(products) != 2:
        return None

    a, b = products[0], products[1]
    a_name = product_name_of(a)
    b_name = product_name_of(b)

    a_cs, a_ct = extract_location(a, "current")
    a_ts, a_tt = extract_location(a, "target")
    b_cs, b_ct = extract_location(b, "current")
    b_ts, b_tt = extract_location(b, "target")

    a_from = location_text(a_cs, a_ct)
    a_to = location_text(a_ts, a_tt)
    b_from = location_text(b_cs, b_ct)
    b_to = location_text(b_ts, b_tt)

    # A direct swap must have all four physical endpoints.
    if "Unknown location" in (a_from, a_to, b_from, b_to):
        return None

    return {
        "action_type": "SWAP",
        "status": "SAFE",
        "priority": "HIGH",
        "products": [
            {
                "product_id": product_id_of(a),
                "product_name": a_name,
                "from": a_from,
                "to": a_to,
            },
            {
                "product_id": product_id_of(b),
                "product_name": b_name,
                "from": b_from,
                "to": b_to,
            },
        ],
        "instruction": (
            f"Swap {a_name} at {a_from} with {b_name} at {b_from}. "
            f"After the swap, place {a_name} at {a_to} and "
            f"{b_name} at {b_to}."
        ),
        "steps": [
            f"Remove {a_name} from {a_from}.",
            f"Remove {b_name} from {b_from}.",
            f"Place {a_name} at {a_to}.",
            f"Place {b_name} at {b_to}.",
        ],
        "evidence": swap.get("evidence", []),
    }


def make_move_action(item: dict[str, Any]) -> dict[str, Any] | None:
    if str(item.get("status", "")).upper() not in {"FEASIBLE", "SAFE"}:
        return None
    if not item.get("destination_empty", False):
        return None

    product = product_name_of(item)
    cs, ct = extract_location(item, "current")
    ts, tt = extract_location(item, "target")

    current = location_text(cs, ct)
    target = location_text(ts, tt)

    if "Unknown location" in (current, target):
        return None

    return {
        "action_type": "MOVE",
        "status": "SAFE",
        "priority": "HIGH",
        "product_id": product_id_of(item),
        "product_name": product,
        "from": current,
        "to": target,
        "instruction": f"Move {product} from {current} to {target}.",
        "evidence": item.get("evidence", []),
    }


def make_rearrange_action(cycle: dict[str, Any]) -> dict[str, Any] | None:
    if str(cycle.get("status", "")).upper() not in {"FEASIBLE", "SAFE"}:
        return None

    sequence = cycle.get("steps") or cycle.get("sequence") or cycle.get("actions")
    if not isinstance(sequence, list) or not sequence:
        return None

    return {
        "action_type": "REARRANGE",
        "status": "SAFE",
        "priority": "HIGH",
        "instruction": "Follow the proven rearrangement sequence exactly.",
        "steps": sequence,
        "evidence": cycle.get("evidence", []),
    }


def make_review(
    product_id: str | None,
    product_name: str | None,
    reason: str,
    source: str,
) -> dict[str, Any]:
    name = product_name or product_id or "Unknown product"
    return {
        "action_type": "REVIEW",
        "status": "REVIEW",
        "priority": "MEDIUM",
        "product_id": product_id,
        "product_name": name,
        "instruction": (
            f"Manually verify {name} before moving anything. "
            "Do not change the product until the location is confirmed."
        ),
        "reason": reason,
        "source": source,
    }



def iter_extra_occurrences(report: dict[str, Any]):
    """
    Read the exact occurrence_resolver v1 schema.

    Example:
      {
        "product_id": "...",
        "product_name": "...",
        "status": "CORRECT_OCCURRENCE",
        "correct_occurrence": {"shelf": 3, "slots": [1]},
        "extra_occurrences": [{"shelf": 1, "slots": [2]}]
      }

    The important point is that an extra occurrence is nested inside
    extra_occurrence_cases / resolutions; it is NOT itself labelled
    EXTRA_OCCURRENCE in the `status` field.
    """
    seen = set()

    def emit(parent: dict[str, Any]):
        extras = parent.get("extra_occurrences")
        if not isinstance(extras, list) or not extras:
            return

        # Each extra occurrence gets its own physical action, while the
        # correct occurrence remains the "keep" location.
        for extra in extras:
            if not isinstance(extra, dict):
                continue

            item = {
                "product_id": parent.get("product_id"),
                "product_name": parent.get("product_name"),
                "correct_occurrence": parent.get("correct_occurrence"),
                "expected_occurrence": parent.get("expected_occurrence"),
                "extra_occurrence": extra,
                "type": "EXTRA_OCCURRENCE",
            }

            key = (
                str(parent.get("product_id") or parent.get("product_name") or "").lower(),
                json.dumps(extra, sort_keys=True),
            )
            if key not in seen:
                seen.add(key)
                yield item

    # Exact resolver output.
    for item in report.get("extra_occurrence_cases", []) or []:
        if isinstance(item, dict):
            yield from emit(item)

    # Defensive support if a future resolver puts the same records in
    # resolutions but does not populate extra_occurrence_cases.
    if not report.get("extra_occurrence_cases"):
        for item in report.get("resolutions", []) or []:
            if isinstance(item, dict):
                yield from emit(item)


def iter_ambiguous(report: dict[str, Any]):
    for key in ("ambiguous", "ambiguous_products", "ambiguous_occurrences"):
        value = report.get(key)
        if isinstance(value, list):
            yield from value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Smart Planogram reports into physical staff actions."
    )
    parser.add_argument("--corrections", required=True)
    parser.add_argument("--occurrences", required=True)
    parser.add_argument("--rearrangements", required=True)
    parser.add_argument("--cycles", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    paths = {
        "corrections": Path(args.corrections),
        "occurrences": Path(args.occurrences),
        "rearrangements": Path(args.rearrangements),
        "cycles": Path(args.cycles),
    }

    for label, p in paths.items():
        if not p.exists():
            parser.error(f"{label} file not found: {p}")

    corrections = load_json(paths["corrections"])
    occurrences = load_json(paths["occurrences"])
    rearrangements = load_json(paths["rearrangements"])
    cycles = load_json(paths["cycles"])

    rack = first(
        corrections.get("rack"),
        occurrences.get("rack"),
        rearrangements.get("rack"),
        cycles.get("rack"),
        "UNKNOWN",
    )

    actions: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    handled_products: set[str] = set()

    # 1. EXTRA OCCURRENCES -> REMOVE_EXTRA.
    for item in iter_extra_occurrences(occurrences):
        key = occurrence_key(item)
        if key in handled_products:
            continue

        action = make_remove_action(item)
        if action["status"] == "SAFE":
            actions.append(action)
        else:
            reviews.append({
                "action_type": "REVIEW",
                "status": "REVIEW",
                "priority": "MEDIUM",
                "product_id": product_id_of(item),
                "product_name": product_name_of(item),
                "instruction": action["instruction"],
                "reason": action["reason"],
                "source": "occurrence_resolver",
            })
        handled_products.add(key)

    # 2. Proven direct swaps -> SWAP.
    for swap in rearrangements.get("safe_rearrangements", []) or []:
        if str(swap.get("type", "")).upper() != "DIRECT_SWAP":
            continue

        action = make_swap_action(swap)
        if action is None:
            continue

        actions.append(action)
        for p in swap.get("products", []):
            handled_products.add(occurrence_key(p))

    # 3. Explicitly proven empty-destination moves.
    for collection_name in ("feasible_candidates", "safe_actions"):
        for item in corrections.get(collection_name, []) or []:
            action = make_move_action(item)
            if action is None:
                continue

            key = occurrence_key(item)
            if key not in handled_products:
                actions.append(action)
                handled_products.add(key)

    # 4. Proven cycle.
    for cycle in cycles.get("safe_cycles", []) or []:
        action = make_rearrange_action(cycle)
        if action is not None:
            actions.append(action)

    # 5. Ambiguous occurrences.
    for item in iter_ambiguous(occurrences):
        if not isinstance(item, dict):
            continue

        pid = product_id_of(item)
        name = product_name_of(item)
        key = str(first(pid, name, "")).lower()

        if key in handled_products:
            continue

        reviews.append(make_review(
            pid,
            name,
            str(first(
                item.get("reason"),
                "Product occurrence could not be uniquely resolved.",
            )),
            "occurrence_resolver",
        ))
        handled_products.add(key)

    # 6. Unresolved rearrangements.
    for item in rearrangements.get("unresolved_rearrangements", []) or []:
        pid = product_id_of(item)
        name = product_name_of(item)
        key = str(first(pid, name, "")).lower()

        if key in handled_products:
            continue

        reviews.append(make_review(
            pid,
            name,
            str(first(
                item.get("reason"),
                "No safe physical rearrangement was proven.",
            )),
            "rearrangement_planner",
        ))
        handled_products.add(key)

    # 7. Unresolved cycle products.
    for item in cycles.get("unresolved_products", []) or []:
        if isinstance(item, dict):
            pid = product_id_of(item)
            name = product_name_of(item)
            reason = str(first(item.get("reason"), "No safe cycle was proven."))
        else:
            pid = str(item)
            name = str(item)
            reason = "No safe cycle was proven."

        key = str(first(pid, name, "")).lower()
        if key in handled_products:
            continue

        reviews.append(make_review(pid, name, reason, "cycle_planner"))
        handled_products.add(key)

    # 8. Blocked corrections.
    blocked = corrections.get("blocked_candidates") or corrections.get("blocked_corrections") or []
    for item in blocked:
        pid = product_id_of(item)
        name = product_name_of(item)
        key = str(first(pid, name, "")).lower()

        if key in handled_products:
            continue

        reviews.append(make_review(
            pid,
            name,
            str(first(
                item.get("reason"),
                "Safe physical correction could not be proven.",
            )),
            "correction_engine",
        ))
        handled_products.add(key)

    # Deduplicate safe actions.
    deduped = []
    seen_actions = set()

    for action in actions:
        if action["action_type"] == "SWAP":
            ids = tuple(sorted(
                str(x.get("product_id") or x.get("product_name"))
                for x in action["products"]
            ))
            key = ("SWAP", ids)
        else:
            key = (
                action["action_type"],
                str(action.get("product_id") or action.get("product_name")),
                str(action.get("from")),
                str(action.get("to")),
            )

        if key not in seen_actions:
            seen_actions.add(key)
            deduped.append(action)

    actions = deduped

    if args.output:
        output = Path(args.output)
    else:
        output = paths["corrections"].parent / (
            f"physical_actions_{paths['corrections'].stem}.json"
        )

    summary = {
        "safe_actions": len(actions),
        "remove_extra": sum(x["action_type"] == "REMOVE_EXTRA" for x in actions),
        "moves": sum(x["action_type"] == "MOVE" for x in actions),
        "swaps": sum(x["action_type"] == "SWAP" for x in actions),
        "rearrangements": sum(x["action_type"] == "REARRANGE" for x in actions),
        "review_required": len(reviews),
    }

    decision = (
        "ACTION_RECOMMENDED"
        if actions
        else "REVIEW_REQUIRED"
        if reviews
        else "NO_ACTION"
    )

    report = {
        "engine": "physical_action_planner",
        "engine_version": "2.0",
        "rack": rack,
        "sources": {k: str(v) for k, v in paths.items()},
        "summary": summary,
        "decision": decision,
        "safe_actions": actions,
        "review_required": reviews,
        "safety_boundary": (
            "Only actions explicitly proven by upstream structured reports "
            "are converted into SAFE physical instructions. Unknown "
            "destinations, ambiguous occurrences, occupied targets without "
            "a proven reciprocal swap, and unproven longer rearrangements "
            "remain REVIEW."
        ),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("=" * 76)
    print("SMART PLANOGRAM — PHYSICAL ACTION PLANNER v2")
    print("=" * 76)
    print(f"Rack: {rack}")
    print()
    print(f"Safe actions       : {len(actions)}")
    print(f"  Remove extra     : {summary['remove_extra']}")
    print(f"  Move             : {summary['moves']}")
    print(f"  Swap             : {summary['swaps']}")
    print(f"  Rearrange        : {summary['rearrangements']}")
    print(f"Review required    : {summary['review_required']}")
    print(f"Decision           : {decision}")
    print("-" * 76)

    if actions:
        print("SAFE PHYSICAL ACTIONS")
        for i, action in enumerate(actions, 1):
            print(f"\n{i}. [{action['action_type']}]")
            print(f"   {action['instruction']}")
            for step in action.get("steps", []):
                print(f"   - {step}")

    if reviews:
        print("\nREVIEW REQUIRED")
        for i, review in enumerate(reviews, 1):
            print(f"\n{i}. {review['product_name']}")
            print(f"   {review['instruction']}")
            print(f"   Reason: {review['reason']}")

    print()
    print(f"Physical action report written to: {output}")
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
