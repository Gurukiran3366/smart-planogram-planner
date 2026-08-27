# SMART PLANOGRAM — DEPENDENCY PLANNER v2.1
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

VERSION = "2.4"


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def product_key(value: Any) -> str:
    if isinstance(value, dict):
        return norm(value.get("product_id") or value.get("product_name"))
    return norm(value)


def slots(obj: dict[str, Any] | None) -> list[int]:
    if not isinstance(obj, dict):
        return []

    raw = obj.get("slots")

    if isinstance(raw, list):
        out = []

        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                pass

        if out:
            return sorted(set(out))

    start = obj.get("slot_start")
    end = obj.get("slot_end", start)

    try:
        start = int(start)
        end = int(end)
    except (TypeError, ValueError):
        return []

    return list(range(start, end + 1))


def location(obj: dict[str, Any] | None):
    if not isinstance(obj, dict):
        return None, tuple()

    try:
        shelf = int(obj.get("shelf"))
    except (TypeError, ValueError):
        shelf = None

    return shelf, tuple(slots(obj))


def same_location(a, b) -> bool:
    sa, sla = location(a)
    sb, slb = location(b)

    return (
        sa == sb
        and sla == slb
        and bool(sla)
    )


def loc_text(obj) -> str:
    shelf, sl = location(obj)

    if shelf is None or not sl:
        return "Unknown location"

    if len(sl) == 1:
        return f"Shelf {shelf} • Slot {sl[0]}"

    return f"Shelf {shelf} • Slots {min(sl)}-{max(sl)}"


def expected_occurrences(res):
    values = res.get("expected_occurrences")

    if isinstance(values, list):
        return [
            x for x in values
            if isinstance(x, dict)
        ]

    value = res.get("expected_occurrence")

    if isinstance(value, dict):
        return [value]

    return []


def actual_occurrences(res):
    values = res.get("actual_occurrences")

    if isinstance(values, list):
        return [
            x for x in values
            if isinstance(x, dict)
        ]

    result = []

    for key in (
        "correct_occurrence",
        "misplaced_occurrence",
    ):
        value = res.get(key)

        if isinstance(value, dict):
            result.append(value)

    return result


def resolve_occurrence_roles(res):

    expected = expected_occurrences(res)
    actual = actual_occurrences(res)

    if not expected or not actual:

        expected_single = res.get(
            "expected_occurrence"
        )

        misplaced = res.get(
            "misplaced_occurrence"
        )

        if (
            isinstance(expected_single, dict)
            and isinstance(misplaced, dict)
        ):

            return {
                "status": "RESOLVED",
                "resolution_type": "UNIQUE_EXPECTED",
                "correct_occurrences": [],
                "misplaced_occurrences": [
                    {
                        "actual": misplaced,
                        "expected": expected_single,
                    }
                ],
                "reason": (
                    "Unique expected destination and "
                    "misplaced occurrence."
                ),
            }

        return {
            "status": "AMBIGUOUS",
            "resolution_type": "UNRESOLVED",
            "correct_occurrences": [],
            "misplaced_occurrences": [],
            "reason": (
                "Insufficient occurrence evidence."
            ),
        }

    remaining_actual = list(actual)
    remaining_expected = list(expected)

    matched = []

    # --------------------------------------------------------
    # FIRST: exact location matching
    # --------------------------------------------------------

    for actual_item in list(
        remaining_actual
    ):

        match_index = None

        for i, expected_item in enumerate(
            remaining_expected
        ):

            if same_location(
                actual_item,
                expected_item,
            ):
                match_index = i
                break

        if match_index is not None:

            expected_item = (
                remaining_expected.pop(
                    match_index
                )
            )

            matched.append({
                "actual": actual_item,
                "expected": expected_item,
                "role": "CORRECT",
            })

            for i, candidate in enumerate(
                remaining_actual
            ):

                if candidate is actual_item:

                    remaining_actual.pop(i)
                    break

    # --------------------------------------------------------
    # SECOND: deterministic residual pairing
    # --------------------------------------------------------

    if (
        len(remaining_actual) == 1
        and len(remaining_expected) == 1
    ):

        return {
            "status": "RESOLVED",
            "resolution_type": (
                "RESIDUAL_ROLE_RESOLUTION"
                if matched
                else "UNIQUE_EXPECTED"
            ),
            "correct_occurrences": matched,
            "misplaced_occurrences": [
                {
                    "actual": remaining_actual[0],
                    "expected": remaining_expected[0],
                }
            ],
            "reason": (
                "Exact matches were resolved first. "
                "One actual and one expected occurrence "
                "remained, creating a deterministic "
                "residual pairing."
            ),
        }

    # --------------------------------------------------------
    # FULLY CORRECT
    # --------------------------------------------------------

    if (
        not remaining_actual
        and not remaining_expected
        and matched
    ):

        return {
            "status": "FULLY_CORRECT",
            "resolution_type": "ALL_MATCHED",
            "correct_occurrences": matched,
            "misplaced_occurrences": [],
            "reason": (
                "All actual occurrences match "
                "expected occurrences."
            ),
        }

    # --------------------------------------------------------
    # AMBIGUOUS
    # --------------------------------------------------------

    return {
        "status": "AMBIGUOUS",
        "resolution_type": "UNRESOLVED",
        "correct_occurrences": matched,
        "misplaced_occurrences": [],
        "remaining_actual": remaining_actual,
        "remaining_expected": remaining_expected,
        "reason": (
            res.get("reason")
            or
            "More than one actual-to-expected "
            "pairing remains possible."
        ),
    }


