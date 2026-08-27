#!/usr/bin/env python3
"""
SMART PLANOGRAM — MISPLACEMENT DETECTOR

Purpose
-------
Identify products that are physically present on a shelf but do not belong
to that shelf according to the merchandising analysis produced by
shelf_analyzer.py.

This module deliberately DOES NOT recommend physical corrections.
It answers only:

    "Which products are misplaced, where are they now, and why?"

Correction planning belongs to correction_engine_v2.py.

Input
-----
    data/actual_maps/*.json
    data/analyses/analysis_*.json

The primary input is the shelf_analyzer analysis JSON because it already
contains the validated product/shelf/category comparison.

CLI
---
    python misplacement_detector.py data/analyses/analysis_actual_map_wrongshelf.json

Optional:
    --output PATH
    --oos PRODUCT_ID [PRODUCT_ID ...]

Output
------
A JSON containing:
- misplaced products
- shelf-level summaries
- evidence from hard category violations
- current shelf/slot
- expected shelf information when the analyzer provides it
- OOS exclusions
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


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


def slot(item: Dict[str, Any]) -> Optional[int]:
    for key in ("slot", "position", "actual_slot", "index"):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def shelf_number(shelf: Dict[str, Any]) -> Any:
    return (
        shelf.get("shelf_number")
        or shelf.get("shelf")
        or shelf.get("number")
        or shelf.get("shelf_id")
    )


def shelves_from_analysis(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = analysis.get("shelves")
    if isinstance(value, list):
        return value

    for key in ("shelf_analysis", "shelf_results"):
        value = analysis.get(key)
        if isinstance(value, list):
            return value

    return []


def actual_products(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("products", "actual_products", "items", "placements"):
        value = shelf.get(key)
        if isinstance(value, list):
            return value
    return []


def category_status(shelf: Dict[str, Any]) -> Dict[str, Any]:
    """
    Find the analyzer's category diagnostic.

    We support the structured form used by the current analyzer and avoid
    deriving a category violation merely from a generic NEEDS_ACTION status.
    """
    value = shelf.get("category")

    if isinstance(value, dict):
        return value

    diagnostics = shelf.get("diagnostics")
    if isinstance(diagnostics, dict):
        value = diagnostics.get("category")
        if isinstance(value, dict):
            return value

    checks = shelf.get("checks")
    if isinstance(checks, dict):
        value = checks.get("category")
        if isinstance(value, dict):
            return value

    return {}


def extract_category_failures(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract product-specific category failures.

    Expected analyzer representation can vary slightly, so this function
    checks common structured fields but never turns a plain shelf-level
    'category' failure into a product-level accusation without product
    evidence.
    """
    cat = category_status(shelf)
    result: List[Dict[str, Any]] = []

    for key in (
        "failures",
        "failure_details",
        "violations",
        "details",
        "mismatches",
        "product_failures",
    ):
        value = cat.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result.append(item)

    # Some analyzer outputs expose an explicit wrong-product list.
    for key in (
        "wrong_products",
        "misplaced_products",
        "misplaced",
        "wrong_category_products",
    ):
        value = shelf.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result.append(item)

    return result


def build_actual_product_index(
    shelves: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}

    for shelf in shelves:
        sn = shelf_number(shelf)

        for item in actual_products(shelf):
            product_id = pid(item)
            if not product_id:
                continue

            index[norm(product_id)] = {
                "product_id": product_id,
                "product_name": pname(item),
                "current_shelf": sn,
                "current_slot": slot(item),
                "item": item,
            }

    return index


