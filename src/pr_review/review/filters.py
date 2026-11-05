"""Decide which diff paths are safe to send to a model."""

from __future__ import annotations

import fnmatch


def path_is_excluded(path: str, patterns: list[str]) -> bool:
    """Return True when ``path`` matches a configured exclude glob."""
    relative = _normalize(path)
    if not relative:
        return False
    name = relative.rsplit("/", 1)[-1]
    for pattern in patterns:
        candidate = pattern.strip().replace("\\", "/")
        if not candidate:
            continue
        if fnmatch.fnmatch(relative, candidate) or fnmatch.fnmatch(name, candidate):
            return True
        if _double_star_match(relative, candidate):
            return True
    return False


def _normalize(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _double_star_match(path: str, pattern: str) -> bool:
    if not pattern.startswith("**/"):
        return False
    rest = pattern[3:]
    if rest.endswith("/**"):
        prefix = rest[:-3]
        if path == prefix or path.startswith(prefix + "/"):
            return True
        return f"/{prefix}/" in f"/{path}/"
    parts = path.split("/")
    for index in range(len(parts)):
        suffix = "/".join(parts[index:])
        if fnmatch.fnmatch(suffix, rest):
            return True
    return False
