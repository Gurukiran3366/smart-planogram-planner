#!/usr/bin/env python3
"""
SMART PLANOGRAM — CORRECTION ENGINE v1.4.4

Data-backed correction and rearrangement engine.

Inputs:
  1. shelf_analyzer.py analysis JSON
  2. merchandising_rules_v2.json
  3. products.xlsx

Design:
  - shelf_analyzer.py remains frozen.
  - Product attributes are loaded here, not guessed from the analysis JSON.
  - merchandising_rules_v2.json is the source of hard/soft rule semantics.
  - Every simulated action is validated against hard constraints before it
    can become a recommendation.
  - OOS products are never moved or corrected.
  - Physical capacity is never invented.
  - Preferred SKU rank is a soft preference, never an exact slot mandate.
  - Exact colour sequences are only scored when product colour data actually
    matches the rule vocabulary. dark/light is NOT silently treated as
    orange/red/white/etc.
  - Price groups are scored as soft preferences because the current rules
    explicitly mark them non-hard.
  - Tetra and pouch/spout-pouch products are treated as corner-only per the
    current merchandising requirement.
  - Rearrangement recommendations require a measurable net improvement.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


ENGINE_VERSION = "1.4.4"


# ---------------------------------------------------------------------
# FILE / GENERIC HELPERS
# ---------------------------------------------------------------------

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip().lower()


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def bool_value(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = norm(value)
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


# ---------------------------------------------------------------------
# PRODUCT MASTER
# ---------------------------------------------------------------------

def load_product_master(
    path: Path,
) -> Dict[str, Dict[str, Any]]:

    if not path.exists():
        raise FileNotFoundError(
            f"Product master not found: {path}"
        )

    df = pd.read_excel(path)

    required = {
        "product_id",
        "product_name",
        "commodity",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            "Product master is missing required columns: "
            f"{sorted(missing)}"
        )

    lookup: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():

        pid = norm(row.get("product_id"))

        if not pid or pid == "nan":
            continue

        lookup[pid.upper()] = {
            "product_id": str(row.get("product_id")).strip(),
            "product_name": str(
                row.get("product_name")
                or row.get("product_id")
            ).strip(),
            "brand": norm(row.get("brand")),
            "commodity": norm(row.get("commodity")),
            "pack_size_ml": safe_int(row.get("pack_size_ml")),
            "price_point": safe_int(row.get("price_point")),
            "colour_tone": norm(row.get("colour_tone")),
            "size_band": norm(row.get("size_band")),
            "is_fast_moving": bool_value(
                row.get("is_fast_moving")
            ),
            "is_high_margin": bool_value(
                row.get("is_high_margin")
            ),
            "is_water": bool_value(
                row.get("is_water")
            ),
            "package_type": norm(
                row.get("package_type")
            ),
        }

    return lookup


# ---------------------------------------------------------------------
# OOS
# ---------------------------------------------------------------------

def get_oos_ids(
    shelf: Dict[str, Any],
) -> set[str]:

    result = set()

    for item in shelf.get(
        "out_of_stock_products",
        [],
    ) or []:

        if not isinstance(item, dict):
            continue

        pid = item.get("product_id")

        if pid:
            result.add(str(pid).upper())

    return result


def is_oos(
    shelf: Dict[str, Any],
    product_id: str,
) -> bool:

    return str(product_id).upper() in get_oos_ids(shelf)


# ---------------------------------------------------------------------
# SHELF DATA EXTRACTION
# ---------------------------------------------------------------------

def colour_details(
    shelf: Dict[str, Any],
) -> List[Dict[str, Any]]:

    return list(
        (shelf.get("colour_sequence") or {}).get(
            "details"
        ) or []
    )


def facing_details(
    shelf: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:

    details = (
        shelf.get("facings") or {}
    ).get("details") or []

    result = {}

    for item in details:

        pid = item.get("product_id")

        if not pid:
            continue

        result[str(pid).upper()] = item

    return result


def physical_units(
    shelf: Dict[str, Any],
) -> List[Dict[str, Any]]:

    """
    Expand actual facings into physical positions.

    If a SKU starts at slot 6 with two facings, positions 6 and 7 are both
    occupied. This avoids false "free slot" detection.
    """

    fmap = facing_details(shelf)

    units = []

    for item in colour_details(shelf):

        pid_raw = item.get("product_id")

        if not pid_raw:
            continue

        pid = str(pid_raw).upper()

        start = safe_int(
            item.get("slot_start")
        )

        if start is None:
            continue

        facing = fmap.get(pid, {})

        count = safe_int(
            facing.get("actual_facings")
        ) or 1

        for offset in range(count):

            units.append({
                "slot": start + offset,
                "product_id": pid,
                "product_name": item.get(
                    "product_name",
                    pid,
                ),
                "unit_index": offset + 1,
            })

    units.sort(
        key=lambda x: x["slot"]
    )

    return units


def product_groups(
    units: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    groups = []

    for unit in units:

        if (
            groups
            and groups[-1]["product_id"]
            == unit["product_id"]
        ):

            groups[-1]["slots"].append(
                unit["slot"]
            )

        else:

            groups.append({
                "product_id": unit["product_id"],
                "product_name": unit["product_name"],
                "slots": [unit["slot"]],
            })

    return groups


def capacity_for_shelf(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
) -> Optional[int]:

    shelf_number = str(
        shelf.get("shelf_number")
    )

    rule = (
        rules.get("shelves", {})
        .get(shelf_number, {})
    )

    value = safe_int(
        rule.get("capacity_units")
    )

    if value is not None:
        return value

    capacity = shelf.get("capacity") or {}

    return safe_int(
        capacity.get("capacity")
    )


# ---------------------------------------------------------------------
# RULE ACCESS
# ---------------------------------------------------------------------

def shelf_rule(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, Any]:

    shelf_number = str(
        shelf.get("shelf_number")
    )

    return (
        rules.get("shelves", {})
        .get(shelf_number, {})
    )


def allowed_commodities(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
) -> set[str]:

    return {
        norm(x)
        for x in shelf_rule(
            shelf,
            rules,
        ).get(
            "allowed_commodities",
            [],
        )
    }


def preferred_rank_map(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, int]:

    result = {}

    for item in shelf_rule(
        shelf,
        rules,
    ).get(
        "preferred_products",
        [],
    ):

        pid = item.get("product_id")

        rank = safe_int(
            item.get("preferred_rank")
        )

        if pid and rank is not None:
            result[str(pid).upper()] = rank

    return result


def preferred_facings_map(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, int]:

    result = {}

    for item in shelf_rule(
        shelf,
        rules,
    ).get(
        "preferred_products",
        [],
    ):

        pid = item.get("product_id")

        facings = safe_int(
            item.get("preferred_facings")
        )

        if pid and facings is not None:
            result[str(pid).upper()] = facings

    return result


# ---------------------------------------------------------------------
# PHYSICAL CAPACITY
# ---------------------------------------------------------------------

def proven_free_slots(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
) -> List[int]:

    units = physical_units(shelf)

    if not units:
        return []

    occupied = {
        x["slot"]
        for x in units
    }

    capacity = capacity_for_shelf(
        shelf,
        rules,
    )

    if capacity is None:
        # Do not infer space after the last observed slot.
        return []

    return [
        slot
        for slot in range(
            1,
            capacity + 1,
        )
        if slot not in occupied
    ]


def physical_capacity_valid(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    units: List[Dict[str, Any]],
) -> Tuple[bool, str]:

    capacity = capacity_for_shelf(
        shelf,
        rules,
    )

    if capacity is None:
        return (
            False,
            "capacity_unknown",
        )

    if len(units) > capacity:
        return (
            False,
            "physical_facing_count_exceeds_capacity",
        )

    return (
        True,
        "capacity_valid",
    )


# ---------------------------------------------------------------------
# HARD CONSTRAINTS
# ---------------------------------------------------------------------

def is_corner_only(
    product: Dict[str, Any],
) -> bool:

    package_type = norm(
        product.get("package_type")
    )

    return (
        "tetra" in package_type
        or "pouch" in package_type
        or "spout" in package_type
    )


def hard_validate_layout(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    units: List[Dict[str, Any]],
) -> Dict[str, Any]:

    rule = shelf_rule(
        shelf,
        rules,
    )

    violations = []

    # -------------------------------------------------------------
    # Capacity
    # -------------------------------------------------------------

    capacity_ok, capacity_reason = (
        physical_capacity_valid(
            shelf,
            rules,
            units,
        )
    )

    if not capacity_ok:
        violations.append(
            capacity_reason
        )

    # -------------------------------------------------------------
    # Commodity
    # -------------------------------------------------------------

    allowed = allowed_commodities(
        shelf,
        rules,
    )

    for unit in units:

        product = products.get(
            unit["product_id"]
        )

        if not product:
            violations.append(
                f"unknown_product:{unit['product_id']}"
            )
            continue

        commodity = norm(
            product.get("commodity")
        )

        # Water is allowed only where the shelf rule explicitly permits it.
        if commodity not in allowed:
            violations.append(
                "wrong_commodity:"
                f"{unit['product_id']}"
                f":{commodity}"
            )

    # -------------------------------------------------------------
    # Shelf 6 minimum pack size
    # -------------------------------------------------------------

    price_rule = rule.get(
        "price_rule",
        {}
    )

    minimum_pack = safe_int(
        price_rule.get(
            "minimum_pack_size_ml"
        )
    )

    if minimum_pack is not None:

        for unit in units:

            product = products.get(
                unit["product_id"]
            )

            if not product:
                continue

            if bool_value(
                product.get("is_water")
            ):
                continue

            pack_size = product.get(
                "pack_size_ml"
            )

            if (
                pack_size is not None
                and pack_size < minimum_pack
            ):
                violations.append(
                    "pack_size_below_shelf_minimum:"
                    f"{unit['product_id']}"
                )

    # -------------------------------------------------------------
    # Hard special rules
    # -------------------------------------------------------------

    for special in rule.get(
        "special_rules",
        [],
    ) or []:

        if not special.get("hard"):
            continue

        rule_type = norm(
            special.get("type")
        )

        if rule_type == "tetra_pack_corner_only":

            positions = [
                x["slot"]
                for x in units
            ]

            if positions:

                first_slot = min(positions)
                last_slot = max(positions)

                for unit in units:

                    product = products.get(
                        unit["product_id"]
                    )

                    if not product:
                        continue

                    if not is_corner_only(
                        product
                    ):
                        continue

                    if unit["slot"] not in {
                        first_slot,
                        last_slot,
                    }:
                        violations.append(
                            "corner_only_package_not_at_corner:"
                            f"{unit['product_id']}:"
                            f"slot_{unit['slot']}"
                        )

    # -------------------------------------------------------------
    # OOS immobility
    # -------------------------------------------------------------

    oos = get_oos_ids(shelf)

    # Caller handles before/after OOS positions.
    # Here we only ensure the layout contains no unknown OOS product issue.

    return {
        "feasible": not violations,
        "violations": violations,
    }


# ---------------------------------------------------------------------
# SOFT SCORING
# ---------------------------------------------------------------------

def order_inversions(
    units: List[Dict[str, Any]],
    rank_map: Dict[str, int],
) -> int:

    ranks = [
        rank_map[x["product_id"]]
        for x in sorted(
            units,
            key=lambda x: x["slot"],
        )
        if x["product_id"] in rank_map
    ]

    inversions = 0

    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):

            if ranks[i] > ranks[j]:
                inversions += 1

    return inversions


def price_group_score(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    units: List[Dict[str, Any]],
) -> float:

    rule = shelf_rule(
        shelf,
        rules,
    )

    price_rule = rule.get(
        "price_rule",
        {},
    )

    target = safe_int(
        price_rule.get("value")
    )

    if target is None:
        return 0.0

    known = 0
    matches = 0

    for unit in units:

        product = products.get(
            unit["product_id"]
        )

        if not product:
            continue

        price = product.get(
            "price_point"
        )

        if price is None:
            continue

        known += 1

        if price == target:
            matches += 1

    if not known:
        return 0.0

    return matches / known


def colour_score(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    units: List[Dict[str, Any]],
) -> Tuple[Optional[float], str]:

    rule = shelf_rule(
        shelf,
        rules,
    )

    colour_rule = rule.get(
        "colour_sequence",
        {},
    )

    expected = [
        norm(x)
        for x in colour_rule.get(
            "order",
            [],
        )
    ]

    if not expected:
        return None, "colour_rule_unavailable"

    # IMPORTANT:
    # The current product master uses coarse values such as dark/light.
    # Do not map dark -> black/orange/etc. without evidence.
    observed = []

    for unit in sorted(
        units,
        key=lambda x: x["slot"],
    ):

        product = products.get(
            unit["product_id"]
        )

        if not product:
            continue

        colour = norm(
            product.get("colour_tone")
        )

        if colour not in expected:
            return (
                None,
                "catalog_colour_granularity_insufficient",
            )

        observed.append(colour)

    if not observed:
        return (
            None,
            "colour_data_unavailable",
        )

    # Score based on monotonic order positions.
    positions = {
        colour: i
        for i, colour in enumerate(expected)
    }

    values = [
        positions[x]
        for x in observed
    ]

    inversions = 0

    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] > values[j]:
                inversions += 1

    max_pairs = (
        len(values) * (len(values) - 1) // 2
    )

    if max_pairs == 0:
        return 1.0, "evaluated"

    return (
        1.0 - (inversions / max_pairs),
        "evaluated",
    )



def adjacency_group_score(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    units: List[Dict[str, Any]],
) -> float:

    special_types = {
        norm(x.get("type"))
        for x in shelf_rule(
            shelf,
            rules,
        ).get(
            "special_rules",
            [],
        ) or []
        if x.get("enabled", True)
    }

    use_brand = (
        "group_same_brand_or_flavour"
        in special_types
        or "group_same_brand"
        in special_types
    )

    if not use_brand:
        return 0.0

    ordered = sorted(
        units,
        key=lambda x: x["slot"],
    )

    known = 0
    matches = 0

    for left, right in zip(
        ordered,
        ordered[1:],
    ):

        a = products.get(
            left["product_id"]
        )

        b = products.get(
            right["product_id"]
        )

        if not a or not b:
            continue

        brand_a = norm(
            a.get("brand")
        )

        brand_b = norm(
            b.get("brand")
        )

        if not brand_a or not brand_b:
            continue

        known += 1

        if brand_a == brand_b:
            matches += 1

    if not known:
        return 0.0

    return matches / known


def shelf_quality(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    units: List[Dict[str, Any]],
) -> Dict[str, Any]:

    rank_map = preferred_rank_map(
        shelf,
        rules,
    )

    before = physical_units(
        shelf
    )

    before_inversions = (
        order_inversions(
            before,
            rank_map,
        )
    )

    after_inversions = (
        order_inversions(
            units,
            rank_map,
        )
    )

    before_price = price_group_score(
        shelf,
        rules,
        products,
        before,
    )

    after_price = price_group_score(
        shelf,
        rules,
        products,
        units,
    )

    before_colour, before_colour_status = (
        colour_score(
            shelf,
            rules,
            products,
            before,
        )
    )

    after_colour, after_colour_status = (
        colour_score(
            shelf,
            rules,
            products,
            units,
        )
    )

    before_grouping = adjacency_group_score(
        shelf,
        rules,
        products,
        before,
    )

    after_grouping = adjacency_group_score(
        shelf,
        rules,
        products,
        units,
    )

    return {
        "preferred_order_inversions_before":
            before_inversions,
        "preferred_order_inversions_after":
            after_inversions,
        "preferred_order_improvement":
            before_inversions - after_inversions,

        "price_group_score_before":
            round(before_price, 3),
        "price_group_score_after":
            round(after_price, 3),
        "price_group_improvement":
            round(
                after_price - before_price,
                3,
            ),

        "colour_score_before":
            before_colour,
        "colour_score_after":
            after_colour,
        "colour_status_before":
            before_colour_status,
        "colour_status_after":
            after_colour_status,

        "brand_grouping_score_before":
            round(before_grouping, 3),
        "brand_grouping_score_after":
            round(after_grouping, 3),
        "brand_grouping_improvement":
            round(
                after_grouping - before_grouping,
                3,
            ),

        "preferred_rank_data_available":
            bool(rank_map),

        "colour_data_available":
            (
                before_colour is not None
                or after_colour is not None
            ),
    }


# ---------------------------------------------------------------------
# HARD BEFORE/AFTER INTEGRITY
# ---------------------------------------------------------------------

def counts_by_product(
    units: List[Dict[str, Any]],
) -> Dict[str, int]:

    result = {}

    for unit in units:
        pid = unit["product_id"]
        result[pid] = (
            result.get(pid, 0) + 1
        )

    return result


def hard_integrity_check(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    before: List[Dict[str, Any]],
    after: List[Dict[str, Any]],
) -> Dict[str, Any]:

    violations = []

    if counts_by_product(before) != counts_by_product(after):
        violations.append(
            "product_facing_counts_changed"
        )

    # OOS products cannot move.
    oos = get_oos_ids(shelf)

    for pid in oos:

        before_slots = [
            x["slot"]
            for x in before
            if x["product_id"] == pid
        ]

        after_slots = [
            x["slot"]
            for x in after
            if x["product_id"] == pid
        ]

        if before_slots != after_slots:
            violations.append(
                f"oos_product_moved:{pid}"
            )

    before_hard = hard_validate_layout(
        shelf,
        rules,
        products,
        before,
    )

    after_hard = hard_validate_layout(
        shelf,
        rules,
        products,
        after,
    )

    before_violation_count = len(
        before_hard["violations"]
    )

    after_violation_count = len(
        after_hard["violations"]
    )

    # Existing hard violations are allowed to remain. A candidate is rejected
    # only when it introduces NEW hard violations. This is critical because a
    # messy staff shelf can already contain a hard violation unrelated to the
    # proposed correction.
    if (
        after_violation_count
        > before_violation_count
    ):
        violations.append(
            "candidate_creates_new_hard_violation"
        )

    # Identify the actual new hard violations for auditability.
    before_set = set(
        before_hard["violations"]
    )
    new_hard_violations = [
        x
        for x in after_hard["violations"]
        if x not in before_set
    ]

    if new_hard_violations:
        violations.extend(
            "new_hard:" + x
            for x in new_hard_violations
        )

    return {
        "feasible":
            not violations,
        "violations":
            violations,
        "before_hard":
            before_hard,
        "after_hard":
            after_hard,
        "hard_violation_count_before":
            before_violation_count,
        "hard_violation_count_after":
            after_violation_count,
        "new_hard_violations":
            new_hard_violations,
        "hard_violation_improvement":
            before_violation_count
            - after_violation_count,
    }


# ---------------------------------------------------------------------
# REARRANGEMENT SIMULATION
# ---------------------------------------------------------------------

def simulate_group_move(
    shelf: Dict[str, Any],
    source_product_id: str,
    source_slots: List[int],
    destination_before_product_id: str,
) -> Optional[List[Dict[str, Any]]]:

    before = physical_units(shelf)

    if (
        not before
        or source_product_id in get_oos_ids(shelf)
    ):
        return None

    source_slot_set = set(source_slots)

    source = [
        deepcopy(x)
        for x in before
        if (
            x["product_id"] == source_product_id
            and x["slot"] in source_slot_set
        )
    ]

    if not source:
        return None

    remaining = [
        deepcopy(x)
        for x in before
        if not (
            x["product_id"] == source_product_id
            and x["slot"] in source_slot_set
        )
    ]

    target_index = next(
        (
            i
            for i, x in enumerate(remaining)
            if x["product_id"] == destination_before_product_id
        ),
        None,
    )

    if target_index is None:
        return None

    # Mark the moved group so the recommendation can report the exact
    # moved facing/group rather than all occurrences of the same SKU.
    for unit in source:
        unit["_move_group"] = True

    result = (
        remaining[:target_index]
        + source
        + remaining[target_index:]
    )

    for slot, unit in enumerate(result, start=1):
        unit["slot"] = slot

    return result


def generate_rearrangement_candidates(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:

    before = physical_units(
        shelf
    )

    groups = product_groups(
        before
    )

    if len(groups) < 2:
        return []

    candidates = []

    for source in groups:

        source_pid = source[
            "product_id"
        ]

        if is_oos(
            shelf,
            source_pid,
        ):
            continue

        for destination in groups:

            destination_pid = destination[
                "product_id"
            ]

            if (
                source_pid
                == destination_pid
            ):
                continue

            simulated = simulate_group_move(
                shelf,
                source_pid,
                source["slots"],
                destination_pid,
            )

            if simulated is None:
                continue

            integrity = hard_integrity_check(
                shelf,
                rules,
                products,
                before,
                simulated,
            )

            if not integrity["feasible"]:
                continue

            quality = shelf_quality(
                shelf,
                rules,
                products,
                simulated,
            )

            order_gain = quality[
                "preferred_order_improvement"
            ]

            price_gain = quality[
                "price_group_improvement"
            ]

            grouping_gain = quality[
                "brand_grouping_improvement"
            ]

            colour_gain = 0.0

            if (
                quality["colour_score_before"]
                is not None
                and quality["colour_score_after"]
                is not None
            ):
                colour_gain = (
                    quality["colour_score_after"]
                    - quality["colour_score_before"]
                )

            # Weighted soft objective.
            #
            # Preferred rank is strongest.
            # Price grouping is secondary.
            # Brand grouping is tertiary.
            # Colour only participates when exact colour vocabulary is
            # actually available.
            weighted_gain = (
                (3.0 * order_gain)
                + (1.5 * price_gain)
                + (1.0 * grouping_gain)
                + (1.0 * colour_gain)
            )

            # A recommendation must measurably improve the shelf.
            if weighted_gain <= 0:
                continue

            # Do not recommend a move that worsens any reliable primary
            # signal. Unknown signals are not treated as deterioration.
            if (
                quality[
                    "preferred_rank_data_available"
                ]
                and order_gain < 0
            ):
                continue

            if price_gain < 0:
                continue

            if grouping_gain < 0:
                continue

            if (
                quality[
                    "colour_score_before"
                ] is not None
                and colour_gain < 0
            ):
                continue

            candidates.append({
                "action_type":
                    "REARRANGE_PRODUCT_GROUP",

                "shelf_number":
                    shelf.get("shelf_number"),

                "product_id":
                    source_pid,

                "product_name":
                    source["product_name"],

                "move_before_product_id":
                    destination_pid,

                "move_before_product_name":
                    destination[
                        "product_name"
                    ],

                "from_slots":
                    source["slots"],

                "simulated_after_slots": [
                    x["slot"]
                    for x in simulated
                    if x.get("_move_group")
                ],

                "reason":
                    (
                        "Move the complete product group to improve "
                        "overall merchandising compliance without "
                        "changing product/facing counts or violating "
                        "hard shelf rules."
                    ),

                "quality":
                    quality,

                "weighted_gain":
                    round(
                        weighted_gain,
                        3,
                    ),

                "hard_check":
                    integrity,

                "confidence":
                    (
                        "high"
                        if (
                            quality[
                                "preferred_rank_data_available"
                            ]
                            and (
                                quality[
                                    "colour_score_before"
                                ] is not None
                                or quality[
                                    "price_group_score_before"
                                ] >= 0
                            )
                        )
                        else "medium"
                    ),

                "requires_human_confirmation":
                    True,
            })

    # A SKU can have multiple physical groups/facings. Do not emit
    # duplicate instructions that are operationally identical.
    deduped = []
    seen = set()

    for candidate in candidates:
        signature = (
            candidate.get("shelf_number"),
            candidate.get("action_type"),
            candidate.get("product_id"),
            candidate.get("move_before_product_id"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(candidate)

    candidates = deduped

    candidates.sort(
        key=lambda x: (
            x["weighted_gain"],
            x["quality"][
                "preferred_order_improvement"
            ],
            x["quality"][
                "brand_grouping_improvement"
            ],
        ),
        reverse=True,
    )

    return candidates


def simulate_insert_at_slot(
    shelf: Dict[str, Any],
    product_id: str,
    product_name: str,
    target_slot: int,
) -> List[Dict[str, Any]]:
    """
    Insert one new facing at a physical position and shift everything at or
    to the right by one position. This is a real shelf rearrangement, not
    an assumption that the target slot was empty.
    """
    before = physical_units(shelf)
    simulated = []

    for unit in before:
        item = deepcopy(unit)
        if item["slot"] >= target_slot:
            item["slot"] += 1
        simulated.append(item)

    simulated.append({
        "slot": target_slot,
        "product_id": product_id,
        "product_name": product_name,
        "unit_index": 1,
    })

    simulated.sort(
        key=lambda x: x["slot"]
    )

    return simulated


def oos_positions_unchanged(
    shelf: Dict[str, Any],
    before: List[Dict[str, Any]],
    after: List[Dict[str, Any]],
) -> bool:
    oos = get_oos_ids(shelf)

    for pid in oos:
        before_slots = [
            x["slot"] for x in before
            if x["product_id"] == pid
        ]
        after_slots = [
            x["slot"] for x in after
            if x["product_id"] == pid
        ]
        if before_slots != after_slots:
            return False

    return True


# ---------------------------------------------------------------------
# MISSING PRODUCT CORRECTIONS
# ---------------------------------------------------------------------

def excess_facing_available(
    shelf: Dict[str, Any],
    product_id: str,
) -> bool:

    detail = facing_details(
        shelf
    ).get(
        str(product_id).upper()
    )

    if not detail:
        return False

    actual = safe_int(
        detail.get(
            "actual_facings"
        )
    )

    expected = safe_int(
        detail.get(
            "expected_facings"
        )
    )

    if (
        actual is None
        or expected is None
    ):
        return False

    return actual > expected


def diagnose_missing_product(
    shelf: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    missing: Dict[str, Any],
) -> Dict[str, Any]:

    pid = missing.get("product_id")

    product_id = (
        str(pid).upper()
        if pid
        else None
    )

    product_name = missing.get(
        "product_name"
    )

    expected_slot = safe_int(
        missing.get("expected_slot")
    )

    destination_id_raw = missing.get(
        "destination_occupant"
    )

    destination_id = (
        str(destination_id_raw).upper()
        if destination_id_raw
        else None
    )

    destination_name = missing.get(
        "destination_occupant_name"
    )

    # -------------------------------------------------------------
    # OOS
    # -------------------------------------------------------------

    if (
        product_id
        and is_oos(
            shelf,
            product_id,
        )
    ):
        return {
            "product_id":
                product_id,
            "product_name":
                product_name,
            "decision":
                "BLOCKED_OOS",
            "safe_action":
                False,
            "reasons": [
                "product_is_out_of_stock",
            ],
        }

    # -------------------------------------------------------------
    # Existing occupant with an excess facing
    # -------------------------------------------------------------

    if destination_id:

        if excess_facing_available(
            shelf,
            destination_id,
        ):
            return {
                "product_id":
                    product_id,
                "product_name":
                    product_name,
                "decision":
                    "ACTION_RECOMMENDED",
                "safe_action":
                    True,
                "checks": [{
                    "check":
                        "destination_excess_facing",
                    "status":
                        "available",
                }],
                "action": {
                    "type":
                        "reduce_excess_facing_and_place",
                    "remove_product_id":
                        destination_id,
                    "remove_product_name":
                        destination_name,
                    "target_product_id":
                        product_id,
                    "target_product_name":
                        product_name,
                    "target_slot":
                        expected_slot,
                },
            }

    # -------------------------------------------------------------
    # Prove free physical positions from rule capacity.
    # -------------------------------------------------------------

    free_slots = proven_free_slots(
        shelf,
        rules,
    )

    if not free_slots:
        reasons = []

        if destination_id:
            reasons.append(
                "destination_occupant_has_no_excess_facing"
            )

        reasons.append(
            "physical_space_not_proven"
        )

        return {
            "product_id":
                product_id,
            "product_name":
                product_name,
            "decision":
                "REVIEW_NO_SAFE_ACTION",
            "safe_action":
                False,
            "checks": [{
                "check":
                    "physical_capacity",
                "status":
                    "not_proven",
            }],
            "reasons":
                reasons,
        }

    # -------------------------------------------------------------
    # Data-backed insertion search.
    #
    # Instead of blindly using the first free slot, simulate adding the
    # missing product at every available physical slot. Reject candidates
    # that violate hard rules and rank the remaining positions using the
    # same merchandising objective as rearrangement.
    # -------------------------------------------------------------

    if not product_id:
        return {
            "product_id":
                None,
            "product_name":
                product_name,
            "decision":
                "REVIEW_NO_SAFE_ACTION",
            "safe_action":
                False,
            "reasons": [
                "missing_product_id",
            ],
        }

    product = products.get(
        product_id
    )

    if not product:
        return {
            "product_id":
                product_id,
            "product_name":
                product_name,
            "decision":
                "REVIEW_NO_SAFE_ACTION",
            "safe_action":
                False,
            "reasons": [
                "product_not_found_in_product_master",
            ],
        }

    before = physical_units(
        shelf
    )

    # -------------------------------------------------------------
    # Preferred-position insertion with shelf-wide shift.
    #
    # If the preferred position is occupied but the shelf has capacity,
    # do not immediately fall back to "put it at the end". Simulate inserting
    # the missing SKU at its preferred position and shift the existing
    # products one position to the right. This is the key whole-shelf
    # correction behavior.
    # -------------------------------------------------------------

    capacity = capacity_for_shelf(
        shelf,
        rules,
    )

    if (
        expected_slot is not None
        and capacity is not None
        and len(before) < capacity
        and 1 <= expected_slot <= capacity
    ):

        simulated = simulate_insert_at_slot(
            shelf,
            product_id,
            product.get(
                "product_name",
                product_name or product_id,
            ),
            expected_slot,
        )

        hard_before = hard_validate_layout(
            shelf,
            rules,
            products,
            before,
        )

        hard_after = hard_validate_layout(
            shelf,
            rules,
            products,
            simulated,
        )

        new_hard = [
            x
            for x in hard_after["violations"]
            if x not in set(
                hard_before["violations"]
            )
        ]

        if (
            len(hard_after["violations"])
            <= len(hard_before["violations"])
            and not new_hard
            and oos_positions_unchanged(
                shelf,
                before,
                simulated,
            )
        ):

            quality = shelf_quality(
                shelf,
                rules,
                products,
                simulated,
            )

            shifted = [
                {
                    "product_id":
                        x["product_id"],
                    "product_name":
                        x["product_name"],
                    "from_slot":
                        next(
                            (
                                y["slot"]
                                for y in before
                                if (
                                    y["product_id"]
                                    == x["product_id"]
                                    and y["slot"]
                                    == (
                                        x["slot"] - 1
                                    )
                                )
                            ),
                            None,
                        ),
                    "to_slot":
                        x["slot"],
                }
                for x in simulated
                if (
                    x["slot"] > expected_slot
                    and x["product_id"] != product_id
                )
            ]

            return {
                "product_id":
                    product_id,
                "product_name":
                    product_name
                    or product.get(
                        "product_name",
                        product_id,
                    ),
                "decision":
                    "ACTION_RECOMMENDED",
                "safe_action":
                    True,
                "checks": [
                    {
                        "check":
                            "preferred_position",
                        "status":
                            "occupied_but_insertable",
                        "preferred_slot":
                            expected_slot,
                    },
                    {
                        "check":
                            "physical_capacity",
                        "status":
                            "capacity_proven",
                        "capacity":
                            capacity,
                        "facings_before":
                            len(before),
                        "facings_after":
                            len(simulated),
                    },
                    {
                        "check":
                            "hard_rules",
                        "status":
                            "passed_without_new_violation",
                    },
                ],
                "action": {
                    "type":
                        "insert_missing_product_and_shift",
                    "product_id":
                        product_id,
                    "product_name":
                        product_name
                        or product.get(
                            "product_name",
                            product_id,
                        ),
                    "target_slot":
                        expected_slot,
                    "shifted_products":
                        shifted,
                    "placement_reason":
                        (
                            "Insert the missing expected product at its "
                            "preferred position and shift the affected "
                            "product block right by one facing. This uses "
                            "existing capacity rather than removing a "
                            "required facing."
                        ),
                },
                "quality":
                    quality,
                "requires_human_confirmation":
                    True,
            }

    candidate_positions = []

    for slot in free_slots:

        simulated = deepcopy(
            before
        )

        simulated.append({
            "slot":
                slot,
            "product_id":
                product_id,
            "product_name":
                product.get(
                    "product_name",
                    product_name
                    or product_id,
                ),
            "unit_index":
                1,
        })

        simulated.sort(
            key=lambda x: x["slot"]
        )

        # Re-number physical positions only when there is an explicit
        # internal free position. The actual free position remains the
        # physical target; do not collapse the shelf.
        before_hard = hard_validate_layout(
            shelf,
            rules,
            products,
            before,
        )

        hard = hard_validate_layout(
            shelf,
            rules,
            products,
            simulated,
        )

        before_hard_set = set(
            before_hard["violations"]
        )
        new_hard = [
            x
            for x in hard["violations"]
            if x not in before_hard_set
        ]

        if len(hard["violations"]) > len(before_hard["violations"]):
            continue

        if new_hard:
            continue

        quality = shelf_quality(
            shelf,
            rules,
            products,
            simulated,
        )

        order_gain = quality[
            "preferred_order_improvement"
        ]

        price_gain = quality[
            "price_group_improvement"
        ]

        grouping_gain = quality[
            "brand_grouping_improvement"
        ]

        colour_gain = 0.0

        if (
            quality[
                "colour_score_before"
            ] is not None
            and quality[
                "colour_score_after"
            ] is not None
        ):
            colour_gain = (
                quality[
                    "colour_score_after"
                ]
                - quality[
                    "colour_score_before"
                ]
            )

        weighted_gain = (
            (3.0 * order_gain)
            + (1.5 * price_gain)
            + (1.0 * grouping_gain)
            + (1.0 * colour_gain)
        )

        # For a missing expected product, do not block the physical
        # correction merely because adding the SKU makes a SOFT preference
        # score slightly worse. Hard safety is decisive; soft scoring is used
        # only to choose the best available slot.

        candidate_positions.append({
            "slot":
                slot,
            "weighted_gain":
                round(
                    weighted_gain,
                    3,
                ),
            "quality":
                quality,
            "hard":
                hard,
        })

    if not candidate_positions:

        return {
            "product_id":
                product_id,
            "product_name":
                product_name,
            "decision":
                "REVIEW_NO_SAFE_ACTION",
            "safe_action":
                False,
            "reasons": [
                "all_proven_free_slots_fail_hard_or_soft_validation",
            ],
        }

    candidate_positions.sort(
        key=lambda x: (
            x["weighted_gain"],
            x["quality"][
                "preferred_order_improvement"
            ],
            -abs(
                (
                    expected_slot
                    or x["slot"]
                )
                - x["slot"]
            ),
        ),
        reverse=True,
    )

    best = candidate_positions[0]

    return {
        "product_id":
            product_id,
        "product_name":
            product_name
            or product.get(
                "product_name",
                product_id,
            ),
        "decision":
            "ACTION_RECOMMENDED",
        "safe_action":
            True,
        "checks": [
            {
                "check":
                    "destination_excess_facing",
                "status":
                    (
                        "not_available"
                        if destination_id
                        else "not_applicable"
                    ),
            },
            {
                "check":
                    "physical_capacity",
                "status":
                    "free_slot_proven",
                "free_slots":
                    free_slots,
            },
            {
                "check":
                    "candidate_slot_validation",
                "status":
                    "passed",
                "candidate_slots_evaluated":
                    len(candidate_positions),
            },
        ],
        "action": {
            "type":
                "add_product_to_free_slot",
            "product_id":
                product_id,
            "product_name":
                product_name
                or product.get(
                    "product_name",
                    product_id,
                ),
            "preferred_slot":
                expected_slot,
            "available_slot":
                best["slot"],
            "placement_reason":
                (
                    "Selected from proven free physical slots using "
                    "hard-rule validation and data-backed merchandising "
                    "scoring; exact preferred slot was not available."
                    if (
                        expected_slot is not None
                        and best["slot"]
                        != expected_slot
                    )
                    else
                    "Selected by hard-rule validation and "
                    "merchandising scoring."
                ),
        },
        "quality":
            best["quality"],
        "weighted_gain":
            best["weighted_gain"],
    }


# ---------------------------------------------------------------------
# ENGINE
# ---------------------------------------------------------------------

def run_engine(
    analysis: Dict[str, Any],
    rules: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:

    shelf_results = []
    candidates = []
    blocked = []

    for shelf in (
        analysis.get(
            "shelves",
            [],
        )
    ):

        missing_results = []

        for missing in (
            (
                shelf.get(
                    "missing_products"
                )
                or {}
            ).get(
                "details",
                [],
            )
            or []
        ):

            diagnosis = (
                diagnose_missing_product(
                    shelf,
                    rules,
                    products,
                    missing,
                )
            )

            missing_results.append(
                diagnosis
            )

            if diagnosis.get(
                "safe_action"
            ):
                candidates.append({
                    "shelf_number":
                        shelf.get(
                            "shelf_number"
                        ),
                    "source":
                        "missing_product",
                    **diagnosis,
                })

            elif (
                diagnosis.get(
                    "decision"
                )
                == "REVIEW_NO_SAFE_ACTION"
            ):
                blocked.append({
                    "shelf_number":
                        shelf.get(
                            "shelf_number"
                        ),
                    **diagnosis,
                })

        rearrangements = (
            generate_rearrangement_candidates(
                shelf,
                rules,
                products,
            )
        )

        for candidate in rearrangements:
            candidates.append({
                "shelf_number":
                    shelf.get(
                        "shelf_number"
                    ),
                "source":
                    "rearrangement",
                **candidate,
            })

        shelf_results.append({
            "shelf_number":
                shelf.get(
                    "shelf_number"
                ),
            "shelf_name":
                shelf.get(
                    "shelf_name"
                ),
            "physical_occupied_slots":
                [
                    x["slot"]
                    for x in physical_units(
                        shelf
                    )
                ],
            "proven_free_slots":
                proven_free_slots(
                    shelf,
                    rules,
                ),
            "missing_diagnostics":
                missing_results,
            "rearrangement_candidates":
                rearrangements,
        })

    # Direct physical correction wins over a pure soft rearrangement.
    candidates.sort(
        key=lambda x: (
            0
            if x.get(
                "source"
            )
            == "missing_product"
            else 1,

            -x.get(
                "weighted_gain",
                0,
            ),

            -x.get(
                "quality",
                {}
            ).get(
                "preferred_order_improvement",
                0,
            ),
        )
    )

    primary = (
        candidates[0]
        if candidates
        else None
    )

    return {
        "engine_version":
            ENGINE_VERSION,

        "analyzer_version":
            analysis.get(
                "analyzer_version"
            ),

        "rack_id":
            analysis.get(
                "rack_id"
            ),

        "data_sources": {
            "analysis":
                "shelf_analyzer.py output",
            "rules":
                "merchandising_rules_v2.json",
            "product_master":
                "products.xlsx",
        },

        "principles": {
            "shelf_analyzer_frozen":
                True,
            "never_correct_oos":
                True,
            "never_remove_required_facing":
                True,
            "never_assume_capacity":
                True,
            "hard_constraints_dominate_soft_preferences":
                True,
            "preferred_product_order_is_soft":
                True,
            "exact_colour_sequence_requires_matching_catalog_vocabulary":
                True,
            "price_group_is_soft_when_rule_marks_it_non_hard":
                True,
            "rearrangement_preserves_total_facings":
                True,
            "rearrangement_requires_net_measurable_improvement":
                True,
        },

        "summary": {
            "shelves_analyzed":
                len(
                    analysis.get(
                        "shelves",
                        [],
                    )
                ),
            "candidates_generated":
                len(candidates),
            "blocked_corrections":
                len(blocked),
            "rearrangement_candidates":
                sum(
                    1
                    for x in candidates
                    if x.get(
                        "source"
                    )
                    == "rearrangement"
                ),
            "decision":
                (
                    "ACTION_RECOMMENDED"
                    if primary
                    else "REVIEW"
                ),
        },

        "primary_recommendation":
            primary,

        "candidates":
            candidates,

        "blocked_corrections":
            blocked,

        "shelves":
            shelf_results,
    }


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Smart Planogram data-backed correction engine."
        )
    )

    parser.add_argument(
        "analysis",
        type=Path,
    )

    parser.add_argument(
        "--rules",
        type=Path,
        default=Path(
            "data/merchandising_rules_v2.json"
        ),
    )

    parser.add_argument(
        "--products",
        type=Path,
        default=Path(
            "data/products.xlsx"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )

    args = parser.parse_args()

    if not args.analysis.exists():
        raise FileNotFoundError(
            f"Analysis file not found: "
            f"{args.analysis}"
        )

    if not args.rules.exists():
        raise FileNotFoundError(
            f"Rules file not found: "
            f"{args.rules}"
        )

    products = load_product_master(
        args.products
    )

    rules = load_json(
        args.rules
    )

    analysis = load_json(
        args.analysis
    )

    result = run_engine(
        analysis,
        rules,
        products,
    )

    output = (
        args.output
        or (
            args.analysis.parent
            / f"corrections_"
              f"{args.analysis.name}"
        )
    )

    save_json(
        result,
        output,
    )

    print()
    print("=" * 72)
    print(
        "SMART PLANOGRAM — "
        "CORRECTION ENGINE v1.4.4"
    )
    print("=" * 72)

    print(
        f"Rack: "
        f"{result.get('rack_id')}"
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
        f"Rearrangement candidates: "
        f"{result['summary']['rearrangement_candidates']}"
    )

    print(
        f"Decision              : "
        f"{result['summary']['decision']}"
    )

    print("-" * 72)

    primary = result.get(
        "primary_recommendation"
    )

    if not primary:

        print(
            "RECOMMENDATION: "
            "REVIEW / NO SAFE ACTION"
        )

        for item in result.get(
            "blocked_corrections",
            [],
        ):

            print()

            print(
                f"Shelf "
                f"{item.get('shelf_number')} — "
                f"{item.get('product_name')}"
            )

            for reason in item.get(
                "reasons",
                [],
            ):

                if reason == (
                    "destination_occupant_has_no_excess_facing"
                ):
                    print(
                        "  - Destination occupant "
                        "has no excess facing."
                    )

                elif reason == (
                    "physical_space_not_proven"
                ):
                    print(
                        "  - Physical space "
                        "is not proven."
                    )

                else:
                    print(
                        f"  - {reason}"
                    )

    elif (
        primary.get(
            "source"
        )
        == "missing_product"
    ):

        print(
            "RECOMMENDATION: "
            "ACTIONABLE CORRECTION"
        )

        print(
            f"Shelf "
            f"{primary['shelf_number']}:"
        )

        print(
            json.dumps(
                primary.get(
                    "action",
                    {},
                ),
                indent=2,
                ensure_ascii=False,
            )
        )

    else:

        print(
            "RECOMMENDATION: "
            "SHELF-WIDE REARRANGEMENT"
        )

        print(
            f"Shelf "
            f"{primary['shelf_number']}"
        )

        print(
            f"Move: "
            f"{primary.get('product_name')}"
        )

        print(
            f"Move before: "
            f"{primary.get('move_before_product_name')}"
        )

        print(
            f"Current slots: "
            f"{primary.get('from_slots')}"
        )

        print(
            f"Simulated slots: "
            f"{primary.get('simulated_after_slots')}"
        )

        quality = primary.get(
            "quality",
            {},
        )

        print(
            "Preferred-order improvement: "
            f"{quality.get('preferred_order_improvement', 0)}"
        )

        print(
            "Price-group improvement: "
            f"{quality.get('price_group_improvement', 0)}"
        )

        print(
            "Brand-grouping improvement: "
            f"{quality.get('brand_grouping_improvement', 0)}"
        )

        print(
            "Colour evaluation: "
            f"{quality.get('colour_status_after')}"
        )

        print(
            f"Confidence: "
            f"{primary.get('confidence')}"
        )

        print(
            "HUMAN CONFIRMATION: required"
        )

    print()
    print(
        f"Correction analysis written to: "
        f"{output}"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