def get_category_evidence(
    shelf: Dict[str, Any],
    actual_index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert analyzer category-failure records into normalized product-level
    evidence.

    If the analyzer's category check contains no product-level evidence,
    return an empty list rather than guessing.
    """
    evidence = []

    for failure in extract_category_failures(shelf):
        product_id = str(
            failure.get("product_id")
            or failure.get("actual_product_id")
            or failure.get("id")
            or ""
        )

        if not product_id:
            continue

        actual = actual_index.get(norm(product_id))
        if not actual:
            continue

        evidence.append(
            {
                "product_id": actual["product_id"],
                "product_name": actual["product_name"],
                "current_shelf": actual["current_shelf"],
                "current_slot": actual["current_slot"],
                "reason": str(
                    failure.get("reason")
                    or failure.get("diagnosis")
                    or failure.get("message")
                    or "Product-level category violation reported by analyzer."
                ),
                "evidence_type": "category",
            }
        )

    return evidence


def get_expected_shelf_for_product(
    analysis: Dict[str, Any],
    product_id: str,
) -> Optional[Any]:
    """
    Search expected/missing product records for a product's intended shelf.

    This is evidence only. It does not imply that moving the product is safe.
    """
    target = norm(product_id)

    for shelf in shelves_from_analysis(analysis):
        sn = shelf_number(shelf)

        missing = shelf.get("missing_products")
        if isinstance(missing, dict):
            details = missing.get("details", [])
            if isinstance(details, list):
                for item in details:
                    if not isinstance(item, dict):
                        continue
                    candidate_id = str(
                        item.get("product_id")
                        or item.get("expected_product_id")
                        or ""
                    )
                    if norm(candidate_id) == target:
                        return sn

        for key in ("missing_expected_products", "missing_products_details"):
            details = shelf.get(key)
            if isinstance(details, list):
                for item in details:
                    if not isinstance(item, dict):
                        continue
                    candidate_id = str(
                        item.get("product_id")
                        or item.get("expected_product_id")
                        or ""
                    )
                    if norm(candidate_id) == target:
                        return sn

    return None


def collect_misplacements(
    analysis: Dict[str, Any],
    oos: Set[str],
) -> List[Dict[str, Any]]:
    shelves = shelves_from_analysis(analysis)
    actual_index = build_actual_product_index(shelves)

    all_evidence: List[Dict[str, Any]] = []

    for shelf in shelves:
        all_evidence.extend(
            get_category_evidence(
                shelf,
                actual_index,
            )
        )

    # Deduplicate product-level evidence.
    dedup: Dict[str, Dict[str, Any]] = {}

    for item in all_evidence:
        key = norm(item["product_id"])

        if key in dedup:
            # Preserve the strongest explanation if multiple diagnostics
            # identify the same product.
            old = dedup[key]
            if item.get("reason") and not old.get("reason"):
                old["reason"] = item["reason"]
            continue

        dedup[key] = item

    result: List[Dict[str, Any]] = []

    for key, item in dedup.items():
        if key in oos or norm(item["product_name"]) in oos:
            continue

        expected_shelf = get_expected_shelf_for_product(
            analysis,
            item["product_id"],
        )

        current_shelf = item["current_shelf"]

        record = {
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "current_shelf": current_shelf,
            "current_slot": item["current_slot"],
            "expected_shelf": expected_shelf,
            "status": (
                "MISPLACED"
                if expected_shelf is not None
                and str(expected_shelf) != str(current_shelf)
                else "SHELF_RULE_VIOLATION"
            ),
            "reason": item["reason"],
            "evidence_type": item["evidence_type"],
            "oos": False,
            "correction_authorized": False,
            "correction_note": (
                "Detection only. Do not move automatically until "
                "correction_engine_v2 validates the destination."
            ),
        }

        result.append(record)

    result.sort(
        key=lambda x: (
            str(x.get("current_shelf")),
            x.get("current_slot")
            if x.get("current_slot") is not None
            else 999999,
        )
    )

    return result


def build_shelf_summary(
    analysis: Dict[str, Any],
    misplacements: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    shelves = shelves_from_analysis(analysis)
    result = []

    for shelf in shelves:
        sn = shelf_number(shelf)
        products = [
            x for x in misplacements
            if str(x.get("current_shelf")) == str(sn)
        ]

        result.append(
            {
                "shelf": sn,
                "misplaced_count": len(products),
                "products": [
                    {
                        "product_id": x["product_id"],
                        "product_name": x["product_name"],
                        "slot": x["current_slot"],
                        "status": x["status"],
                        "expected_shelf": x["expected_shelf"],
                    }
                    for x in products
                ],
            }
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect products that are on the wrong shelf."
    )
    parser.add_argument(
        "analysis",
        help="shelf_analyzer analysis JSON",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path",
    )
    parser.add_argument(
        "--oos",
        nargs="*",
        default=[],
        help="Product IDs/names to exclude from detection",
    )

    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    if not analysis_path.exists():
        raise FileNotFoundError(
            f"Analysis file not found: {analysis_path}"
        )

    analysis = load_json(analysis_path)

    oos = {norm(x) for x in args.oos if str(x).strip()}

    misplacements = collect_misplacements(
        analysis,
        oos,
    )

    shelves = shelves_from_analysis(analysis)

    rack = (
        analysis.get("rack")
        or analysis.get("rack_id")
        or analysis.get("metadata", {}).get("rack")
        or "UNKNOWN"
    )

    output = {
        "detector": "misplacement_detector",
        "detector_version": VERSION,
        "rack": rack,
        "source_analysis": str(analysis_path),
        "oos_products": sorted(oos),
        "summary": {
            "shelves_analyzed": len(shelves),
            "misplaced_products": len(misplacements),
            "oos_excluded": len(oos),
        },
        "misplaced_products": misplacements,
        "shelf_summary": build_shelf_summary(
            analysis,
            misplacements,
        ),
        "important_boundary": (
            "This detector identifies misplaced products only. "
            "It does not authorize or recommend physical movement. "
            "Correction safety belongs to correction_engine_v2."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            analysis_path.parent
            / f"misplacements_{analysis_path.stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — MISPLACEMENT DETECTOR")
    print("=" * 72)
    print(f"Rack: {rack}")
    print(f"Shelves analyzed    : {len(shelves)}")
    print(f"Misplaced products  : {len(misplacements)}")
    print(f"OOS excluded        : {len(oos)}")
    print("-" * 72)

    if not misplacements:
        print("NO PRODUCT-LEVEL MISPLACEMENTS PROVEN")
        print()
        print(
            "The analyzer may still contain shelf-level category violations, "
            "but no product-level evidence was sufficient to label a product "
            "as misplaced."
        )
    else:
        for item in misplacements:
            current = (
                f"Shelf {item['current_shelf']}"
                if item["current_shelf"] is not None
                else "Shelf ?"
            )
            if item["current_slot"] is not None:
                current += f", slot {item['current_slot']}"

            expected = (
                f"Shelf {item['expected_shelf']}"
                if item["expected_shelf"] is not None
                else "expected shelf not proven"
            )

            print(
                f"{item['status']}: {item['product_name']} "
                f"({item['product_id']})"
            )
            print(f"  Current : {current}")
            print(f"  Target  : {expected}")
            print(f"  Reason  : {item['reason']}")
            print()

    print("-" * 72)
    print(f"Detection written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())