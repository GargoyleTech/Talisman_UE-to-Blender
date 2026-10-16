"""Package fingerprints, persistent mesh indexes and virtual-path search."""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import bpy

from .session import _run_gargoyle_asset_request

# Cache schema 3 retains both static and skeletal listings for every title.
_MESH_CACHE_VERSION = 3
_NATURAL_PATH_TOKEN = re.compile(r"(\d+)")
ZERO_READABLE_PACKAGES_MESSAGE = "Zero readable packages. The usmap file might be missing or invalid."


class UnreadableMeshPackagesError(ValueError):
    """Mounted packages were found, but the mesh scan could read none of them."""


def mesh_index_failure_count(index):
    failures = index.get("failures") or 0
    return len(failures) if isinstance(failures, (list, tuple)) else int(failures)


def validate_mesh_index(index):
    """Diagnose failed decoding separately from an empty or non-mesh scan.

    Older bridge builds do not report the readable package count. Their empty
    mesh lists plus package failures remain the best available failure signal.
    """
    if (mesh_index_failure_count(index) > 0
            and not index.get("staticMeshes") and not index.get("skeletalMeshes")
            and not index.get("readablePackages")):
        raise UnreadableMeshPackagesError(ZERO_READABLE_PACKAGES_MESSAGE)


def _package_config_key(
    game_root: str, oodle_dll: str, usmap_path: str
) -> tuple[str, str, str]:
    return tuple(
        os.path.normcase(os.path.abspath(value)) if value else ""
        for value in (game_root, oodle_dll, usmap_path)
    )


def _mesh_package_signature(
    game_root: str,
    profile=None,
) -> list[tuple[str, int, int]]:
    """Small fingerprint of IoStore containers; changes invalidate disk cache."""
    pak_root = Path(game_root).joinpath(
        *(profile.package_relative_path if profile else ())
    )
    if not pak_root.is_dir():
        pak_root = Path(game_root)
    signature = []
    for path in pak_root.rglob("*"):
        if path.suffix.casefold() not in {".pak", ".utoc", ".ucas"}:
            continue
        try:
            stat = path.stat()
            signature.append(
                (
                    path.relative_to(pak_root).as_posix().casefold(),
                    stat.st_size,
                    stat.st_mtime_ns,
                )
            )
        except OSError:
            continue
    return sorted(signature)


def _mesh_disk_cache_path(cache_key: tuple[str, str, str]) -> Path | None:
    try:
        cache_root = bpy.utils.user_resource("CONFIG")
        if not cache_root:
            return None
        cache_root = Path(cache_root) / "talisman"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_id = hashlib.sha256("\0".join(cache_key).encode("utf-8")).hexdigest()[:20]
        return cache_root / f"mesh_index_{cache_id}.json"
    except Exception:
        return None


def _natural_path_key(path: str) -> tuple[tuple[int, int | str], ...]:
    """Case-insensitive path key that orders numeric runs numerically.

    Game mesh names commonly encode an outfit/variation as ``_00``, ``_04``,
    and so on. Plain string ordering can be lost again in Blender's search
    popup, so use this key both for the cached index and its returned matches.
    """
    return tuple(
        (0, int(part)) if part.isdecimal() else (1, part.casefold())
        for part in _NATURAL_PATH_TOKEN.split(path)
        if part
    )


def _load_mesh_disk_cache(
    cache_path: Path | None,
    cache_key: tuple[str, str, str],
    package_signature: list[tuple[str, int, int]],
) -> tuple[list[str], list[str]] | None:
    if cache_path is None or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            payload.get("version") != _MESH_CACHE_VERSION
            or tuple(payload.get("config") or []) != cache_key
            or payload.get("packageSignature")
            != [list(item) for item in package_signature]
        ):
            return None
        static_meshes = payload.get("staticMeshes")
        skeletal_meshes = payload.get("skeletalMeshes")
        if not isinstance(static_meshes, list) or not isinstance(skeletal_meshes, list):
            return None
        return (
            sorted((str(path) for path in static_meshes), key=_natural_path_key),
            sorted((str(path) for path in skeletal_meshes), key=_natural_path_key),
        )
    except (OSError, ValueError, TypeError):
        return None


def _save_mesh_disk_cache(
    cache_path: Path | None,
    cache_key: tuple[str, str, str],
    package_signature: list[tuple[str, int, int]],
    static_meshes: list[str],
    skeletal_meshes: list[str],
) -> None:
    if cache_path is None:
        return
    try:
        payload = {
            "version": _MESH_CACHE_VERSION,
            "config": list(cache_key),
            "packageSignature": [list(item) for item in package_signature],
            "staticMeshes": static_meshes,
            "skeletalMeshes": skeletal_meshes,
        }
        temporary_path = cache_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
        os.replace(temporary_path, cache_path)
    except OSError as exc:
        print(f"Package mesh index could not be saved to disk: {exc}")


