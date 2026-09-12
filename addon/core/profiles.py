"""Game-profile metadata and preference-path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class GamePaths:
    """Resolved filesystem inputs consumed by the package bridge."""

    install_root: str
    oodle_dll: str = ""
    usmap_path: str = ""


@dataclass(frozen=True)
class GameProfile:
    """Stable per-title configuration, separate from importer implementation."""

    key: str
    label: str
    bridge_profile: str
    engine_label: str
    package_relative_path: tuple[str, ...]
    install_root_property: str
    oodle_property: str | None = None
    usmap_property: str | None = None
    bundled_oodle_relative_path: tuple[str, ...] | None = None

    @property
    def requires_usmap(self) -> bool:
        return self.usmap_property is not None

    def paths_from_preferences(
        self,
        preferences,
        abspath: Callable[[str], str] = str,
    ) -> GamePaths:
        """Resolve this profile's configured paths without importing Blender."""
        def resolve(property_name: str | None) -> str:
            if property_name is None:
                return ""
            value = getattr(preferences, property_name, "") or ""
            return abspath(value) if value else ""

        install_root = resolve(self.install_root_property)
        oodle_dll = (
            resolve(self.oodle_property)
        )
        if (
            not oodle_dll
            and install_root
            and self.bundled_oodle_relative_path is not None
        ):
            candidate = Path(install_root).joinpath(*self.bundled_oodle_relative_path)
            if candidate.is_file():
                oodle_dll = str(candidate)
        usmap_path = resolve(self.usmap_property)
        return GamePaths(install_root, oodle_dll, usmap_path)