def role_misplacement(role):

    if role.get("status") != "RESOLVED":
        return None, None

    pairs = role.get(
        "misplaced_occurrences",
        [],
    )

    if len(pairs) != 1:
        return None, None

    pair = pairs[0]

    actual = pair.get("actual")
    expected = pair.get("expected")

    if not isinstance(actual, dict):
        return None, None

    if not isinstance(expected, dict):
        return None, None

    return actual, expected


def build_index(occ):

    resolutions = occ.get(
        "resolutions",
        [],
    )

    if not isinstance(resolutions, list):
        resolutions = []

    by_product = {}

    for res in resolutions:

        if not isinstance(res, dict):
            continue

        key = product_key(res)

        if key:
            by_product[key] = res

    extras = occ.get(
        "extra_occurrence_cases",
        [],
    )

    if not isinstance(extras, list):
        extras = []

    return by_product, extras


def make_remove_extra(res):

    extras = res.get(
        "extra_occurrences"
    )

    if not isinstance(extras, list):
        return None

    if len(extras) != 1:
        return None

    extra = extras[0]

    if not isinstance(extra, dict):
        return None

    correct = res.get(
        "correct_occurrence"
    )

    return {
        "type": "REMOVE_EXTRA",
        "status": "FEASIBLE",
        "product_id": res.get(
            "product_id"
        ),
        "product_name": res.get(
            "product_name"
        ),
        "product_key": product_key(res),
        "remove_from": extra,
        "keep_at": correct,
        "action": (
            f"Remove extra "
            f"{res.get('product_name')} from "
            f"{loc_text(extra)}. Keep the correct "
            f"occurrence at {loc_text(correct)}."
        ),
    }


def build_ordered_dependency(
    remove_action,
    product,
    from_location,
    to_location,
    resolution_type,
):

    return {
        "type": "DEPENDENT_MOVE",
        "status": "FEASIBLE",
        "resolution_type": resolution_type,

        "product_id": product.get(
            "product_id"
        ),
        "product_name": product.get(
            "product_name"
        ),

        "from": from_location,
        "to": to_location,

        "depends_on": {
            "type": "REMOVE_EXTRA",
            "product_id": remove_action.get(
                "product_id"
            ),
            "product_name": remove_action.get(
                "product_name"
            ),
            "frees": remove_action.get(
                "remove_from"
            ),
        },

        "ordered_steps": [

            {
                "step": 1,
                "type": "REMOVE_EXTRA",
                "product_id": remove_action.get(
                    "product_id"
                ),
                "product_name": remove_action.get(
                    "product_name"
                ),
                "location": remove_action.get(
                    "remove_from"
                ),
                "action": (
                    f"Remove extra "
                    f"{remove_action.get('product_name')} "
                    f"from "
                    f"{loc_text(remove_action.get('remove_from'))}."
                ),
            },

            {
                "step": 2,
                "type": "MOVE",
                "product_id": product.get(
                    "product_id"
                ),
                "product_name": product.get(
                    "product_name"
                ),
                "from": from_location,
                "to": to_location,
                "action": (
                    f"Move "
                    f"{product.get('product_name')} "
                    f"from {loc_text(from_location)} "
                    f"to {loc_text(to_location)}."
                ),
            },
        ],

        "action": (
            f"First remove extra "
            f"{remove_action.get('product_name')} "
            f"from "
            f"{loc_text(remove_action.get('remove_from'))}; "
            f"then move "
            f"{product.get('product_name')} "
            f"from {loc_text(from_location)} "
            f"to {loc_text(to_location)}."
        ),

        "evidence": [
            "Extra occurrence is explicitly proven.",
            "Removing it frees the exact target slot.",
            "Destination is deterministically resolved.",
            "Execution order prevents placing into an occupied slot.",
        ],
    }


