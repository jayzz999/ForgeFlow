"""Targeted code patching for workflow modifications."""

import difflib


def generate_diff(original: str, modified: str) -> str:
    """Generate a human-readable diff between two code versions."""
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile="original.py",
        tofile="modified.py",
        lineterm="",
    )

    return "\n".join(diff)


def count_changes(original: str, modified: str) -> dict:
    """Count the number of lines added, removed, and modified."""
    original_lines = set(original.splitlines())
    modified_lines = set(modified.splitlines())

    added = modified_lines - original_lines
    removed = original_lines - modified_lines

    return {
        "added": len(added),
        "removed": len(removed),
        "total_changes": len(added) + len(removed),
    }
