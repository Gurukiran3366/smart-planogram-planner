#!/usr/bin/env python3
"""
OOS FILTER — Smart Planogram Planner

Purpose
-------
Apply staff-selected out-of-stock (OOS) products to an expected planogram
without deleting their merchandising position.

Rules
-----
1. An OOS product is excluded from missing-product compliance checks.
2. An OOS product is excluded from correction candidates.
3. Its preferred slot/facing metadata is preserved.
4. OOS does NOT reduce the physical shelf capacity.
5. OOS does NOT automatically create an empty-space correction.
6. An unknown product is NOT treated as OOS.
7. The filter is intentionally independent of photo detection and correction.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_product_ids(values: Iterable[Any]) -> Set[str]:
    result = set()
    for value in values or []:
        if value is None:
            continue
        if isinstance(value, dict):
            value = value.get("product_id") or value.get("id")
        if value is not None:
            result.add(str(value).strip())
    return result


def get_oos_ids(oos_input: Any) -> Set[str]:
    """
    Accept either:
      ["SKU1", "SKU2"]
    or:
      {"out_of_stock_products": ["SKU1", "SKU2"]}
    or:
      {"products": [{"product_id": "SKU1"}, ...]}
    """
    if oos_input is None:
        return set()

    if isinstance(oos_input, list):
        return normalize_product_ids(oos_input)

    if isinstance(oos_input, dict):
        for key in (
            "out_of_stock_products",
            "oos_products",
            "products",
            "selected_products",
        ):
            if key in oos_input:
                return normalize_product_ids(oos_input[key])

    raise ValueError(
        "Unsupported OOS input. Use a list of product IDs or an object "
        "containing out_of_stock_products/oos_products/products."
    )


def get_expected_shelves(expected_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    shelves = expected_map.get("shelves", [])
    if isinstance(shelves, dict):
        normalized = []
        for shelf_id, shelf in shelves.items():
            shelf_copy = deepcopy(shelf)
            shelf_copy.setdefault("shelf_id", int(shelf_id) if str(shelf_id).isdigit() else shelf_id)
            normalized.append(shelf_copy)
        return normalized
    return shelves


def get_products(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("products", "expected_products", "product_list"):
        products = shelf.get(key)
        if isinstance(products, list):
            return products
    return []


def apply_oos_filter(
    expected_map: Dict[str, Any],
    oos_product_ids: Iterable[str],
) -> Dict[str, Any]:
    """
    Preserve the expected planogram but annotate OOS products.

    The filtered expected product list excludes OOS products from active
    compliance/correction analysis while preserving their original slot,
    facing, and merchandising metadata under oos_products.
    """
    oos_ids = normalize_product_ids(oos_product_ids)
    result = deepcopy(expected_map)

    result.setdefault("oos_filter", {})
    result["oos_filter"].update({
        "enabled": True,
        "selected_product_ids": sorted(oos_ids),
        "physical_capacity_preserved": True,
        "excluded_from_missing_check": True,
        "excluded_from_correction": True,
    })

    total_oos = 0
    total_active = 0

    for shelf in get_expected_shelves(result):
        products = get_products(shelf)

        active_products = []
        oos_products = []

        for product in products:
            pid = str(product.get("product_id", "")).strip()

            if pid and pid in oos_ids:
                oos_record = deepcopy(product)
                oos_record["status"] = "out_of_stock"
                oos_record["excluded_from_missing_check"] = True
                oos_record["excluded_from_correction"] = True
                oos_record["preferred_position_preserved"] = True
                oos_products.append(oos_record)
                total_oos += 1
            else:
                active_products.append(product)
                total_active += 1

        # Preserve the original shelf capacity.
        original_capacity = shelf.get("capacity")

        shelf["active_expected_products"] = active_products
        shelf["oos_products"] = oos_products
        shelf["active_expected_product_count"] = len(active_products)
        shelf["oos_product_count"] = len(oos_products)

        if original_capacity is not None:
            shelf["physical_capacity"] = original_capacity

        # The analyzer should use active_expected_products.
        shelf["analysis_expected_products_key"] = "active_expected_products"

    result["oos_filter"]["total_oos_products"] = total_oos
    result["oos_filter"]["total_active_expected_products"] = total_active

    return result


def print_summary(filtered_map: Dict[str, Any]) -> None:
    meta = filtered_map.get("oos_filter", {})

    print("=" * 72)
    print("SMART PLANOGRAM — OOS FILTER")
    print("=" * 72)
    print(f"OOS products selected : {meta.get('total_oos_products', 0)}")
    print(f"Active expected       : {meta.get('total_active_expected_products', 0)}")
    print("Physical capacity     : PRESERVED")
    print("OOS missing check     : EXCLUDED")
    print("OOS corrections      : EXCLUDED")
    print()

    for shelf in get_expected_shelves(filtered_map):
        shelf_id = shelf.get("shelf_id")
        oos_products = shelf.get("oos_products", [])
        active_count = shelf.get("active_expected_product_count", 0)
        capacity = shelf.get("physical_capacity", shelf.get("capacity"))

        print(f"Shelf {shelf_id}: active={active_count} | capacity={capacity}")

        if oos_products:
            for product in oos_products:
                print(
                    f"  OOS: {product.get('product_name', product.get('product_id'))}"
                    f" | slot={product.get('slot_start')}"
                    f" | preferred_position_preserved=True"
                )

    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply staff-selected OOS products to an expected planogram."
    )
    parser.add_argument(
        "expected_map",
        help="Path to expected_map JSON",
    )
    parser.add_argument(
        "--oos",
        nargs="*",
        default=[],
        help="Product IDs selected as out of stock",
    )
    parser.add_argument(
        "--oos-file",
        help="Optional JSON file containing selected OOS product IDs",
    )
    parser.add_argument(
        "--output",
        help="Output JSON path",
    )

    args = parser.parse_args()

    expected_path = Path(args.expected_map)
    expected_map = load_json(expected_path)

    selected = list(args.oos)

    if args.oos_file:
        selected.extend(
            get_oos_ids(load_json(Path(args.oos_file)))
        )

    filtered = apply_oos_filter(expected_map, selected)

    output = (
        Path(args.output)
        if args.output
        else expected_path.with_name(
            expected_path.stem + "_oos_filtered.json"
        )
    )

    save_json(filtered, output)
    print_summary(filtered)
    print(f"\nFiltered map written to: {output}")


if __name__ == "__main__":
    main()
