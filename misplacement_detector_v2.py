#!/usr/bin/env python3
"""
SMART PLANOGRAM — MISPLACEMENT DETECTOR v2

Detect products that are physically on the wrong shelf.

Evidence sources:
  1. actual_map      = where the product is now
  2. expected_map    = where the product should be
  3. merchandising rules = what categories are allowed on each shelf
  4. analyzer JSON   = supporting diagnostics

This detector DOES NOT authorize physical movement.
It only identifies product-level misplacement with evidence.

Example:
  python misplacement_detector_v2.py ^
    data\analyses\analysis_actual_map_wrongshelf.json ^
    --actual data\actual_maps\actual_map_wrongshelf.json ^
    --expected data\\expected_map_BTM_CH01.json ^
    --rules data\\merchandising_rules_v2.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


VERSION = "2.0"


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
        or item.get("sku")
        or ""
    )


def product_name(item: Dict[str, Any]) -> str:
    return str(
        item.get("product_name")
        or item.get("name")
        or item.get("product")
        or product_id(item)
    )


def shelf_number(item: Dict[str, Any]) -> Any:
    return (
        item.get("shelf_number")
        or item.get("shelf")
        or item.get("number")
        or item.get("shelf_id")
    )


def slot_number(item: Dict[str, Any]) -> Optional[int]:
    for key in (
        "slot",
        "position",
        "actual_slot",
        "expected_slot",
        "index",
    ):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def shelf_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in (
        "shelves",
        "shelf_map",
        "shelf_layout",
        "shelf_analysis",
        "shelf_results",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return value

    for parent_key in ("rack", "layout", "map"):
        parent = data.get(parent_key)
        if isinstance(parent, dict):
            for key in (
                "shelves",
                "shelf_map",
                "shelf_layout",
                "shelf_analysis",
            ):
                value = parent.get(key)
                if isinstance(value, list):
                    return value

    return []


def products_in_shelf(shelf: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in (
        "products",
        "items",
        "actual_products",
        "placements",
        "expected_products",
        "positions",
    ):
        value = shelf.get(key)
        if isinstance(value, list):
            return value
    return []


def product_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    for shelf in shelf_list(data):
        shelf_no = shelf_number(shelf)

        for item in products_in_shelf(shelf):
            if not isinstance(item, dict):
                continue

            pid = product_id(item)
            if not pid:
                continue

            result.append(
                {
                    "product_id": pid,
                    "product_name": product_name(item),
                    "shelf": (
                        item.get("shelf")
                        or item.get("shelf_number")
                        or item.get("current_shelf")
                        or shelf_no
                    ),
                    "slot": slot_number(item),
                    "raw": item,
                }
            )

    if result:
        return result

    # Support flat product maps.
    for key in (
        "products",
        "items",
        "placements",
        "product_positions",
    ):
        values = data.get(key)
        if not isinstance(values, list):
            continue

        for item in values:
            if not isinstance(item, dict):
                continue

            pid = product_id(item)
            if not pid:
                continue

            result.append(
                {
                    "product_id": pid,
                    "product_name": product_name(item),
                    "shelf": (
                        item.get("shelf")
                        or item.get("shelf_number")
                        or item.get("current_shelf")
                    ),
                    "slot": slot_number(item),
                    "raw": item,
                }
            )

    return result


def expected_index(data: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not data:
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    for record in product_records(data):
        result[norm(record["product_id"])] = record

    # Expected maps can also expose missing/expected products inside shelves.
    for shelf in shelf_list(data):
        shelf_no = shelf_number(shelf)

        for key in (
            "missing_products",
            "expected_missing",
            "missing_expected_products",
        ):
            values = shelf.get(key)

            if isinstance(values, dict):
                values = values.get("details", [])

            if not isinstance(values, list):
                continue

            for item in values:
                if not isinstance(item, dict):
                    continue

                pid = str(
                    item.get("product_id")
                    or item.get("expected_product_id")
                    or item.get("id")
                    or ""
                )

                if not pid:
                    continue

                result.setdefault(
                    norm(pid),
                    {
                        "product_id": pid,
                        "product_name": product_name(item),
                        "shelf": shelf_no,
                        "slot": slot_number(item),
                        "raw": item,
                    },
                )

    return result


def rule_shelves(rules: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rules:
        return []

    for key in ("shelves", "shelf_rules", "rules"):
        value = rules.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            result = []

            for key_name, rule in value.items():
                if isinstance(rule, dict):
                    item = dict(rule)
                    item.setdefault("shelf", key_name)
                    result.append(item)

            if result:
                return result

    return []


def shelf_rule(
    rules: Optional[Dict[str, Any]],
    shelf_no: Any,
) -> Dict[str, Any]:
    for rule in rule_shelves(rules):
        rule_shelf = (
            rule.get("shelf")
            or rule.get("shelf_number")
            or rule.get("number")
            or rule.get("id")
        )

        if str(rule_shelf) == str(shelf_no):
            return rule

    return {}


def allowed_categories(rule: Dict[str, Any]) -> Set[str]:
    value = (
        rule.get("allowed_categories")
        or rule.get("allowed_category")
        or rule.get("categories")
        or rule.get("category")
    )

    if value is None:
        return set()

    if isinstance(value, str):
        return {norm(value)}

    if isinstance(value, list):
        return {norm(x) for x in value if str(x).strip()}

    return set()


def product_category(
    record: Dict[str, Any],
    rules: Optional[Dict[str, Any]],
) -> str:
    raw = record.get("raw", {})

    for key in (
        "category",
        "category_name",
        "product_category",
        "super_category",
        "super_category_name",
    ):
        if raw.get(key) is not None:
            return str(raw[key])

    # Optional product attributes in rules.
    if rules:
        for key in ("products", "product_attributes", "catalog"):
            values = rules.get(key)

            if isinstance(values, dict):
                attributes = values.get(record["product_id"])
                if isinstance(attributes, dict):
                    for attr in (
                        "category",
                        "category_name",
                        "product_category",
                        "super_category",
                    ):
                        if attributes.get(attr) is not None:
                            return str(attributes[attr])

    return ""


def category_mismatch_reason(
    record: Dict[str, Any],
    rules: Optional[Dict[str, Any]],
) -> Optional[str]:
    if not rules:
        return None

    rule = shelf_rule(rules, record.get("shelf"))
    allowed = allowed_categories(rule)

    if not allowed:
        return None

    category = product_category(record, rules)

    if not category:
        return None

    if norm(category) not in allowed:
        return (
            f"Product category '{category}' is not allowed on "
            f"Shelf {record.get('shelf')}; allowed categories: "
            f"{', '.join(sorted(allowed))}"
        )

    return None


def analyzer_product_evidence(
    analysis: Dict[str, Any],
    product_id_value: str,
) -> List[str]:
    """
    Only accept product-specific analyzer evidence.
    A generic shelf-level HARD: category flag is NOT enough.
    """
    evidence: List[str] = []

    for shelf in shelf_list(analysis):
        category = shelf.get("category")

        if isinstance(category, dict):
            candidates = []

            for key in (
                "failures",
                "failure_details",
                "violations",
                "details",
                "mismatches",
                "product_failures",
                "wrong_products",
                "misplaced_products",
            ):
                value = category.get(key)

                if isinstance(value, list):
                    candidates.extend(value)

            for item in candidates:
                if not isinstance(item, dict):
                    continue

                failure_id = str(
                    item.get("product_id")
                    or item.get("actual_product_id")
                    or item.get("id")
                    or ""
                )

                if norm(failure_id) == norm(product_id_value):
                    evidence.append(
                        str(
                            item.get("reason")
                            or item.get("diagnosis")
                            or item.get("message")
                            or "Analyzer product-level category evidence."
                        )
                    )

        for key in (
            "wrong_products",
            "misplaced_products",
            "misplaced",
            "wrong_category_products",
        ):
            values = shelf.get(key)

            if not isinstance(values, list):
                continue

            for item in values:
                if not isinstance(item, dict):
                    continue

                failure_id = str(
                    item.get("product_id")
                    or item.get("actual_product_id")
                    or item.get("id")
                    or ""
                )

                if norm(failure_id) == norm(product_id_value):
                    evidence.append(
                        str(
                            item.get("reason")
                            or item.get("diagnosis")
                            or item.get("message")
                            or "Analyzer product-level evidence."
                        )
                    )

    return evidence


def detect_misplacements(
    analysis: Dict[str, Any],
    actual: Dict[str, Any],
    expected: Dict[str, Any],
    rules: Dict[str, Any],
    oos: Set[str],
) -> List[Dict[str, Any]]:
    actual_records = product_records(actual)
    expected_by_product = expected_index(expected)

    # If actual_map schema is unavailable, fall back to the analyzer's
    # product placements.
    if not actual_records:
        actual_records = product_records(analysis)

    results: Dict[str, Dict[str, Any]] = {}

    for actual_record in actual_records:
        pid = actual_record["product_id"]
        name = actual_record["product_name"]

        if norm(pid) in oos or norm(name) in oos:
            continue

        evidence: List[Dict[str, Any]] = []

        expected_record = expected_by_product.get(norm(pid))

        # Evidence A: expected map says this product belongs on another shelf.
        if expected_record:
            current_shelf = actual_record.get("shelf")
            expected_shelf = expected_record.get("shelf")

            if (
                current_shelf is not None
                and expected_shelf is not None
                and str(current_shelf) != str(expected_shelf)
            ):
                evidence.append(
                    {
                        "type": "expected_map",
                        "reason": (
                            f"Current shelf is {current_shelf}; "
                            f"expected shelf is {expected_shelf}."
                        ),
                    }
                )

        # Evidence B: shelf rules say this product's category is not allowed.
        rule_reason = category_mismatch_reason(actual_record, rules)

        if rule_reason:
            evidence.append(
                {
                    "type": "shelf_rule",
                    "reason": rule_reason,
                }
            )

        # Evidence C: analyzer product-specific evidence.
        for reason in analyzer_product_evidence(
            analysis,
            pid,
        ):
            evidence.append(
                {
                    "type": "analyzer",
                    "reason": reason,
                }
            )

        if not evidence:
            continue

        expected_shelf = (
            expected_record.get("shelf")
            if expected_record
            else None
        )

        expected_slot = (
            expected_record.get("slot")
            if expected_record
            else None
        )

        # A product is MISPLACED only when the expected map proves that
        # its intended shelf differs from its current shelf.
        # Analyzer/rule evidence is supporting evidence only.
        truly_misplaced = (
            expected_shelf is not None
            and actual_record.get("shelf") is not None
            and str(actual_record.get("shelf"))
            != str(expected_shelf)
        )

        # Never create a relocation candidate when the product is already
        # on the shelf assigned to it by the expected map.
        if not truly_misplaced:
            continue

        key = norm(pid)

        if key not in results:
            results[key] = {
                "product_id": pid,
                "product_name": name,
                "current_shelf": actual_record.get("shelf"),
                "current_slot": actual_record.get("slot"),
                "expected_shelf": expected_shelf,
                "expected_slot": expected_slot,
                "status": "MISPLACED",
                "evidence": evidence,
                "correction_authorized": False,
                "correction_note": (
                    "Detection only. A physical move must be validated "
                    "by correction_engine_v2."
                ),
            }
        else:
            existing = results[key]
            existing["evidence"].extend(evidence)

            if existing["expected_shelf"] is None:
                existing["expected_shelf"] = expected_shelf

            if existing["expected_slot"] is None:
                existing["expected_slot"] = expected_slot

    # Deduplicate evidence.
    for record in results.values():
        unique = []
        seen = set()

        for evidence in record["evidence"]:
            signature = json.dumps(
                evidence,
                sort_keys=True,
                ensure_ascii=False,
            )

            if signature not in seen:
                seen.add(signature)
                unique.append(evidence)

        record["evidence"] = unique

    output = list(results.values())

    output.sort(
        key=lambda x: (
            str(x.get("current_shelf")),
            (
                x.get("current_slot")
                if x.get("current_slot") is not None
                else 999999
            ),
        )
    )

    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect products that are on the wrong shelf."
    )

    parser.add_argument(
        "analysis",
        help="shelf_analyzer analysis JSON",
    )

    parser.add_argument(
        "--actual",
        required=True,
        help="actual_map JSON from the staff photo",
    )

    parser.add_argument(
        "--expected",
        required=True,
        help="expected_map JSON for the rack",
    )

    parser.add_argument(
        "--rules",
        required=True,
        help="merchandising_rules_v2.json",
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
        help="Product IDs/names to exclude",
    )

    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    actual_path = Path(args.actual)
    expected_path = Path(args.expected)
    rules_path = Path(args.rules)

    for path in (
        analysis_path,
        actual_path,
        expected_path,
        rules_path,
    ):
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

    analysis = load_json(analysis_path)
    actual = load_json(actual_path)
    expected = load_json(expected_path)
    rules = load_json(rules_path)

    oos = {
        norm(x)
        for x in args.oos
        if str(x).strip()
    }

    misplacements = detect_misplacements(
        analysis,
        actual,
        expected,
        rules,
        oos,
    )

    shelves = shelf_list(actual)

    rack = (
        actual.get("rack")
        or actual.get("rack_id")
        or analysis.get("rack")
        or analysis.get("rack_id")
        or "UNKNOWN"
    )

    output = {
        "detector": "misplacement_detector_v2",
        "detector_version": VERSION,
        "rack": rack,
        "sources": {
            "analysis": str(analysis_path),
            "actual": str(actual_path),
            "expected": str(expected_path),
            "rules": str(rules_path),
        },
        "oos_products": sorted(oos),
        "summary": {
            "shelves_analyzed": len(shelves),
            "misplaced_products": len(misplacements),
            "oos_excluded": len(oos),
            "classification_rule": (
                "Only products whose actual shelf differs from their "
                "expected-map shelf are classified as MISPLACED."
            ),
        },
        "misplaced_products": misplacements,
        "safety_boundary": (
            "This detector identifies product-level misplacement. "
            "It does not recommend or authorize a physical movement."
        ),
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            analysis_path.parent
            / f"misplacements_v2_{analysis_path.stem}.json"
        )

    write_json(output_path, output)

    print("=" * 72)
    print("SMART PLANOGRAM — MISPLACEMENT DETECTOR v2")
    print("=" * 72)
    print(f"Rack: {rack}")
    print(f"Shelves analyzed       : {len(shelves)}")
    print(
        "Misplaced products     : "
        f"{output['summary']['misplaced_products']}"
    )
    print(f"OOS excluded           : {len(oos)}")
    print("-" * 72)

    if not misplacements:
        print("NO PRODUCT-LEVEL MISPLACEMENTS PROVEN")
    else:
        for item in misplacements:
            print(
                f"{item['status']}: "
                f"{item['product_name']} "
                f"({item['product_id']})"
            )

            print(
                f"  Current : Shelf {item['current_shelf']}"
                + (
                    f", slot {item['current_slot']}"
                    if item["current_slot"] is not None
                    else ""
                )
            )

            if item["expected_shelf"] is not None:
                target = f"Shelf {item['expected_shelf']}"
                if item["expected_slot"] is not None:
                    target += f", slot {item['expected_slot']}"
            else:
                target = "expected shelf not proven"

            print(f"  Target  : {target}")

            for evidence in item["evidence"]:
                print(
                    f"  Evidence ({evidence['type']}): "
                    f"{evidence['reason']}"
                )

            print()

    print("-" * 72)
    print(f"Detection written to: {output_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