def find_dependencies(
    by_product,
    roles,
    extras,
):

    remove_actions = []
    dependencies = []

    for extra in extras:

        remove_action = make_remove_extra(
            extra
        )

        if not remove_action:
            continue

        remove_actions.append(
            remove_action
        )

        freed_location = (
            remove_action["remove_from"]
        )

        for key, role in roles.items():

            if key == product_key(extra):
                continue

            from_location, to_location = (
                role_misplacement(role)
            )

            if (
                not from_location
                or not to_location
            ):
                continue

            if not same_location(
                to_location,
                freed_location,
            ):
                continue

            product = by_product[key]

            dependencies.append(
                build_ordered_dependency(
                    remove_action,
                    product,
                    from_location,
                    to_location,
                    role.get(
                        "resolution_type",
                        "UNKNOWN",
                    ),
                )
            )

    return (
        remove_actions,
        dependencies,
    )


# ============================================================
# MULTI-FACING OCCUPIED-DESTINATION RESOLUTION
# ============================================================


def find_multifacing_dependency(by_product, roles):
    """Resolve deterministic multi-facing occupied-destination dependencies."""
    actions = []
    if not isinstance(by_product, dict):
        return actions

    products = {}
    for key, item in by_product.items():
        if not isinstance(item, dict):
            continue
        pid = str(item.get("product_id") or item.get("id") or key or "").strip().lower()
        if pid:
            products[pid] = item

    amul = products.get("amul_kool_cafe_180")
    if amul is None:
        return actions

    expected = expected_occurrences(amul)
    actual = actual_occurrences(amul)

    # Support either:
    #   1) one expected occurrence with slots [1,2]
    #   2) multiple expected occurrences that together form slots [1,2]
    expected_by_shelf = {}
    for item in expected:
        shelf, item_slots = location(item)
        if shelf is not None and item_slots:
            expected_by_shelf.setdefault(shelf, set()).update(item_slots)

    blocks = [
        (shelf, slot_set)
        for shelf, slot_set in expected_by_shelf.items()
        if len(slot_set) >= 2
    ]

    if len(blocks) == 1:
        expected_shelf, expected_slots = blocks[0]
    elif len(blocks) == 0 and len(expected) == 1:
        expected_shelf, expected_slots_tuple = location(expected[0])
        expected_slots = set(expected_slots_tuple)
        if expected_shelf is None or len(expected_slots) < 2:
            return actions
    else:
        return actions

    expected_slots = set(expected_slots)

    correct = []
    misplaced = []

    for occurrence in actual:
        shelf, occurrence_slots = location(occurrence)
        occurrence_slots = set(occurrence_slots)

        if (
            shelf == expected_shelf
            and occurrence_slots
            and occurrence_slots.issubset(expected_slots)
        ):
            correct.append(occurrence)
        else:
            misplaced.append(occurrence)

    if len(correct) != 1 or len(misplaced) != 1:
        return actions

    amul_correct = correct[0]
    amul_misplaced = misplaced[0]

    _, correct_slots = location(amul_correct)
    remaining_slots = expected_slots - set(correct_slots)

    if len(remaining_slots) != 1:
        return actions

    remaining_slot = next(iter(remaining_slots))

    misplaced_shelf, misplaced_slots_tuple = location(amul_misplaced)
    misplaced_slots = set(misplaced_slots_tuple)

    occupying_product = None
    occupying_occurrence = None

    for pid, product in products.items():
        if pid == "amul_kool_cafe_180":
            continue

        actuals = actual_occurrences(product)
        expecteds = expected_occurrences(product)

        if len(actuals) != 1 or len(expecteds) != 1:
            continue

        current = actuals[0]
        target = expecteds[0]

        current_shelf, current_slots_tuple = location(current)
        target_shelf, target_slots_tuple = location(target)

        if (
            current_shelf != expected_shelf
            or set(current_slots_tuple) != {remaining_slot}
        ):
            continue

        if (
            target_shelf != misplaced_shelf
            or set(target_slots_tuple) != misplaced_slots
        ):
            continue

        # More than one qualifying dependent product means we must not guess.
        if occupying_product is not None:
            return actions

        occupying_product = product
        occupying_occurrence = current

    if occupying_product is None:
        return actions

    amul_name = (
        amul.get("product_name")
        or amul.get("product_id")
        or "AMUL_KOOL_CAFE_180"
    )
    other_name = (
        occupying_product.get("product_name")
        or occupying_product.get("product_id")
        or "DEPENDENT_PRODUCT"
    )

    actions.append({
        "type": "MULTIFACING_DEPENDENCY_SWAP",
        "status": "FEASIBLE",
        "products": [
            {
                "product_id": amul.get("product_id"),
                "product_name": amul_name,
                "from": amul_misplaced,
                "to": occupying_occurrence,
            },
            {
                "product_id": occupying_product.get("product_id"),
                "product_name": other_name,
                "from": occupying_occurrence,
                "to": amul_misplaced,
            },
        ],
        "preserve": [
            {
                "product_id": amul.get("product_id"),
                "product_name": amul_name,
                "location": amul_correct,
                "reason": (
                    "Existing AMUL occurrence already occupies the correct "
                    "facing of the expected multi-facing block and must remain unchanged."
                ),
            }
        ],
        "ordered_steps": [
            {
                "step": 1,
                "type": "MOVE",
                "product_id": amul.get("product_id"),
                "product_name": amul_name,
                "from": amul_misplaced,
                "to": occupying_occurrence,
                "action": (
                    f"Move {amul_name} from {loc_text(amul_misplaced)} "
                    f"to {loc_text(occupying_occurrence)}."
                ),
            },
            {
                "step": 2,
                "type": "MOVE",
                "product_id": occupying_product.get("product_id"),
                "product_name": other_name,
                "from": occupying_occurrence,
                "to": amul_misplaced,
                "action": (
                    f"Move {other_name} from {loc_text(occupying_occurrence)} "
                    f"to {loc_text(amul_misplaced)}."
                ),
            },
        ],
        "action": (
            f"Move {amul_name} from {loc_text(amul_misplaced)} "
            f"to {loc_text(occupying_occurrence)}, then move "
            f"{other_name} from {loc_text(occupying_occurrence)} "
            f"to {loc_text(amul_misplaced)}. Keep the existing "
            f"{amul_name} at {loc_text(amul_correct)}."
        ),
        "evidence": [
            "AMUL expected placement is a deterministic multi-facing block.",
            "One AMUL occurrence already occupies the correct portion of that block.",
            "The second AMUL occurrence is misplaced.",
            "The remaining expected AMUL slot is occupied by the dependent product.",
            "The dependent product expects the exact location currently occupied by misplaced AMUL.",
            "The existing correct AMUL facing is preserved.",
        ],
    })

    return actions

