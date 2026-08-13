# compare_engine.py
"""
Milestone 4: The Comparison Engine (Complete Production Version)
Compares expected reference map against actual detected map.
Features:
- Slot-based positioning (accounts for facings)
- Zone tolerance for adjacent zones
- Out-of-stock awareness
- Multi-shelf product handling
- Clean, actionable correction messages
"""

import json
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from stock_status import load_today_oos

# ============================================================
# CONFIG
# ============================================================
EXPECTED_MAP_FILE = "data/expected_map_BTM_CH01.json"
PRODUCTS_FILE = "data/products.xlsx"
RULES_FILE = "data/chiller_rules.json"
COMPARISONS_DIR = Path("data/comparisons")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def zones_are_adjacent_or_equal(zone1, zone2):
    """
    Check if two zones are the same or adjacent.
    Zone ordering: left < center < right
    """
    if zone1 == zone2:
        return True
    zone_order = {"left": 0, "center": 1, "right": 2}
    if zone1 not in zone_order or zone2 not in zone_order:
        return False
    return abs(zone_order[zone1] - zone_order[zone2]) <= 1


def load_data(actual_map_file):
    """Load all required data files."""
    with open(EXPECTED_MAP_FILE, "r", encoding="utf-8") as f:
        expected = json.load(f)
    with open(actual_map_file, "r", encoding="utf-8") as f:
        actual = json.load(f)
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        rules = json.load(f)
    products_df = pd.read_excel(PRODUCTS_FILE)
    
    product_lookup = {}
    for _, row in products_df.iterrows():
        product_lookup[row["product_id"]] = {
            "product_name": row["product_name"],
            "brand": row["brand"],
            "commodity": row["commodity"],
            "colour_tone": row["colour_tone"],
            "size_band": row["size_band"],
            "is_fast_moving": bool(row.get("is_fast_moving", False)),
            "is_high_margin": bool(row.get("is_high_margin", False)),
            "is_water": bool(row.get("is_water", False)),
            "package_type": row.get("package_type", "")
        }
    
    return expected, actual, rules, product_lookup


def get_product_name(pid, product_lookup):
    """Get friendly product name, fallback to ID if not in catalog."""
    if pid in product_lookup:
        return product_lookup[pid]["product_name"]
    return pid.replace("_", " ").title()


def build_expected_index(expected):
    """Build index: {product_id: [{shelf, zone, slot_start, slot_end, facings}, ...]}"""
    index = {}
    for shelf in expected["shelves"]:
        shelf_num = shelf["shelf_number"]
        for product in shelf.get("products", []):
            pid = product["product_id"]
            if pid not in index:
                index[pid] = []
            index[pid].append({
                "shelf": shelf_num,
                "zone": product.get("zone", "unknown"),
                "slot_start": product.get("slot_start"),
                "slot_end": product.get("slot_end"),
                "facings": product.get("facings", 1)
            })
    return index


def build_actual_index(actual):
    """Build index: {product_id: [{shelf, zone, slot_start, slot_end, facings, confidence}, ...]}"""
    index = {}
    for shelf in actual["shelves"]:
        shelf_num = shelf["shelf_number"]
        for product in shelf.get("products", []):
            pid = product["product_id"]
            if pid not in index:
                index[pid] = []
            index[pid].append({
                "shelf": shelf_num,
                "zone": product.get("zone", "unknown"),
                "slot_start": product.get("slot_start"),
                "slot_end": product.get("slot_end"),
                "facings": product.get("facings", 1),
                "confidence": product.get("confidence", "high")
            })
    return index


def get_shelf_commodity_map(rules):
    """Extract shelf commodity map from rules."""
    for rule in rules["rules"]:
        if rule["rule_id"] == "CHILLER_SHELF_COMMODITY":
            return rule["shelf_commodity_map"]
    return {}


# ============================================================
# VIOLATION DETECTION
# ============================================================

