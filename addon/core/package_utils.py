"""Helpers for identifying this add-on under legacy and extension imports."""

from __future__ import annotations


def addon_package_name(module_package: str | None) -> str:
    """Return the add-on's registered module name for either install style."""
    parts = (module_package or "").split(".")
    if not parts or not parts[0]:
        return ""
    if parts[0] == "bl_ext" and len(parts) >= 3:
        return ".".join(parts[:3])
    return parts[0]
