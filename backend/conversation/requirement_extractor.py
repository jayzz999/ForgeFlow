"""Requirement extraction helpers."""


def merge_requirements(existing: dict, new_info: dict) -> dict:
    """Merge new user input into existing requirements."""
    merged = {**existing}

    # Update confidence
    if new_info.get("confidence", 0) > existing.get("confidence", 0):
        merged["confidence"] = new_info["confidence"]

    # Merge actions (avoid duplicates)
    existing_ids = {a["id"] for a in existing.get("actions", [])}
    for action in new_info.get("actions", []):
        if action["id"] not in existing_ids:
            merged.setdefault("actions", []).append(action)

    # Merge entities
    existing_names = {e["name"] for e in existing.get("entities", [])}
    for entity in new_info.get("entities", []):
        if entity["name"] not in existing_names:
            merged.setdefault("entities", []).append(entity)

    # Update other fields if they're more complete
    for field in ("workflow_name", "description", "intent"):
        if new_info.get(field) and not existing.get(field):
            merged[field] = new_info[field]

    # Merge data flows
    merged["data_flows"] = new_info.get("data_flows", existing.get("data_flows", []))

    # Clear resolved clarifications
    merged["clarification_needed"] = new_info.get("clarification_needed", [])
    merged["assumed_defaults"] = existing.get("assumed_defaults", []) + new_info.get("assumed_defaults", [])

    return merged


def requirements_complete(requirements: dict) -> bool:
    """Check if requirements are complete enough to proceed."""
    return (
        requirements.get("confidence", 0) >= 0.7
        and len(requirements.get("actions", [])) > 0
        and not requirements.get("clarification_needed")
    )