def analyze_product_placement(pid, expected_locations, actual_locations, product_lookup):
    """
    Analyze a single product holistically across all shelves.
    Uses slot-based positioning with zone fallback.
    Handles multi-shelf products, out-of-stock, misplacements.
    """
    violations = []
    product_name = get_product_name(pid, product_lookup)
    
    # Check OOS status
    oos_products = load_today_oos()
    is_out_of_stock = pid in oos_products
    
    expected_shelves = {loc["shelf"] for loc in expected_locations}
    actual_shelves = {loc["shelf"] for loc in actual_locations}
    
    satisfied_shelves = expected_shelves & actual_shelves
    unsatisfied_shelves = expected_shelves - actual_shelves
    unexpected_shelves = actual_shelves - expected_shelves
    
    # For satisfied shelves, check position + facings
    for shelf_num in satisfied_shelves:
        exp_loc = next(l for l in expected_locations if l["shelf"] == shelf_num)
        act_loc = next(l for l in actual_locations if l["shelf"] == shelf_num)
        
        # SLOT-BASED POSITION CHECK
        exp_slot_start = exp_loc.get("slot_start")
        act_slot_start = act_loc.get("slot_start")
        
        if exp_slot_start is not None and act_slot_start is not None:
            slot_diff = abs(exp_slot_start - act_slot_start)
            
            if slot_diff == 0:
                pass  # Perfect match
            elif slot_diff <= 1:
                violations.append({
                    "type": "position_minor_shift",
                    "severity": "low",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "expected_slot": exp_slot_start,
                    "actual_slot": act_slot_start,
                    "description": f"{product_name} slightly off position on Shelf {shelf_num}",
                    "correction": f"Verify {product_name} on Shelf {shelf_num} (at slot {act_slot_start}, expected slot {exp_slot_start})"
                })
            elif slot_diff <= 2:
                direction = "right" if act_slot_start > exp_slot_start else "left"
                violations.append({
                    "type": "wrong_position",
                    "severity": "medium",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "expected_slot": exp_slot_start,
                    "actual_slot": act_slot_start,
                    "description": f"{product_name} in wrong position on Shelf {shelf_num}",
                    "correction": f"Move {product_name} on Shelf {shelf_num} from slot {act_slot_start} to slot {exp_slot_start} ({direction} by {slot_diff} slots)"
                })
            else:
                direction = "right" if act_slot_start > exp_slot_start else "left"
                violations.append({
                    "type": "wrong_position",
                    "severity": "high",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "expected_slot": exp_slot_start,
                    "actual_slot": act_slot_start,
                    "description": f"{product_name} significantly misplaced on Shelf {shelf_num}",
                    "correction": f"Move {product_name} on Shelf {shelf_num} from slot {act_slot_start} to slot {exp_slot_start} ({direction} by {slot_diff} slots)"
                })
        else:
            # Fallback to zone check if slot info missing
            if act_loc.get("zone") != exp_loc.get("zone") and act_loc.get("zone") != "unknown":
                if zones_are_adjacent_or_equal(exp_loc.get("zone", ""), act_loc.get("zone", "")):
                    severity = "low"
                    correction = f"Verify {product_name} position on Shelf {shelf_num}"
                else:
                    severity = "medium"
                    correction = f"Move {product_name} on Shelf {shelf_num} from {act_loc['zone']} to {exp_loc['zone']}"
                
                violations.append({
                    "type": "wrong_zone",
                    "severity": severity,
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "expected_zone": exp_loc.get("zone"),
                    "actual_zone": act_loc.get("zone"),
                    "description": f"{product_name} position issue on Shelf {shelf_num}",
                    "correction": correction
                })
        
        # Facing check
        if act_loc["facings"] < exp_loc["facings"]:
            violations.append({
                "type": "low_facing",
                "severity": "medium",
                "product_id": pid,
                "product_name": product_name,
                "shelf_number": shelf_num,
                "expected_facings": exp_loc["facings"],
                "actual_facings": act_loc["facings"],
                "description": f"{product_name} has too few facings on Shelf {shelf_num}",
                "correction": f"Increase {product_name} facings on Shelf {shelf_num} from {act_loc['facings']} to {exp_loc['facings']}"
            })
        elif act_loc["facings"] > exp_loc["facings"]:
            is_fast_moving = product_lookup.get(pid, {}).get("is_fast_moving", False)
            if not is_fast_moving:
                violations.append({
                    "type": "excess_facing_non_fast_moving",
                    "severity": "low",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "expected_facings": exp_loc["facings"],
                    "actual_facings": act_loc["facings"],
                    "description": f"{product_name} has extra facings on Shelf {shelf_num}",
                    "correction": f"Reduce {product_name} facings on Shelf {shelf_num} from {act_loc['facings']} to {exp_loc['facings']}"
                })
    
    # Handle misplacement — consolidated single message
    if unexpected_shelves and unsatisfied_shelves:
        wrong_shelves_str = ", ".join(f"Shelf {s}" for s in sorted(unexpected_shelves))
        correct_shelves = sorted(unsatisfied_shelves)
        
        if len(correct_shelves) == 1:
            target = correct_shelves[0]
            target_zone = next(l["zone"] for l in expected_locations if l["shelf"] == target)
            correction = f"Move {product_name} from {wrong_shelves_str} to Shelf {target} ({target_zone} zone)"
            description = f"{product_name} is on wrong shelf"
        else:
            targets_str = " OR ".join(f"Shelf {s}" for s in correct_shelves)
            correction = f"Move {product_name} from {wrong_shelves_str} to {targets_str}"
            description = f"{product_name} is on wrong shelf (belongs on multiple shelves)"
        
        violations.append({
            "type": "wrong_shelf",
            "severity": "high",
            "product_id": pid,
            "product_name": product_name,
            "actual_shelves": sorted(unexpected_shelves),
            "expected_shelves": correct_shelves,
            "description": description,
            "correction": correction
        })
    
    elif unexpected_shelves and not unsatisfied_shelves:
        wrong_shelves_str = ", ".join(f"Shelf {s}" for s in sorted(unexpected_shelves))
        correct_shelves_str = ", ".join(f"Shelf {s}" for s in sorted(expected_shelves))
        
        violations.append({
            "type": "duplicate_on_wrong_shelf",
            "severity": "medium",
            "product_id": pid,
            "product_name": product_name,
            "actual_extra_shelves": sorted(unexpected_shelves),
            "correct_shelves": sorted(expected_shelves),
            "description": f"{product_name} incorrectly duplicated on {wrong_shelves_str}",
            "correction": f"Remove extra {product_name} from {wrong_shelves_str} (correct location: {correct_shelves_str})"
        })
    
    elif unsatisfied_shelves and not unexpected_shelves and not satisfied_shelves:
        # Product not detected anywhere
        if is_out_of_stock:
            shelves_str = " AND ".join(f"Shelf {s}" for s in sorted(unsatisfied_shelves))
            violations.append({
                "type": "expected_but_out_of_stock",
                "severity": "info",
                "product_id": pid,
                "product_name": product_name,
                "expected_shelves": sorted(unsatisfied_shelves),
                "description": f"{product_name} is out of stock (marked by staff)",
                "correction": f"⚠️ {product_name} is OOS — consider substitution on {shelves_str}"
            })
        else:
            if len(unsatisfied_shelves) == 1:
                shelf = list(unsatisfied_shelves)[0]
                exp_loc = next(l for l in expected_locations if l["shelf"] == shelf)
                zone = exp_loc["zone"]
                description = f"{product_name} not detected — expected on Shelf {shelf}"
                correction = f"Verify {product_name} on Shelf {shelf} ({zone} zone). If missing, add it. If out of stock, mark as OOS."
            else:
                shelves_str = " AND ".join(f"Shelf {s}" for s in sorted(unsatisfied_shelves))
                description = f"{product_name} not detected — expected on multiple shelves"
                correction = f"Verify {product_name} on {shelves_str}. If missing, add it. If out of stock, mark as OOS."
            
            violations.append({
                "type": "missing_product",
                "severity": "high",
                "product_id": pid,
                "product_name": product_name,
                "expected_shelves": sorted(unsatisfied_shelves),
                "description": description,
                "correction": correction
            })
    
    elif unsatisfied_shelves and satisfied_shelves:
        # Partial placement
        if is_out_of_stock:
            missing_shelves_str = " AND ".join(f"Shelf {s}" for s in sorted(unsatisfied_shelves))
            present_shelves_str = ", ".join(f"Shelf {s}" for s in sorted(satisfied_shelves))
            violations.append({
                "type": "expected_but_out_of_stock",
                "severity": "info",
                "product_id": pid,
                "product_name": product_name,
                "description": f"{product_name} is OOS — only on {present_shelves_str}",
                "correction": f"⚠️ {product_name} OOS — cannot add to {missing_shelves_str}"
            })
        else:
            missing_shelves_str = " AND ".join(f"Shelf {s}" for s in sorted(unsatisfied_shelves))
            present_shelves_str = ", ".join(f"Shelf {s}" for s in sorted(satisfied_shelves))
            
            violations.append({
                "type": "missing_product_partial",
                "severity": "medium",
                "product_id": pid,
                "product_name": product_name,
                "missing_from_shelves": sorted(unsatisfied_shelves),
                "present_on_shelves": sorted(satisfied_shelves),
                "description": f"{product_name} present on {present_shelves_str} but not detected on {missing_shelves_str}",
                "correction": f"Verify {product_name} on {missing_shelves_str} (already confirmed on {present_shelves_str}). Add if missing."
            })
    
    return violations


