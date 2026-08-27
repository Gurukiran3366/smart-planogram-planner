"""
shelf_analyzer.py

Whole-shelf merchandising analyzer for the Smart Planogram Planner.

This module intentionally does NOT generate final physical corrections.
It evaluates an actual shelf against:
  1. hard merchandising constraints
  2. soft merchandising preferences
  3. the locked expected map
  4. product-master attributes

The output is a structured shelf diagnosis that a later correction engine
can use to generate and validate physical actions.

Usage:
    python shelf_analyzer.py data/actual_maps/actual_map_shelfmessing.json

Optional:
    python shelf_analyzer.py <actual_map.json> --rules data/merchandising_rules_v2.json
    python shelf_analyzer.py <actual_map.json> --expected data/expected_map_BTM_CH01.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    from oos_filter import apply_oos_filter, get_oos_ids
except ImportError:
    apply_oos_filter = None
    get_oos_ids = None


DEFAULT_RULES = Path("data/merchandising_rules_v2.json")
DEFAULT_EXPECTED = Path("data/expected_map_BTM_CH01.json")
DEFAULT_PRODUCTS = Path("data/products.xlsx")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def norm(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def unique(values: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for value in values:
        key = str(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def safe_mean(values: List[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


# ---------------------------------------------------------------------------
# Product master
# ---------------------------------------------------------------------------

def load_product_master(path: Path) -> Dict[str, Dict[str, Any]]:
    df = pd.read_excel(path)

    required = {"product_id", "product_name"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Product master is missing required columns: {sorted(missing)}"
        )

    lookup: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        pid = str(row["product_id"]).strip()
        if not pid or pid.lower() == "nan":
            continue

        item = {
            "product_id": pid,
            "product_name": row.get("product_name", pid),
            "brand": row.get("brand", ""),
            "commodity": row.get("commodity", ""),
            "colour_tone": row.get("colour_tone", ""),
            "size_band": row.get("size_band", ""),
            "price_point": row.get("price_point", None),
            "pack_size_ml": row.get("pack_size_ml", None),
            "package_type": row.get("package_type", ""),
            "is_fast_moving": row.get("is_fast_moving", None),
            "is_high_margin": row.get("is_high_margin", None),
            "is_water": row.get("is_water", None),
        }

        # Preserve optional flavour/variant columns if present in future catalog versions.
        for column in ("flavour", "flavor", "variant", "sub_category", "product_vertical"):
            if column in df.columns:
                item[column] = row.get(column, "")

        lookup[pid] = item

    return lookup


def product_attr(product_lookup: Dict[str, Dict[str, Any]], pid: str, key: str) -> Any:
    return product_lookup.get(pid, {}).get(key)


def product_name(product_lookup: Dict[str, Dict[str, Any]], pid: str) -> str:
    value = product_attr(product_lookup, pid, "product_name")
    return str(value) if value and not pd.isna(value) else pid.replace("_", " ").title()


def product_flavour(product_lookup: Dict[str, Dict[str, Any]], pid: str) -> Optional[str]:
    item = product_lookup.get(pid, {})
    for key in ("flavour", "flavor", "variant"):
        value = norm(item.get(key))
        if value:
            return value
    return None


def fast_moving_status(product_lookup: Dict[str, Dict[str, Any]], pid: str) -> str:
    value = product_attr(product_lookup, pid, "is_fast_moving")
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "unknown"
    if isinstance(value, str):
        v = norm(value)
        if v in {"true", "yes", "1", "y"}:
            return "true"
        if v in {"false", "no", "0", "n"}:
            return "false"
        return "unknown"
    return "true" if bool(value) else "false"


# ---------------------------------------------------------------------------
# Rules / expected / actual map
# ---------------------------------------------------------------------------

def build_rule_lookup(rules: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    shelves = rules.get("shelves", {})
    result: Dict[int, Dict[str, Any]] = {}

    for shelf_id, shelf_rule in shelves.items():
        sid = as_int(shelf_id)
        if sid is not None:
            result[sid] = shelf_rule

    return result


def build_expected_lookup(
    expected: Dict[str, Any],
    oos_product_ids: Optional[Iterable[str]] = None,
) -> Dict[int, List[Dict[str, Any]]]:
    """Build expected products, excluding staff-selected OOS products.

    Shelf identity is taken from ``shelf_number`` (the canonical expected-map
    field). OOS products are retained as metadata but are not returned as
    active expected products for missing-product/correction analysis.
    """
    oos_ids = {str(pid).strip() for pid in (oos_product_ids or [])}
    result: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for shelf in expected.get("shelves", []):
        sid = as_int(shelf.get("shelf_number"))
        if sid is None:
            continue

        for product in shelf.get("products", []):
            item = dict(product)
            item["product_id"] = str(product["product_id"]).strip()

            if item["product_id"] in oos_ids:
                continue

            result[sid].append(item)

    return dict(result)


def build_oos_lookup(
    expected: Dict[str, Any],
    oos_product_ids: Iterable[str],
) -> Dict[int, List[Dict[str, Any]]]:
    """Preserve OOS products by shelf for reporting and future restoration."""
    oos_ids = {str(pid).strip() for pid in (oos_product_ids or [])}
    result: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for shelf in expected.get("shelves", []):
        sid = as_int(shelf.get("shelf_number"))
        if sid is None:
            continue

        for product in shelf.get("products", []):
            pid = str(product.get("product_id", "")).strip()
            if pid in oos_ids:
                item = dict(product)
                item["product_id"] = pid
                item["status"] = "out_of_stock"
                item["excluded_from_missing_check"] = True
                item["excluded_from_correction"] = True
                item["preferred_position_preserved"] = True
                result[sid].append(item)

    return dict(result)

def build_actual_lookup(actual: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    result: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for shelf in actual.get("shelves", []):
        sid = as_int(shelf.get("shelf_number"))
        if sid is None:
            continue

        for product in shelf.get("products", []):
            item = dict(product)
            item["product_id"] = str(product["product_id"]).strip()
            item["slot_start"] = as_int(item.get("slot_start"))
            item["slot_end"] = as_int(
                item.get("slot_end"), item.get("slot_start")
            )
            item["facings"] = as_int(item.get("facings"), 1) or 1
            result[sid].append(item)

    return dict(result)


def preferred_product_ids(
    shelf_id: int,
    rule: Dict[str, Any],
    expected_products: List[Dict[str, Any]],
) -> List[str]:
    # The rules file is the merchandising source of truth. The expected map
    # is used as a fallback for the locked reference list.
    preferred = rule.get("preferred_products", [])
    ids = []

    for item in preferred:
        pid = item.get("product_id") if isinstance(item, dict) else item
        if pid:
            ids.append(str(pid).strip())

    if ids:
        return ids

    return [
        str(item["product_id"]).strip()
        for item in expected_products
        if item.get("product_id")
    ]


# ---------------------------------------------------------------------------
# Shelf occupancy / geometry
# ---------------------------------------------------------------------------

def physical_slots(products: List[Dict[str, Any]]) -> List[int]:
    slots: List[int] = []
    for product in products:
        start = as_int(product.get("slot_start"))
        end = as_int(product.get("slot_end"), start)

        if start is not None and end is not None:
            if end < start:
                start, end = end, start
            slots.extend(range(start, end + 1))
        else:
            facings = as_int(product.get("facings"), 1) or 1
            slots.extend([-1] * facings)

    return slots


def occupied_slot_map(products: List[Dict[str, Any]]) -> Dict[int, str]:
    occupancy: Dict[int, str] = {}

    for product in products:
        pid = product["product_id"]
        start = as_int(product.get("slot_start"))
        end = as_int(product.get("slot_end"), start)

        if start is None:
            continue

        end = end if end is not None else start
        if end < start:
            start, end = end, start

        for slot in range(start, end + 1):
            occupancy[slot] = pid

    return occupancy


def total_physical_facings(products: List[Dict[str, Any]]) -> int:
    total = 0
    for product in products:
        start = as_int(product.get("slot_start"))
        end = as_int(product.get("slot_end"), start)
        if start is not None and end is not None:
            total += abs(end - start) + 1
        else:
            total += as_int(product.get("facings"), 1) or 1
    return total


def left_to_right(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        products,
        key=lambda p: (
            as_int(p.get("slot_start"), 10_000) or 10_000,
            norm(p.get("zone")),
        ),
    )


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def allowed_commodities(rule: Dict[str, Any]) -> List[str]:
    values = rule.get("allowed_commodities", [])
    if values:
        return [norm(v) for v in values]

    # Support older/alternate rule files.
    value = rule.get("category")
    return [norm(value)] if value else []


def evaluate_category(
    shelf_id: int,
    products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    allowed = allowed_commodities(rule)
    results = []

    for product in products:
        pid = product["product_id"]
        commodity = norm(product_attr(catalog, pid, "commodity"))

        if not commodity:
            status = "unknown"
        elif commodity in allowed:
            status = "pass"
        else:
            status = "fail"

        results.append({
            "product_id": pid,
            "product_name": product_name(catalog, pid),
            "catalog_commodity": commodity,
            "allowed_commodities": allowed,
            "status": status,
        })

    failures = [r for r in results if r["status"] == "fail"]
    unknowns = [r for r in results if r["status"] == "unknown"]

    return {
        "status": "fail" if failures else ("review" if unknowns else "pass"),
        "allowed_commodities": allowed,
        "details": results,
        "failure_count": len(failures),
        "unknown_count": len(unknowns),
    }


def evaluate_capacity(
    shelf_id: int,
    products: List[Dict[str, Any]],
    rule: Dict[str, Any],
) -> Dict[str, Any]:
    capacity = as_int(rule.get("capacity"))
    occupied = total_physical_facings(products)

    if capacity is None:
        return {
            "status": "unknown",
            "capacity": None,
            "occupied_slots": occupied,
            "remaining_slots": None,
        }

    remaining = capacity - occupied

    return {
        "status": "pass" if remaining >= 0 else "fail",
        "capacity": capacity,
        "occupied_slots": occupied,
        "remaining_slots": remaining,
    }


def evaluate_price_group(
    products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    price_rule = rule.get("price_rule", {})
    if not isinstance(price_rule, dict):
        return {"status": "unknown", "details": []}

    rule_type = price_rule.get("type")
    target = price_rule.get("value")
    details = []

    for product in products:
        pid = product["product_id"]
        value = product_attr(catalog, pid, "price_point")

        if pd.isna(value) if isinstance(value, float) else value is None:
            status = "unknown"
        elif rule_type == "preferred_group":
            try:
                status = "preferred" if float(value) == float(target) else "exception"
            except (TypeError, ValueError):
                status = "unknown"
        elif rule_type == "no_fixed_price":
            status = "pass"
        elif rule_type == "size_band":
            size = product_attr(catalog, pid, "pack_size_ml")
            minimum = price_rule.get("minimum_pack_size_ml")
            if size is None or pd.isna(size):
                status = "unknown"
            else:
                status = "pass" if float(size) >= float(minimum) else "fail"
        else:
            status = "unknown"

        details.append({
            "product_id": pid,
            "product_name": product_name(catalog, pid),
            "catalog_price": value,
            "status": status,
        })

    hard = bool(price_rule.get("hard", False))
    failures = [d for d in details if d["status"] == "fail"]
    exceptions = [d for d in details if d["status"] == "exception"]
    unknowns = [d for d in details if d["status"] == "unknown"]

    if failures:
        status = "fail"
    elif unknowns:
        status = "review"
    elif exceptions and not hard:
        status = "pass_with_preferred_exceptions"
    else:
        status = "pass"

    return {
        "status": status,
        "hard": hard,
        "rule": price_rule,
        "details": details,
        "preferred_count": sum(d["status"] == "preferred" for d in details),
        "exception_count": len(exceptions),
    }


def colour_rank(colour: str, sequence: List[str]) -> Optional[int]:
    c = norm(colour)
    if not c:
        return None

    normalized = [norm(x) for x in sequence]

    # Direct match first.
    if c in normalized:
        return normalized.index(c)

    # Handle common catalog descriptors.
    aliases = {
        "dark_orange": "orange",
        "light_orange": "orange",
        "pink": "pink",
        "light blue": "light_blue",
        "light_blue": "light_blue",
    }

    mapped = aliases.get(c)
    if mapped and mapped in normalized:
        return normalized.index(mapped)

    return None


def evaluate_colour_sequence(
    products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    raw_sequence = rule.get("colour_sequence", [])
    if isinstance(raw_sequence, dict):
        enabled = bool(raw_sequence.get("enabled", True))
        sequence = raw_sequence.get("order", [])
        hard = bool(raw_sequence.get("hard", False))
    else:
        enabled = bool(raw_sequence)
        sequence = raw_sequence
        hard = False

    sequence = [norm(x) for x in sequence]
    if not enabled or not sequence:
        return {
            "status": "not_applicable",
            "configured_sequence": sequence,
            "hard": hard,
            "details": [],
        }

    ordered = left_to_right(products)

    details = []
    ranks = []

    for product in ordered:
        pid = product["product_id"]
        colour = norm(product_attr(catalog, pid, "colour_tone"))
        rank = colour_rank(colour, sequence)

        details.append({
            "product_id": pid,
            "product_name": product_name(catalog, pid),
            "slot_start": product.get("slot_start"),
            "colour": colour,
            "sequence_rank": rank,
        })

        if rank is not None:
            ranks.append(rank)

    # If the rules require exact colours but the catalog only contains
    # coarse dark/light values, do not invent a mapping.
    available_colours = {
        d["colour"] for d in details if d["colour"]
    }
    if available_colours and available_colours.issubset({"dark", "light"}) and (
        set(sequence) - {"dark", "light"}
    ):
        return {
            "status": "data_limitation",
            "reason": "catalog_colour_granularity_insufficient",
            "configured_sequence": sequence,
            "hard": hard,
            "available_catalog_colours": sorted(available_colours),
            "details": details,
        }

    # A sequence is considered compliant if its ranks never move backwards.
    inversions = 0
    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):
            if ranks[i] > ranks[j]:
                inversions += 1

    missing_colour_data = sum(d["sequence_rank"] is None for d in details)

    if not sequence:
        status = "not_applicable"
    elif missing_colour_data:
        status = "data_limitation"
    elif inversions == 0:
        status = "pass"
    else:
        status = "fail"

    return {
        "status": status,
        "configured_sequence": sequence,
        "inversion_count": inversions,
        "missing_colour_data": missing_colour_data,
        "hard": hard,
        "details": details,
    }


def evaluate_corner_packages(
    products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    placement = rule.get("package_placement_rule", {})
    if not placement.get("corner_only"):
        return {"status": "not_applicable", "details": []}

    corner_types = {norm(x) for x in placement.get("package_types", [])}
    details = []

    ordered = left_to_right(products)

    for index, product in enumerate(ordered):
        pid = product["product_id"]
        package_type = norm(product_attr(catalog, pid, "package_type"))
        is_corner = index == 0 or index == len(ordered) - 1

        if package_type in corner_types:
            status = "pass" if is_corner else "fail"
            details.append({
                "product_id": pid,
                "product_name": product_name(catalog, pid),
                "package_type": package_type,
                "position": "leftmost" if index == 0 else (
                    "rightmost" if index == len(ordered) - 1 else "middle"
                ),
                "status": status,
            })

    failures = [d for d in details if d["status"] == "fail"]

    return {
        "status": "fail" if failures else "pass",
        "corner_only_package_types": sorted(corner_types),
        "details": details,
    }


def evaluate_grouping(
    products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    special_rules = [norm(x) for x in rule.get("special_rules", [])]
    group_flavour = any("group same flavour" in x for x in special_rules)
    group_brand = any("group same brand" in x for x in special_rules)

    if not group_flavour and not group_brand:
        return {"status": "not_applicable", "details": []}

    ordered = left_to_right(products)
    details = []
    unknown_flavour = False
    unknown_brand = False
    violations = 0

    def groups_are_contiguous(values: List[Optional[str]]) -> bool:
        seen = set()
        previous = None
        for value in values:
            if not value:
                continue
            if value != previous and value in seen:
                return False
            seen.add(value)
            previous = value
        return True

    if group_flavour:
        flavours = []
        for p in ordered:
            value = product_flavour(catalog, p["product_id"])
            if not value:
                unknown_flavour = True
            flavours.append(value)

        ok = groups_are_contiguous(flavours)
        details.append({
            "rule": "same_flavour_grouping",
            "status": "review" if unknown_flavour else ("pass" if ok else "fail"),
            "sequence": flavours,
        })
        if not ok and not unknown_flavour:
            violations += 1

    if group_brand:
        brands = [norm(product_attr(catalog, p["product_id"], "brand")) for p in ordered]
        unknown_brand = any(not x for x in brands)
        ok = groups_are_contiguous(brands)
        details.append({
            "rule": "same_brand_grouping",
            "status": "review" if unknown_brand else ("pass" if ok else "fail"),
            "sequence": brands,
        })
        if not ok and not unknown_brand:
            violations += 1

    if violations:
        status = "fail"
    elif any(d["status"] == "review" for d in details):
        status = "review"
    else:
        status = "pass"

    return {"status": status, "details": details}


def evaluate_facings(
    products: List[Dict[str, Any]],
    expected_products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    expected_facings = Counter()
    for item in expected_products:
        expected_facings[item["product_id"]] += as_int(item.get("facings"), 1) or 1

    details = []
    for product in products:
        pid = product["product_id"]
        actual = as_int(product.get("facings"), 1) or 1
        expected = expected_facings.get(pid, 1)
        status = "pass"

        if actual > expected:
            fm = fast_moving_status(catalog, pid)
            if fm == "true":
                status = "allowed_extra_facing"
            elif fm == "unknown":
                status = "review"
            else:
                status = "excess_facing"

        elif actual < expected:
            status = "insufficient_facing"

        details.append({
            "product_id": pid,
            "product_name": product_name(catalog, pid),
            "expected_facings": expected,
            "actual_facings": actual,
            "fast_moving_status": fast_moving_status(catalog, pid),
            "status": status,
        })

    failures = [
        d for d in details
        if d["status"] in {"excess_facing", "insufficient_facing"}
    ]
    reviews = [d for d in details if d["status"] == "review"]

    return {
        "status": "fail" if failures else ("review" if reviews else "pass"),
        "details": details,
        "excess_facing_count": sum(d["status"] == "excess_facing" for d in details),
        "insufficient_facing_count": sum(
            d["status"] == "insufficient_facing" for d in details
        ),
        "unknown_fast_moving_count": sum(
            d["fast_moving_status"] == "unknown" for d in details
        ),
    }


def evaluate_preferred_order(
    products: List[Dict[str, Any]],
    preferred_ids: List[str],
) -> Dict[str, Any]:
    if not preferred_ids:
        return {"status": "not_applicable", "score": None, "details": []}

    preferred_rank = {pid: i for i, pid in enumerate(preferred_ids)}
    ordered = left_to_right(products)

    ranks = [
        preferred_rank[p["product_id"]]
        for p in ordered
        if p["product_id"] in preferred_rank
    ]

    if len(ranks) <= 1:
        return {
            "status": "pass",
            "score": 1.0,
            "details": [],
        }

    inversions = 0
    comparisons = 0
    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):
            comparisons += 1
            if ranks[i] > ranks[j]:
                inversions += 1

    score = 1.0 - (inversions / comparisons if comparisons else 0.0)

    return {
        "status": "pass" if inversions == 0 else "soft_deviation",
        "score": round(score, 3),
        "inversion_count": inversions,
        "comparisons": comparisons,
    }


def evaluate_missing_and_occupied_targets(
    shelf_id: int,
    actual_products: List[Dict[str, Any]],
    expected_products: List[Dict[str, Any]],
    catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    actual_ids = {p["product_id"] for p in actual_products}
    actual_occupancy = occupied_slot_map(actual_products)
    expected_by_id = {p["product_id"]: p for p in expected_products}
    actual_by_id = {p["product_id"]: p for p in actual_products}

    missing = []
    for expected in expected_products:
        pid = expected["product_id"]
        if pid in actual_ids:
            continue

        slot = as_int(expected.get("slot_start"))
        occupant_id = actual_occupancy.get(slot) if slot is not None else None
        occupant = actual_by_id.get(occupant_id) if occupant_id else None
        occupant_expected = expected_by_id.get(occupant_id) if occupant_id else None

        actual_facings = (
            as_int(occupant.get("facings"), 1) or 1
            if occupant else None
        )
        expected_facings = (
            as_int(occupant_expected.get("facings"), 1) or 1
            if occupant_expected else None
        )
        potential_excess = bool(
            occupant and occupant_expected
            and actual_facings > expected_facings
        )

        missing.append({
            "product_id": pid,
            "product_name": product_name(catalog, pid),
            "expected_slot": slot,
            "expected_facings": as_int(expected.get("facings"), 1) or 1,
            "destination_occupant": occupant_id,
            "destination_occupant_name": (
                product_name(catalog, occupant_id) if occupant_id else None
            ),
            "occupant_actual_facings": actual_facings,
            "occupant_expected_facings": expected_facings,
            "potential_excess_facing": potential_excess,
            "occupant_fast_moving_status": (
                fast_moving_status(catalog, occupant_id)
                if occupant_id else "unknown"
            ),
            "diagnosis": (
                "potential_excess_facing_blocks_preferred_position"
                if potential_excess
                else (
                    "expected_product_missing_destination_occupied"
                    if occupant_id
                    else "expected_product_missing_destination_empty_or_unknown"
                )
            ),
        })

    return {
        "missing_count": len(missing),
        "potential_excess_facing_conflicts": sum(
            1 for item in missing if item["potential_excess_facing"]
        ),
        "details": missing,
    }


# ---------------------------------------------------------------------------
# Whole-shelf analyzer
# ---------------------------------------------------------------------------

def analyze_shelf(
    shelf_id: int,
    actual_products: List[Dict[str, Any]],
    expected_products: List[Dict[str, Any]],
    rule: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
    oos_products: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:

    preferred_ids = preferred_product_ids(
        shelf_id, rule, expected_products
    )

    category = evaluate_category(
        shelf_id, actual_products, rule, catalog
    )
    capacity = evaluate_capacity(
        shelf_id, actual_products, rule
    )
    price = evaluate_price_group(
        actual_products, rule, catalog
    )
    colour = evaluate_colour_sequence(
        actual_products, rule, catalog
    )
    corners = evaluate_corner_packages(
        actual_products, rule, catalog
    )
    grouping = evaluate_grouping(
        actual_products, rule, catalog
    )
    facings = evaluate_facings(
        actual_products, expected_products, rule, catalog
    )
    preferred_order = evaluate_preferred_order(
        actual_products, preferred_ids
    )
    missing = evaluate_missing_and_occupied_targets(
        shelf_id, actual_products, expected_products, catalog
    )

    hard_failures = []
    reviews = []
    soft_deviations = []

    if category["status"] == "fail":
        hard_failures.append("category")
    elif category["status"] == "review":
        reviews.append("category_data")

    if capacity["status"] == "fail":
        hard_failures.append("capacity")

    if price["status"] == "fail":
        hard_failures.append("price_group")
    elif price["status"] in {"pass_with_preferred_exceptions", "review"}:
        soft_deviations.append("preferred_price_group")

    if colour["status"] == "fail":
        soft_deviations.append("colour_sequence")
    elif colour["status"] == "review":
        reviews.append("colour_data")
    elif colour["status"] == "data_limitation":
        # Do not turn a known catalog limitation into a false merchandising
        # failure. Preserve the limitation in the detailed JSON.
        pass

    if corners["status"] == "fail":
        hard_failures.append("corner_only_package")

    if grouping["status"] == "fail":
        soft_deviations.append("grouping")
    elif grouping["status"] == "review":
        reviews.append("grouping_data")

    if facings["status"] == "fail":
        soft_deviations.append("facings")
    elif facings["status"] == "review":
        # Fast-moving data is unavailable. This is a data-quality
        # limitation, not evidence that the shelf requires correction.
        # Keep the diagnostic information in JSON without escalating status.
        pass

    if preferred_order["status"] == "soft_deviation":
        soft_deviations.append("preferred_order")

    if missing["missing_count"]:
        soft_deviations.append("missing_expected_products")
        if missing["potential_excess_facing_conflicts"]:
            reviews.append("missing_destination_root_cause_review")

    if hard_failures:
        overall_status = "needs_action"
    elif reviews:
        overall_status = "review"
    elif soft_deviations:
        overall_status = "soft_deviation"
    else:
        overall_status = "compliant"

    # A transparent diagnostic score. This is NOT the final business score.
    hard_penalty = min(0.50, 0.20 * len(hard_failures))
    soft_penalty = min(0.30, 0.05 * len(soft_deviations))
    review_penalty = min(0.15, 0.03 * len(reviews))
    diagnostic_score = round(max(0.0, 1.0 - hard_penalty - soft_penalty - review_penalty), 3)

    return {
        "shelf_number": shelf_id,
        "shelf_name": rule.get("shelf_name", f"Shelf {shelf_id}"),
        "status": overall_status,
        "diagnostic_score": diagnostic_score,
        "hard_failures": hard_failures,
        "soft_deviations": soft_deviations,
        "reviews_required": reviews,
        "category": category,
        "capacity": capacity,
        "price_group": price,
        "colour_sequence": colour,
        "package_placement": corners,
        "grouping": grouping,
        "facings": facings,
        "preferred_order": preferred_order,
        "missing_products": missing,
        "root_cause_candidates": [
            {
                "type": "potential_excess_facing_conflict",
                "product_id": item["destination_occupant"],
                "product_name": item["destination_occupant_name"],
                "actual_facings": item["occupant_actual_facings"],
                "expected_facings": item["occupant_expected_facings"],
                "fast_moving_status": item["occupant_fast_moving_status"],
                "confidence": (
                    "medium"
                    if item["occupant_fast_moving_status"] == "unknown"
                    else "high"
                ),
                "reason": item["diagnosis"],
            }
            for item in missing["details"]
            if item["potential_excess_facing"]
        ],
        "actual_product_count": len(actual_products),
        "actual_physical_facings": total_physical_facings(actual_products),
        "preferred_product_count": len(preferred_ids),
        "out_of_stock_products": oos_products or [],
        "oos_product_count": len(oos_products or []),
    }


def analyze_rack(
    actual: Dict[str, Any],
    expected: Dict[str, Any],
    rules: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
    oos_product_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:

    rule_lookup = build_rule_lookup(rules)
    oos_ids = {str(pid).strip() for pid in (oos_product_ids or [])}
    expected_lookup = build_expected_lookup(expected, oos_ids)
    oos_lookup = build_oos_lookup(expected, oos_ids)
    actual_lookup = build_actual_lookup(actual)

    shelf_ids = sorted(set(rule_lookup) | set(expected_lookup) | set(actual_lookup))

    shelf_results = []

    for shelf_id in shelf_ids:
        rule = rule_lookup.get(shelf_id, {})
        result = analyze_shelf(
            shelf_id=shelf_id,
            actual_products=actual_lookup.get(shelf_id, []),
            expected_products=expected_lookup.get(shelf_id, []),
            rule=rule,
            catalog=catalog,
            oos_products=oos_lookup.get(shelf_id, []),
        )
        shelf_results.append(result)

    statuses = Counter(r["status"] for r in shelf_results)

    return {
        "rack_id": actual.get("rack_id", rules.get("rack_id")),
        "analyzer_version": "1.3",
        "analysis_type": "whole_shelf_merchandising",
        "principles": rules.get("global_rules", {}),
        "summary": {
            "shelves_analyzed": len(shelf_results),
            "compliant": statuses.get("compliant", 0),
            "soft_deviation": statuses.get("soft_deviation", 0),
            "review": statuses.get("review", 0),
            "needs_action": statuses.get("needs_action", 0),
        },
        "shelves": shelf_results,
        "oos": {
            "selected_product_ids": sorted(oos_ids),
            "selected_count": len(oos_ids),
            "excluded_from_missing_check": True,
            "excluded_from_correction": True,
            "preferred_positions_preserved": True,
        },
        "note": (
            "This is a diagnostic layer. It intentionally does not emit final "
            "MOVE/ADD/REMOVE recommendations. The correction engine must compare "
            "candidate actions against all shelf constraints before recommending action."
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_summary(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print("SMART PLANOGRAM — WHOLE-SHELF MERCHANDISING ANALYSIS")
    print("=" * 72)
    print(f"Rack: {result.get('rack_id')}")
    print(f"Shelves analyzed: {result['summary']['shelves_analyzed']}")

    summary = result["summary"]
    print(
        "Status: "
        f"needs_action={summary['needs_action']} | "
        f"review={summary['review']} | "
        f"soft_deviation={summary['soft_deviation']} | "
        f"compliant={summary['compliant']}"
    )

    print("\nSHELF SUMMARY")
    print("-" * 72)

    for shelf in result["shelves"]:
        print(
            f"Shelf {shelf['shelf_number']}: "
            f"{shelf['status'].upper():<14} "
            f"diagnostic_score={shelf['diagnostic_score']:.3f}"
        )

        if shelf["hard_failures"]:
            print("  HARD:", ", ".join(shelf["hard_failures"]))

        if shelf["soft_deviations"]:
            print("  SOFT:", ", ".join(shelf["soft_deviations"]))

        if shelf["reviews_required"]:
            print("  REVIEW:", ", ".join(shelf["reviews_required"]))

        if shelf["colour_sequence"].get("status") == "data_limitation":
            print(
                "  DATA LIMITATION: exact colour sequence cannot be evaluated "
                "from current catalog colour granularity"
            )
        if shelf.get("fast_moving_data", {}).get("status") == "unavailable":
            print(
                "  DATA LIMITATION: fast-moving data is unavailable; "
                "no fast-moving assumption is being made"
            )

        missing = shelf["missing_products"]["details"]
        for item in missing:
            occupant = item["destination_occupant_name"]
            if occupant:
                print(
                    f"  MISSING: {item['product_name']} "
                    f"expected slot {item['expected_slot']} "
                    f"but occupied by {occupant}"
                )
            else:
                print(
                    f"  MISSING: {item['product_name']} "
                    f"expected slot {item['expected_slot']}"
                )

            if item.get("potential_excess_facing"):
                print(
                    f"    ROOT-CAUSE CANDIDATE: "
                    f"{item['destination_occupant_name']} has "
                    f"{item['occupant_actual_facings']} facing(s), "
                    f"expected {item['occupant_expected_facings']}; "
                    f"fast-moving={item['occupant_fast_moving_status']}"
                )

    print("=" * 72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a rack photo's actual map against merchandising rules."
    )
    parser.add_argument(
        "actual_map",
        type=Path,
        help="Path to generated actual_map JSON",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=DEFAULT_RULES,
        help=f"Rules JSON (default: {DEFAULT_RULES})",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=DEFAULT_EXPECTED,
        help=f"Expected reference map (default: {DEFAULT_EXPECTED})",
    )
    parser.add_argument(
        "--products",
        type=Path,
        default=DEFAULT_PRODUCTS,
        help=f"Product master Excel (default: {DEFAULT_PRODUCTS})",
    )
    parser.add_argument(
        "--oos",
        nargs="*",
        default=[],
        help="Product IDs selected by staff as out of stock",
    )
    parser.add_argument(
        "--oos-file",
        type=Path,
        default=None,
        help="JSON file containing staff-selected OOS product IDs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.actual_map.exists():
        raise FileNotFoundError(f"Actual map not found: {args.actual_map}")
    if not args.rules.exists():
        raise FileNotFoundError(f"Rules file not found: {args.rules}")
    if not args.expected.exists():
        raise FileNotFoundError(f"Expected map not found: {args.expected}")
    if not args.products.exists():
        raise FileNotFoundError(f"Product master not found: {args.products}")

    actual = load_json(args.actual_map)
    expected = load_json(args.expected)
    rules = load_json(args.rules)
    catalog = load_product_master(args.products)

    oos_ids = {str(pid).strip() for pid in args.oos if str(pid).strip()}

    if args.oos_file:
        oos_payload = load_json(args.oos_file)
        if get_oos_ids is None:
            raise ImportError(
                "oos_filter.py is required when using --oos-file."
            )
        oos_ids.update(get_oos_ids(oos_payload))

    # Validate the selected OOS state through the dedicated OOS layer.
    # Keep the original expected map intact: analyze_rack uses the OOS IDs to
    # build both the active expected view and the preserved OOS metadata.
    if oos_ids and apply_oos_filter is not None:
        apply_oos_filter(expected, sorted(oos_ids))

    result = analyze_rack(actual, expected, rules, catalog, sorted(oos_ids))

    output_path = args.output
    if output_path is None:
        output_path = Path("data/analyses") / (
            f"analysis_{args.actual_map.stem}.json"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print_summary(result)
    print(f"\nFull analysis written to: {output_path}")


if __name__ == "__main__":
    main()