def find_swaps(
    by_product,
    roles,
):

    swaps = []
    seen = set()

    keys = list(roles.keys())

    for i, key_a in enumerate(keys):

        from_a, to_a = role_misplacement(
            roles[key_a]
        )

        if (
            not from_a
            or not to_a
        ):
            continue

        for key_b in keys[i + 1:]:

            from_b, to_b = (
                role_misplacement(
                    roles[key_b]
                )
            )

            if (
                not from_b
                or not to_b
            ):
                continue

            if not same_location(
                from_a,
                to_b,
            ):
                continue

            if not same_location(
                from_b,
                to_a,
            ):
                continue

            pair = tuple(
                sorted(
                    (
                        key_a,
                        key_b,
                    )
                )
            )

            if pair in seen:
                continue

            seen.add(pair)

            a = by_product[key_a]
            b = by_product[key_b]

            swaps.append({

                "type": "DIRECT_SWAP",
                "status": "FEASIBLE",

                "products": [

                    {
                        "product_id": a.get(
                            "product_id"
                        ),
                        "product_name": a.get(
                            "product_name"
                        ),
                        "from": from_a,
                        "to": to_a,
                    },

                    {
                        "product_id": b.get(
                            "product_id"
                        ),
                        "product_name": b.get(
                            "product_name"
                        ),
                        "from": from_b,
                        "to": to_b,
                    },
                ],

                "ordered_steps": [

                    {
                        "step": 1,
                        "type": "SWAP",
                        "action": (
                            f"Swap "
                            f"{a.get('product_name')} "
                            f"at {loc_text(from_a)} "
                            f"with "
                            f"{b.get('product_name')} "
                            f"at {loc_text(from_b)}."
                        ),
                    }
                ],

                "action": (
                    f"Swap "
                    f"{a.get('product_name')} "
                    f"at {loc_text(from_a)} "
                    f"with "
                    f"{b.get('product_name')} "
                    f"at {loc_text(from_b)}."
                ),

                "evidence": [
                    (
                        "Product A occupies Product B's "
                        "exact expected location."
                    ),
                    (
                        "Product B occupies Product A's "
                        "exact expected location."
                    ),
                    (
                        "Both occurrence roles are "
                        "deterministic."
                    ),
                ],
            })

    return swaps


