"""Game-profile metadata and preference-path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


def normalize_optional_input(value: str) -> str:
    """Treat an explicit not-applicable marker as an omitted key or mapping."""
    value = (value or "").strip()
    return "" if value.casefold() == "n/a" else value


@dataclass(frozen=True)
class GamePaths:
    """Resolved filesystem inputs consumed by the package gargoyle."""

    install_root: str
    oodle_dll: str = ""
    usmap_path: str = ""
    aes_key: str = ""

    def __post_init__(self):
        object.__setattr__(self, "usmap_path", normalize_optional_input(self.usmap_path))
        object.__setattr__(self, "aes_key", normalize_optional_input(self.aes_key))


@dataclass(frozen=True)
class GameProfile:
    """Stable per-title configuration, separate from importer implementation."""

    key: str
    label: str
    gargoyle_profile: str
    engine_label: str
    package_relative_path: tuple[str, ...]
    install_root_property: str
    # Mounted package paths normally mirror the folder below the install root.
    # Some multi-title Steam installs mount a game-named content root even when
    # that game's preferences point at the title subdirectory instead.
    virtual_content_root: tuple[str, ...] | None = None
    usmap_property: str | None = None
    aes_key_property: str | None = None

    @property
    def requires_usmap(self) -> bool:
        return self.usmap_property is not None

    @property
    def mounted_content_root(self) -> str:
        """Virtual package prefix used by the mounted CUE4Parse provider."""
        if self.virtual_content_root is not None:
            return "/".join(self.virtual_content_root)
        path_parts = self.package_relative_path
        if path_parts and path_parts[-1].casefold() == "paks":
            path_parts = path_parts[:-1]
        return "/".join(path_parts)

    def paths_from_preferences(
        self,
        preferences,
        abspath: Callable[[str], str] = str,
    ) -> GamePaths:
        """Resolve this profile's configured paths without importing Blender."""
        def value(property_name: str | None) -> str:
            if property_name is None:
                return ""
            return getattr(preferences, property_name, "") or ""

        def resolve(property_name: str | None) -> str:
            property_value = value(property_name)
            return abspath(property_value) if property_value else ""

        install_root = resolve(self.install_root_property)
        # Oodle's decompression DLL is compatible across the supported UE4
        # titles, so every game importer intentionally shares this one
        # add-on preference rather than maintaining per-game copies.
        oodle_dll = resolve("oodle_dll")
        usmap_value = normalize_optional_input(value(self.usmap_property))
        usmap_path = abspath(usmap_value) if usmap_value else ""
        aes_key = normalize_optional_input(value(self.aes_key_property))
        return GamePaths(install_root, oodle_dll, usmap_path, aes_key)
