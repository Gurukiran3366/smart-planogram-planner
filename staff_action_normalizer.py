import argparse
import json
from pathlib import Path
from datetime import datetime


VERSION = "1.1"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def loc_text(loc):
    if not isinstance(loc, dict):
        return "Unknown location"

    shelf = loc.get("shelf")
    slots = loc.get("slots")

    if shelf is None:
        return "Unknown location"

    if isinstance(slots, list) and slots:
        if len(slots) == 1:
            return f"Shelf {shelf} • Slot {slots[0]}"
        return f"Shelf {shelf} • Slots {slots}"

    start = loc.get("slot_start")
    end = loc.get("slot_end")

    if start is not None and end is not None:
        if start == end:
            return f"Shelf {shelf} • Slot {start}"
        return f"Shelf {shelf} • Slots {start}-{end}"

    return f"Shelf {shelf}"


def product_name(item):
    return (
        item.get("product_name")
        or item.get("name")
        or item.get("product_id")
        or "Unknown product"
    )


def normalize_dependencies(data):
    if not isinstance(data, dict):
        return []

    actions = data.get("safe_dependency_actions")

    if not isinstance(actions, list):
        actions = data.get("safe_actions")

    if not isinstance(actions, list):
        actions = data.get("actions", [])

    if not isinstance(actions, list):
        return []

    return actions


def normalize_rearrangements(data):
    if not isinstance(data, dict):
        return []

    actions = data.get("safe_rearrangements")

    if not isinstance(actions, list):
        actions = data.get("direct_swaps", [])

    if not isinstance(actions, list):
        actions = []

    return actions


def dependency_to_staff_action(action):
    if not isinstance(action, dict):
        return None

    action_type = str(
        action.get("type")
        or action.get("action_type")
        or ""
    ).upper()

    products = action.get("products", [])

    # ------------------------------------------------------------
    # REMOVE EXTRA
    # ------------------------------------------------------------
    if action_type == "REMOVE_EXTRA":
        pid = action.get("product_id")
        name = action.get("product_name") or pid or "product"

        extra = (
            action.get("extra_occurrence")
            or action.get("extra")
            or action.get("location")
        )

        correct = (
            action.get("correct_occurrence")
            or action.get("correct_location")
            or action.get("keep_location")
        )

        if isinstance(extra, dict):
            extra_text = loc_text(extra)
        else:
            extra_text = "the identified extra location"

        if isinstance(correct, dict):
            correct_text = loc_text(correct)
        else:
            correct_text = "the correct planogram location"

        return {
            "priority": 1,
            "type": "REMOVE_EXTRA",
            "product_id": pid,
            "product_name": name,
            "title": f"Remove extra {name}",
            "action": (
                f"Remove the extra {name} from {extra_text}. "
                f"Keep the correct {name} at {correct_text}."
            ),
            "steps": [
                f"Remove {name} from {extra_text}.",
                f"Keep the correct {name} at {correct_text}.",
            ],
        }

    # ------------------------------------------------------------
    # DIRECT SWAP
    # ------------------------------------------------------------
    if action_type in {
        "DIRECT_SWAP",
        "SWAP",
        "MULTIFACING_DEPENDENCY_SWAP",
    }:
        if len(products) >= 2:
            a = products[0]
            b = products[1]

            aname = product_name(a)
            bname = product_name(b)

            afrom = a.get("from") or a.get("current")
            ato = a.get("to") or a.get("target")

            bfrom = b.get("from") or b.get("current")
            bto = b.get("to") or b.get("target")

            if afrom and bfrom:
                return {
                    "priority": 2,
                    "type": "SWAP",
                    "product_id": a.get("product_id"),
                    "product_name": aname,
                    "title": f"Swap {aname} and {bname}",
                    "action": (
                        f"Swap {aname} at {loc_text(afrom)} "
                        f"with {bname} at {loc_text(bfrom)}."
                    ),
                    "steps": [
                        f"Remove {aname} from {loc_text(afrom)}.",
                        f"Remove {bname} from {loc_text(bfrom)}.",
                        f"Place {aname} at {loc_text(ato)}.",
                        f"Place {bname} at {loc_text(bto)}.",
                    ],
                }

        # Fallback for older dependency planner format
        text = action.get("action") or action.get("description")

        if text:
            return {
                "priority": 2,
                "type": "SWAP",
                "product_name": (
                    action.get("product_name")
                    or "Product swap"
                ),
                "title": "Perform product swap",
                "action": text,
                "steps": action.get("steps", []),
            }

    # ------------------------------------------------------------
    # DEPENDENT MOVE
    # ------------------------------------------------------------
    if action_type == "DEPENDENT_MOVE":
        steps = action.get("steps", [])

        if not isinstance(steps, list):
            steps = []

        normalized_steps = []

        for step in steps:
            if isinstance(step, dict):
                text = (
                    step.get("action")
                    or step.get("description")
                )

                if text:
                    normalized_steps.append(text)

            elif isinstance(step, str):
                normalized_steps.append(step)

        action_text = action.get("action") or action.get("description")

        if not action_text and normalized_steps:
            action_text = " Then ".join(normalized_steps)

        return {
            "priority": 2,
            "type": "DEPENDENT_MOVE",
            "product_name": action.get("product_name") or "Dependent move",
            "title": "Perform dependent move",
            "action": action_text or "Follow the ordered dependency steps.",
            "steps": normalized_steps,
        }

    # ------------------------------------------------------------
    # GENERIC ACTION
    # ------------------------------------------------------------
    text = (
        action.get("action")
        or action.get("description")
        or action.get("reason")
    )

    if text:
        return {
            "priority": 3,
            "type": action_type or "ACTION",
            "product_name": (
                action.get("product_name")
                or action.get("product_id")
                or "Product"
            ),
            "title": action_type.replace("_", " ").title()
            if action_type
            else "Action",
            "action": text,
            "steps": action.get("steps", []),
        }

    return None