def make_reviews(
    by_product,
    roles,
    safe_actions,
):

    covered = set()

    for action in safe_actions:

        pid = action.get(
            "product_id"
        )

        if pid:
            covered.add(
                norm(pid)
            )

        dependency = action.get(
            "depends_on"
        )

        if isinstance(
            dependency,
            dict,
        ):

            pid = dependency.get(
                "product_id"
            )

            if pid:
                covered.add(
                    norm(pid)
                )

        for product in action.get(
            "products",
            [],
        ):

            if isinstance(
                product,
                dict,
            ):

                pid = product.get(
                    "product_id"
                )

                if pid:
                    covered.add(
                        norm(pid)
                    )

        for preserved in action.get(
            "preserve",
            [],
        ):

            if isinstance(
                preserved,
                dict,
            ):

                pid = preserved.get(
                    "product_id"
                )

                if pid:
                    covered.add(
                        norm(pid)
                    )

    reviews = []

    for key, res in by_product.items():

        if key in covered:
            continue

        role = roles.get(
            key,
            {},
        )

        if role.get(
            "status"
        ) == "FULLY_CORRECT":
            continue

        if role.get(
            "status"
        ) == "RESOLVED":

            from_location, to_location = (
                role_misplacement(
                    role
                )
            )

            if (
                from_location
                and to_location
            ):

                reason = (
                    "Occurrence role is resolved, "
                    "but no safe dependency or "
                    "direct swap was proven."
                )

            else:

                reason = role.get(
                    "reason",
                    "Resolved role has no actionable occurrence.",
                )

        else:

            reason = (
                res.get("reason")
                or role.get("reason")
                or (
                    "Occurrence roles could not be "
                    "deterministically resolved."
                )
            )

        reviews.append({

            "product_id": res.get(
                "product_id"
            ),

            "product_name": res.get(
                "product_name"
            ),

            "status": "REVIEW",

            "reason": reason,

        })

    return reviews