def _package_search_terms(edit_text: str) -> tuple[str, ...]:
    """Split a package search into unordered, space-separated path terms."""
    return tuple(edit_text.casefold().replace("\\", "/").split())


def _path_matches_package_search(path: str, terms: tuple[str, ...]) -> bool:
    """Return whether every search term occurs somewhere in a virtual path."""
    normalized_path = path.casefold().replace("\\", "/")
    return all(term in normalized_path for term in terms)


def _search_virtual_paths(
    paths: list[str],
    edit_text: str,
    empty_limit=256,
    result_limit=512,
    *,
    sort_key=str.casefold,
):
    terms = _package_search_terms(edit_text)
    if not terms:
        return sorted(paths, key=sort_key)[:empty_limit]
    return sorted(
        (path for path in paths if _path_matches_package_search(path, terms)),
        key=sort_key,
    )[:result_limit]


@dataclass
class MeshAssetIndex:
    """A source-scoped static/skeletal listing shared by title adapters."""

    static_meshes: list[str] = field(default_factory=list)
    skeletal_meshes: list[str] = field(default_factory=list)
    cache_key: tuple | None = None
    source: str = ""

    def refresh(self, paths, profile, *, path_filter="", force=False):
        # A changed profile, encryption key or scan filter must never reuse a
        # different game's listing, even when it points at the same directory.
        key = (
            *_package_config_key(paths.install_root, paths.oodle_dll, paths.usmap_path),
            profile.gargoyle_profile,
            hashlib.sha256(paths.aes_key.encode("utf-8")).hexdigest(),
            path_filter,
        )
        if not force and key == self.cache_key:
            return self.static_meshes, self.skeletal_meshes
        signature = _mesh_package_signature(paths.install_root, profile=profile)
        cache_path = _mesh_disk_cache_path(key)
        cached = None if force else _load_mesh_disk_cache(cache_path, key, signature)
        # Older releases cached failed scans as empty lists without diagnostics.
        # Recheck those so the missing/invalid mapping hint is not lost on reload.
        if cached is not None and not any(cached):
            cached = None
        if cached is None:
            request = {"action": "mesh_index"}
            if path_filter:
                request["pathFilter"] = path_filter
            response = _run_gargoyle_asset_request(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                request,
                profile=profile,
                aes_key=paths.aes_key,
            )
            index = response.get("meshIndex") or {}
            cached = (
                sorted(index.get("staticMeshes") or [], key=_natural_path_key),
                sorted(index.get("skeletalMeshes") or [], key=_natural_path_key),
            )
            failures = mesh_index_failure_count(index)
            if failures:
                print(
                    f"{profile.label} mesh index skipped {failures:,} unreadable package(s)."
                )
            try:
                validate_mesh_index(index)
            except UnreadableMeshPackagesError:
                self.static_meshes, self.skeletal_meshes = [], []
                self.cache_key, self.source = None, ""
                raise
            _save_mesh_disk_cache(cache_path, key, signature, *cached)
            self.source = "mounted packages"
        else:
            self.source = "disk cache"
        self.static_meshes, self.skeletal_meshes = cached
        self.cache_key = key
        return cached


@dataclass
class AnimationAssetIndex:
    """Compatible clip listings, isolated by source and title search policy."""

    paths: list[str] = field(default_factory=list)
    cache_key: tuple | None = None

    def refresh(
        self,
        paths,
        profile,
        skeleton_path,
        *,
        search_token="",
        include_unlinked=False,
        use_registry=False,
        force=False,
    ):
        key = (
            *_package_config_key(paths.install_root, paths.oodle_dll, paths.usmap_path),
            profile.gargoyle_profile,
            hashlib.sha256(paths.aes_key.encode("utf-8")).hexdigest(),
            skeleton_path.casefold(),
            search_token,
            include_unlinked,
            use_registry,
        )
        if force or key != self.cache_key:
            request = (
                {
                    "action": "generic_animation_index",
                    "skeletonAssetPath": skeleton_path,
                    "pathFilter": search_token,
                }
                if use_registry
                else {
                    "action": "animation_index",
                    "skeletonAssetPath": skeleton_path,
                    "searchToken": search_token,
                    "includeUnlinked": include_unlinked,
                }
            )
            response = _run_gargoyle_asset_request(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                request,
                profile=profile,
                aes_key=paths.aes_key,
            )
            index = response.get("index" if use_registry else "animationIndex") or {}
            self.paths = sorted(
                {str(path) for path in index.get("paths") or []}
                if use_registry else {
                    str(item["assetPath"])
                    for item in index.get("animations") or []
                    if isinstance(item, dict) and item.get("assetPath")
                },
                key=_natural_path_key,
            )
            for warning in index.get("warnings") or []:
                print(f"{profile.label} animation index: {warning}")
            failures = int(index.get("failures") or 0)
            if failures:
                print(
                    f"{profile.label} animation index skipped {failures:,} unreadable package(s)."
                )
            self.cache_key = key
        return self.paths