def rearrangement_to_staff_action(action):
    if not isinstance(action, dict):
        return None

    products = action.get("products", [])

    if len(products) >= 2:
        a = products[0]
        b = products[1]

        aname = product_name(a)
        bname = product_name(b)

        afrom = a.get("from") or a.get("current")
        ato = a.get("to") or a.get("target")

        bfrom = b.get("from") or b.get("current")
        bto = b.get("to") or b.get("target")

        if afrom and bfrom:
            return {
                "priority": 2,
                "type": "SWAP",
                "product_name": aname,
                "title": f"Swap {aname} and {bname}",
                "action": (
                    f"Swap {aname} at {loc_text(afrom)} "
                    f"with {bname} at {loc_text(bfrom)}."
                ),
                "steps": [
                    f"Remove {aname} from {loc_text(afrom)}.",
                    f"Remove {bname} from {loc_text(bfrom)}.",
                    f"Place {aname} at {loc_text(ato)}.",
                    f"Place {bname} at {loc_text(bto)}.",
                ],
            }

    text = action.get("action") or action.get("description")

    if text:
        return {
            "priority": 2,
            "type": "SWAP",
            "product_name": "Product swap",
            "title": "Perform swap",
            "action": text,
            "steps": action.get("steps", []),
        }

    return None


def build_review_actions(occurrences, dependencies):
    reviews = []

    # Dependency planner reviews are authoritative when present.
    if isinstance(dependencies, dict):
        dependency_reviews = dependencies.get("review_required", [])

        if isinstance(dependency_reviews, list):
            for item in dependency_reviews:
                if not isinstance(item, dict):
                    continue

                name = product_name(item)

                reviews.append({
                    "priority": 4,
                    "type": "REVIEW",
                    "product_name": name,
                    "title": f"Review {name}",
                    "action": (
                        item.get("reason")
                        or f"Manually verify {name} before changing it."
                    ),
                })

    # If dependency planner has no review section, derive unresolved
    # occurrence cases without inventing physical actions.
    if not reviews and isinstance(occurrences, dict):
        resolutions = occurrences.get("resolutions", [])

        if isinstance(resolutions, list):
            for res in resolutions:
                if not isinstance(res, dict):
                    continue

                status = str(res.get("status", "")).upper()

                if status in {"AMBIGUOUS", "REVIEW"}:
                    name = product_name(res)

                    reviews.append({
                        "priority": 4,
                        "type": "REVIEW",
                        "product_name": name,
                        "title": f"Review {name}",
                        "action": (
                            res.get("reason")
                            or f"Manually verify {name} before changing it."
                        ),
                    })

    return reviews