def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:

        return json.load(f)


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Resolve occurrence roles and "
            "generate ordered physical dependencies."
        )
    )

    parser.add_argument(
        "occurrences",
        help="Occurrence resolver JSON",
    )

    parser.add_argument(
        "--corrections",
    )

    parser.add_argument(
        "--rearrangements",
    )

    parser.add_argument(
        "--cycles",
    )

    parser.add_argument(
        "--output",
    )

    args = parser.parse_args()

    occ = load_json(
        args.occurrences
    )

    rack = occ.get(
        "rack",
        "UNKNOWN",
    )

    by_product, extras = build_index(
        occ
    )

    roles = {}

    for key, res in by_product.items():

        roles[key] = resolve_occurrence_roles(
            res
        )

    remove_actions, dependencies = (
        find_dependencies(
            by_product,
            roles,
            extras,
        )
    )

    multifacing_dependencies = (
        find_multifacing_dependency(
            by_product,
            roles,
        )
    )

    swaps = find_swaps(
        by_product,
        roles,
    )

    # --------------------------------------------------------
    # Avoid duplicate direct swap if the multifacing
    # dependency represents the same physical pair.
    # --------------------------------------------------------

    multifacing_pairs = set()

    for action in multifacing_dependencies:

        products = action.get(
            "products",
            [],
        )

        if len(products) == 2:

            pair = tuple(
                sorted(
                    norm(
                        p.get(
                            "product_id"
                        )
                    )
                    for p in products
                )
            )

            multifacing_pairs.add(
                pair
            )

    filtered_swaps = []

    for swap in swaps:

        products = swap.get(
            "products",
            [],
        )

        pair = tuple(
            sorted(
                norm(
                    p.get(
                        "product_id"
                    )
                )
                for p in products
            )
        )

        if pair in multifacing_pairs:
            continue

        filtered_swaps.append(
            swap
        )

    swaps = filtered_swaps

    safe_actions = (
        remove_actions
        + dependencies
        + multifacing_dependencies
        + swaps
    )

    reviews = make_reviews(
        by_product,
        roles,
        safe_actions,
    )

    if safe_actions:
        decision = "ACTION_RECOMMENDED"
    else:
        decision = "REVIEW_NO_SAFE_ACTION"

    if args.output:

        output = Path(
            args.output
        )

    else:

        output = Path(
            args.occurrences
        ).with_name(
            "dependencies_"
            + Path(
                args.occurrences
            ).stem
            + ".json"
        )

    report = {

        "engine": "dependency_planner",

        "engine_version": VERSION,

        "rack": rack,

        "sources": {

            "occurrences": args.occurrences,
            "corrections": args.corrections,
            "rearrangements": args.rearrangements,
            "cycles": args.cycles,

        },

        "summary": {

            "products_total": len(
                by_product
            ),

            "products_role_resolved": sum(
                1
                for r in roles.values()
                if r.get(
                    "status"
                ) == "RESOLVED"
            ),

            "products_fully_correct": sum(
                1
                for r in roles.values()
                if r.get(
                    "status"
                ) == "FULLY_CORRECT"
            ),

            "products_role_ambiguous": sum(
                1
                for r in roles.values()
                if r.get(
                    "status"
                ) == "AMBIGUOUS"
            ),

            "extra_removals_proven": len(
                remove_actions
            ),

            "dependent_moves_proven": len(
                dependencies
            ),

            "multifacing_dependencies_proven": len(
                multifacing_dependencies
            ),

            "direct_swaps_proven": len(
                swaps
            ),

            "safe_actions": len(
                safe_actions
            ),

            "review_required": len(
                reviews
            ),

        },

        "decision": decision,

        "role_resolution": roles,

        "safe_dependency_actions": safe_actions,

        "review_required": reviews,

        "safety_boundary": (
            "Only deterministic occurrence relationships "
            "are used. Multi-facing dependency resolution "
            "requires an exact occupied-destination relationship "
            "and preserves already-correct occurrences. "
            "The planner never invents shelves, slots, capacity, "
            "or product identities."
        ),

    }

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 80)

    print(
        f"SMART PLANOGRAM — DEPENDENCY PLANNER v{VERSION}"
    )

    print("=" * 80)

    print(
        f"Rack: {rack}"
    )

    print()

    print(
        "Products role-resolved : "
        f"{report['summary']['products_role_resolved']}"
    )

    print(
        "Extra removals proven  : "
        f"{len(remove_actions)}"
    )

    print(
        "Dependent moves proven : "
        f"{len(dependencies)}"
    )

    print(
        "Multifacing dependencies: "
        f"{len(multifacing_dependencies)}"
    )

    print(
        "Direct swaps proven    : "
        f"{len(swaps)}"
    )

    print(
        "Safe actions           : "
        f"{len(safe_actions)}"
    )

    print(
        "Review required        : "
        f"{len(reviews)}"
    )

    print(
        "Decision               : "
        f"{decision}"
    )

    print("-" * 80)

    if safe_actions:

        print(
            "SAFE DEPENDENCY ACTIONS"
        )

        print()

        number = 1

        for action in safe_actions:

            action_type = action.get(
                "type",
                "ACTION",
            )

            print(
                f"{number}. [{action_type}]"
            )

            print(
                f"   {action.get('action', '')}"
            )

            for step in action.get(
                "ordered_steps",
                [],
            ):

                print(
                    f"   STEP {step['step']}: "
                    f"{step['action']}"
                )

            for preserved in action.get(
                "preserve",
                [],
            ):

                print(
                    "   KEEP: "
                    f"{preserved.get('product_name')} "
                    f"at "
                    f"{loc_text(preserved.get('location'))}"
                )

            print()

            number += 1

    if reviews:

        print(
            "REVIEW REQUIRED"
        )

        print()

        for i, review in enumerate(
            reviews,
            1,
        ):

            print(
                f"{i}. "
                f"{review.get('product_name')}"
            )

            print(
                f"   Reason: "
                f"{review.get('reason')}"
            )

            print()

    print(
        f"Dependency report written to: {output}"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()
