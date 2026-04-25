"""Filesystem helpers for keeping generated files inside a project root."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


def normalize_relative_path(path: str) -> str:
    """Return a safe normalized relative path or raise ValueError."""
    if not path or "\x00" in path:
        raise ValueError("Path must be a non-empty relative path")
    if os.path.isabs(path) or PureWindowsPath(path).is_absolute():
        raise ValueError("Path must be relative")

    normalized = os.path.normpath(path.replace("\\", "/"))
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        raise ValueError("Path must stay within the project directory")

    return normalized


def resolve_within_directory(base_dir: str | os.PathLike, path: str) -> tuple[Path, str]:
    """Resolve path under base_dir and verify the final target stays inside it."""
    normalized = normalize_relative_path(path)
    base = Path(base_dir).resolve()
    target = (base / normalized).resolve()

    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("Path must stay within the project directory") from exc

    return target, normalized