def deduplicate_actions(actions):
    result = []
    seen = set()

    for action in actions:
        if not isinstance(action, dict):
            continue

        key = (
            action.get("type"),
            str(action.get("product_name", "")).lower(),
            action.get("action", ""),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(action)

    return result


def build_staff_actions(rack, occurrences, dependencies, rearrangements):
    safe = []

    # Dependency planner is the primary authority.
    for action in normalize_dependencies(dependencies):
        normalized = dependency_to_staff_action(action)

        if normalized:
            safe.append(normalized)

    # Use rearrangements only when dependency planner did not already
    # provide the same physical action.
    if not safe:
        for action in normalize_rearrangements(rearrangements):
            normalized = rearrangement_to_staff_action(action)

            if normalized:
                safe.append(normalized)

    safe = deduplicate_actions(safe)

    reviews = build_review_actions(
        occurrences,
        dependencies,
    )

    safe.sort(
        key=lambda x: (
            x.get("priority", 99),
            str(x.get("product_name", "")).lower(),
        )
    )

    reviews.sort(
        key=lambda x: str(
            x.get("product_name", "")
        ).lower()
    )

    return safe, reviews


def render_staff_message(rack, safe, reviews):
    lines = []

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📋 CHILLER PLANOGRAM ACTIONS")
    lines.append(f"Rack: {rack}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if safe:
        lines.append("")
        lines.append("🔧 ACTIONS TO DO")

        for i, action in enumerate(safe, 1):
            lines.append("")
            lines.append(
                f"{i}. {action.get('action', 'Perform action.')}"
            )

            steps = action.get("steps", [])

            if isinstance(steps, list) and len(steps) > 1:
                for j, step in enumerate(steps, 1):
                    lines.append(f"   {j}) {step}")

    if reviews:
        lines.append("")
        lines.append("⚠️ MANUAL REVIEW")

        for i, review in enumerate(reviews, 1):
            lines.append("")
            lines.append(
                f"{i}. {review.get('product_name', 'Product')}"
            )
            lines.append(
                f"   {review.get('action', 'Verify manually before moving.')}"
            )

    if not safe and not reviews:
        lines.append("")
        lines.append("✅ No physical actions identified.")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📸 After completing the actions,")
    lines.append("take a new photo and run the audit again.")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def build_report(
    rack,
    safe,
    reviews,
    occurrences,
    dependencies,
    rearrangements,
):
    return {
        "engine": "staff_action_normalizer",
        "engine_version": VERSION,
        "rack": rack,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "safe_actions": len(safe),
            "review_required": len(reviews),
            "total_actions": len(safe) + len(reviews),
            "decision": (
                "ACTION_RECOMMENDED"
                if safe
                else (
                    "REVIEW_REQUIRED"
                    if reviews
                    else "NO_ACTION"
                )
            ),
        },
        "safe_actions": safe,
        "review_required": reviews,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Normalize dependency/rearrangement results "
            "into clear staff-facing physical actions."
        )
    )

    parser.add_argument(
        "--rack",
        required=True,
    )

    parser.add_argument(
        "--occurrences",
        required=True,
    )

    parser.add_argument(
        "--rearrangements",
        required=True,
    )

    parser.add_argument(
        "--dependencies",
        required=True,
    )

    parser.add_argument(
        "--final-recommendations",
        required=False,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    parser.add_argument(
        "--staff-output",
        required=True,
    )

    args = parser.parse_args()

    # IMPORTANT:
    # Always use args.rack. The previous implementation referenced
    # an undefined local variable named "rack".
    rack = args.rack

    occurrences = load_json(args.occurrences)
    dependencies = load_json(args.dependencies)
    rearrangements = load_json(args.rearrangements)

    safe, reviews = build_staff_actions(
        rack,
        occurrences,
        dependencies,
        rearrangements,
    )

    report = build_report(
        rack,
        safe,
        reviews,
        occurrences,
        dependencies,
        rearrangements,
    )

    staff_message = render_staff_message(
        rack,
        safe,
        reviews,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    staff_path = Path(args.staff_output)
    staff_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    staff_path.write_text(
        staff_message,
        encoding="utf-8",
    )

    print("=" * 80)
    print("SMART PLANOGRAM — STAFF ACTION NORMALIZER")
    print("=" * 80)
    print(f"Rack: {rack}")
    print("")
    print(f"Safe actions       : {len(safe)}")
    print(f"Review required    : {len(reviews)}")
    print(
        f"Decision           : {report['summary']['decision']}"
    )
    print("-" * 80)

    if safe:
        print("STAFF ACTIONS")
        for i, action in enumerate(safe, 1):
            print(
                f"{i}. [{action.get('type', 'ACTION')}]"
            )
            print(
                f"   {action.get('action', '')}"
            )

            steps = action.get("steps", [])

            if isinstance(steps, list) and len(steps) > 1:
                for j, step in enumerate(steps, 1):
                    print(f"   STEP {j}: {step}")

    if reviews:
        print("")
        print("MANUAL REVIEW")

        for i, review in enumerate(reviews, 1):
            print(
                f"{i}. {review.get('product_name', 'Product')}"
            )
            print(
                f"   {review.get('action', '')}"
            )

    print("")
    print(
        f"Staff action report written to: {output_path}"
    )
    print(
        f"Staff message written to: {staff_path}"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