def detect_unauthorized_products(actual_index, expected_index, shelf_commodity_map, product_lookup):
    """Products in actual that aren't expected AND don't match shelf commodity."""
    violations = []
    
    for pid, actual_locations in actual_index.items():
        if pid in expected_index:
            continue
        
        for loc in actual_locations:
            shelf_num = loc["shelf"]
            allowed_commodities = shelf_commodity_map.get(str(shelf_num), [])
            
            attrs = product_lookup.get(pid)
            product_name = get_product_name(pid, product_lookup)
            
            if attrs is None:
                violations.append({
                    "type": "unknown_product",
                    "severity": "medium",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "description": f"{product_name} detected but not in product catalog",
                    "correction": f"Verify {product_name} on Shelf {shelf_num} — either add to catalog or remove from chiller"
                })
                continue
            
            actual_commodity = attrs.get("commodity")
            if actual_commodity not in allowed_commodities:
                violations.append({
                    "type": "wrong_commodity_on_shelf",
                    "severity": "high",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": shelf_num,
                    "actual_commodity": actual_commodity,
                    "expected_commodities": allowed_commodities,
                    "description": f"{product_name} ({actual_commodity}) doesn't belong on Shelf {shelf_num}",
                    "correction": f"Remove {product_name} from Shelf {shelf_num} — this shelf is for {', '.join(allowed_commodities)}"
                })
    
    return violations


