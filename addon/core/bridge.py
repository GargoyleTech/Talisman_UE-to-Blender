"""Shared access to the packaged CUE4Parse gargoyle executable."""

from __future__ import annotations

import os
from pathlib import Path

from .profiles import GamePaths, GameProfile


def gargoyle_executable_path(addon_root: Path) -> Path:
    """Return the packaged gargoyle, falling back to a local release build."""
    candidates = (
        addon_root / "bridge" / "TalismanGameAssetBridge.exe",
        addon_root.parent / "bridge" / "bin" / "Release" / "net10.0"
        / "win-x64" / "TalismanGameAssetBridge.exe",
        addon_root.parent / "bridge" / "bin" / "Release" / "net10.0"
        / "TalismanGameAssetBridge.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Talisman Game Asset Bridge is missing. Reinstall the complete add-on package."
    )


def gargoyle_command(
    addon_root: Path,
    profile: GameProfile,
    paths: GamePaths,
    output_json: str,
    *,
    path_filter: str = "",
    asset_path: str = "",
    dds_output: str = "",
    raw_output: str = "",
    summary: bool = False,
    operation: str = "",
) -> list[str]:
    """Build the gargoyle's positional command line for one explicit title."""
    return [
        str(gargoyle_executable_path(addon_root)),
        os.path.abspath(paths.install_root),
        output_json,
        os.path.abspath(paths.oodle_dll) if paths.oodle_dll else "",
        path_filter,
        asset_path,
        os.path.abspath(paths.usmap_path) if paths.usmap_path else "",
        os.path.abspath(dds_output) if dds_output else "",
        os.path.abspath(raw_output) if raw_output else "",
        "summary" if summary else "",
        operation,
        profile.gargoyle_profile,
        paths.aes_key,
    ]