def detect_low_confidence_items(actual_index, product_lookup):
    """Info-level items needing manual verification."""
    warnings = []
    for pid, locations in actual_index.items():
        for loc in locations:
            if loc.get("confidence") == "low":
                product_name = get_product_name(pid, product_lookup)
                warnings.append({
                    "type": "low_confidence_detection",
                    "severity": "info",
                    "product_id": pid,
                    "product_name": product_name,
                    "shelf_number": loc["shelf"],
                    "description": f"AI is uncertain about {product_name} on Shelf {loc['shelf']}",
                    "correction": f"Manually verify {product_name} on Shelf {loc['shelf']}"
                })
    return warnings


# ============================================================
# MAIN COMPARISON FUNCTION
# ============================================================

def compare_maps(actual_map_file):
    """Main function: run all checks and return violation list."""
    print(f"\n{'='*70}")
    print(f"COMPARING: {actual_map_file}")
    print(f"    against: {EXPECTED_MAP_FILE}")
    print(f"{'='*70}\n")
    
    expected, actual, rules, product_lookup = load_data(actual_map_file)
    shelf_commodity_map = get_shelf_commodity_map(rules)
    
    expected_count = sum(len(s.get("products", [])) for s in expected["shelves"])
    actual_count = sum(len(s.get("products", [])) for s in actual["shelves"])
    
    print(f"✅ Loaded expected map ({expected_count} products expected)")
    print(f"✅ Loaded actual map ({actual_count} products detected)")
    print(f"✅ Loaded {len(product_lookup)} products from catalog\n")
    
    expected_index = build_expected_index(expected)
    actual_index = build_actual_index(actual)
    
    all_violations = []
    
    print("🔍 Analyzing expected products (placement, position, facings)...")
    for pid in set(expected_index.keys()):
        exp_locs = expected_index[pid]
        act_locs = actual_index.get(pid, [])
        violations = analyze_product_placement(pid, exp_locs, act_locs, product_lookup)
        all_violations.extend(violations)
    print(f"   Analyzed {len(expected_index)} expected products\n")
    
    print("🔍 Detecting unauthorized products...")
    unauth = detect_unauthorized_products(actual_index, expected_index, shelf_commodity_map, product_lookup)
    all_violations.extend(unauth)
    print(f"   Found {len(unauth)} unauthorized products\n")
    
    print("🔍 Flagging low-confidence detections...")
    low_conf = detect_low_confidence_items(actual_index, product_lookup)
    all_violations.extend(low_conf)
    print(f"   Flagged {len(low_conf)} low-confidence items\n")
    
    # Categorize by severity
    high = [v for v in all_violations if v["severity"] == "high"]
    medium = [v for v in all_violations if v["severity"] == "medium"]
    low = [v for v in all_violations if v["severity"] == "low"]
    info = [v for v in all_violations if v["severity"] == "info"]
    
    print("=" * 70)
    print(f"VIOLATION SUMMARY:")
    print(f"   🔴 High severity:    {len(high)}")
    print(f"   🟡 Medium severity:  {len(medium)}")
    print(f"   🟢 Low severity:     {len(low)}")
    print(f"   ℹ️  Info (review):    {len(info)}")
    print(f"   📊 Total:            {len(all_violations)}")
    print("=" * 70)
    
    result = {
        "rack_id": expected.get("rack_id"),
        "compared_at": datetime.now().isoformat(),
        "expected_source": EXPECTED_MAP_FILE,
        "actual_source": actual_map_file,
        "violation_counts": {
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "info": len(info),
            "total": len(all_violations)
        },
        "violations": all_violations
    }
    
    COMPARISONS_DIR.mkdir(parents=True, exist_ok=True)
    actual_name = Path(actual_map_file).stem.replace("actual_map_", "")
    output_file = COMPARISONS_DIR / f"comparison_{actual_name}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n📁 Comparison saved to: {output_file}")
    
    # Print grouped violations
    if high:
        print("\n" + "=" * 70)
        print("🔴 HIGH SEVERITY VIOLATIONS")
        print("=" * 70)
        for v in high:
            print(f"\n  → {v['description']}")
            print(f"    ✅ Action: {v['correction']}")
    
    if medium:
        print("\n" + "=" * 70)
        print("🟡 MEDIUM SEVERITY VIOLATIONS")
        print("=" * 70)
        for v in medium:
            print(f"\n  → {v['description']}")
            print(f"    ✅ Action: {v['correction']}")
    
    if low:
        print("\n" + "=" * 70)
        print("🟢 LOW SEVERITY VIOLATIONS")
        print("=" * 70)
        for v in low:
            print(f"  → {v['description']}")
    
    if info:
        print("\n" + "=" * 70)
        print("ℹ️  ITEMS TO REVIEW")
        print("=" * 70)
        for v in info:
            print(f"  → {v['description']}")
    
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        actual_maps_dir = Path("data/actual_maps")
        actual_files = sorted(actual_maps_dir.glob("actual_map_*.json"))
        
        if not actual_files:
            print("❌ No actual_map files found in data/actual_maps/")
            sys.exit(1)
        
        print(f"Comparing {len(actual_files)} actual maps against reference...\n")
        for actual_file in actual_files:
            compare_maps(str(actual_file))
    else:
        compare_maps(sys.argv[1])