"""Browse and import maps and character data directly from Rebirth packages."""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import tempfile
import traceback
from contextlib import contextmanager, nullcontext
from pathlib import Path

import bpy
import numpy as np
from bpy_extras import anim_utils

from ....core.bridge import bridge_command
from ....core.profiles import GamePaths
from ..profile import PROFILE as REBIRTH_PROFILE
from ....formats.mec.importer import import_umap_paths
from ....formats.mec.material import image_loader_override
from ....formats.mec.parser import offset_opposite_face_geometry, scaled_opposite_face_offset
from ....formats.ue_map import map_import
from ..materials import rmi_surface
from ....core.blender.reporting import FF7R_LoggedOperator, report
from ....formats.kdi.drivers import (
    AXIS_ORDER_ITEMS,
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
    COORDINATE_PROFILE_REFERENCE,
)
from ....core.blender.skeletons import (
    _bones_from_bridge,
    build_armature_from_bones,
    FACE_FORWARD_BLENDER,
    FACE_FORWARD_UNREAL,
)
from ... import package_browser


_VIRTUAL_UMAPS: list[str] = []
_CACHE_KEY: tuple[str, str, str] | None = None
_SELECTED_UMAPS: set[str] = set()
_VIRTUAL_KDIS: list[str] = []
_KDI_CACHE_KEY: tuple[str, str, str] | None = None
_VIRTUAL_SKELETONS: list[str] = []
_SKELETON_CACHE_KEY: tuple[str, str, str] | None = None
_VIRTUAL_STATIC_MESHES: list[str] = []
_VIRTUAL_SKELETAL_MESHES: list[str] = []
_MESH_CACHE_KEY: tuple[str, str, str] | None = None
_MESH_CACHE_SOURCE = ""
_STATIC_MESH_BROWSER = package_browser.make_state(
    "StaticMesh assets", initial_directory="End/Content", file_icon="MESH_DATA"
)
_SKELETAL_MESH_BROWSER = package_browser.make_state(
    "SkeletalMesh assets", initial_directory="End/Content", file_icon="ARMATURE_DATA"
)
# Version 2 adds conventional-title SkeletalMesh entries.  Earlier Remake and
# Crisis Core caches deliberately stored an empty skeletal list, so they must
# be rebuilt instead of making the new pickers look empty.
# Version 3 fixes conventional-title caches that previously discarded the
# SkeletalMesh entries while writing the shared mesh index.
_MESH_CACHE_VERSION = 3
_VIRTUAL_ANIMATIONS: list[str] = []
_ANIMATION_CACHE_KEY: tuple[str, str, str, str] | None = None
_VIRTUAL_CUTSCENES: list[str] = []
_CUTSCENE_CACHE_KEY: tuple[str, str, str] | None = None
_NATURAL_PATH_TOKEN = re.compile(r"(\d+)")
_LAST_UMAP_BROWSER_DIRECTORY = "End/Content/Level/Game/Field"
KDI_COORDINATE_PROFILE_PROPERTY = "ff7r_kdi_coordinate_profile"
SKELETON_ASSET_PATH_PROPERTY = "ff7r_skeleton_asset_path"

OFFSET_FACES_NONE = "NONE"
OFFSET_FACES_BAKED = "BAKED"
OFFSET_FACES_MODIFIER = "MODIFIER"
OFFSET_FACES_ITEMS = (
    (OFFSET_FACES_NONE, "None", "Do not offset overlapping opposite-facing faces"),
    (OFFSET_FACES_BAKED, "Baked", "Offset opposite-facing vertices during mesh import"),
    (
        OFFSET_FACES_MODIFIER,
        "Modifier",
        "Add the Retrilogy Alpha Displace modifier and vertex-group mask",
    ),
)

ATTACHMENT_SOCKETS_NONE = "NONE"
ATTACHMENT_SOCKETS_EMPTIES = "EMPTIES"
ATTACHMENT_SOCKETS_BONES = "BONES"
ATTACHMENT_SOCKETS_ITEMS = (
    (ATTACHMENT_SOCKETS_NONE, "None", "Do not create attachment socket objects or bones"),
    (
        ATTACHMENT_SOCKETS_EMPTIES,
        "Empties",
        "Create bone-parented Empty objects for attachment sockets",
    ),
    (
        ATTACHMENT_SOCKETS_BONES,
        "Bones",
        "Create hidden non-deforming bones for attachment sockets",
    ),
)

FACE_FORWARD_ITEMS = (
    (FACE_FORWARD_UNREAL, "+X (Unreal)", "Keep the imported asset facing Unreal's +X axis"),
    (FACE_FORWARD_BLENDER, "-Y (Blender)", "Rotate the imported asset to face Blender's -Y axis"),
)

DEFAULT_STATIC_MESH_PATH = (
    "End/Content/Environment/Machine/Model/Machine_MagicStore_01A.uasset"
)

# These are the three resident-continent TargetLocation values serialized in
# 0001-WORLD's EndStreamingVolume actors.  They match the WorldTransform
# translations in the matching NaviMap settings.  The MEC renderer adds one of
# them as MassiveEnvironmentOrigin before drawing a continent's local geometry.
MEC_CONTINENTS = {
    "EAST": {
        "label": "East (1xxx)",
        "root_map": "1000-EASTC",
        "level_prefix": "1",
        "origin_ue": (400000.0, 200000.0, 0.0),
    },
    "WEST": {
        "label": "West (2xxx)",
        "root_map": "2000-WESTC",
        "level_prefix": "2",
        "origin_ue": (-630000.0, 480000.0, 0.0),
    },
    "NORTH": {
        "label": "North (3xxx)",
        "root_map": "3000-NORTC",
        "level_prefix": "3",
        "origin_ue": (-160000.0, -700000.0, 0.0),
    },
}
MEC_NEARBY_DEFAULT_VIEW_DISTANCE = 300.0


def _addon_package_name() -> str:
    return (__package__ or "").split(".", 1)[0]


def _preferences(context):
    addon = context.preferences.addons.get(_addon_package_name())
    return addon.preferences if addon else None


def _bridge_command(
    game_root: str,
    oodle_dll: str,
    usmap_path: str,
    output_json: str,
    profile=REBIRTH_PROFILE,
    **options,
) -> list[str]:
    return bridge_command(
        Path(__file__).resolve().parents[3],
        profile,
        GamePaths(game_root, oodle_dll, usmap_path),
        output_json,
        **options,
    )


def _run_bridge(
        game_root: str,
        oodle_dll: str,
        usmap_path: str,
        *,
        path_filter: str = "",
        asset_path: str = "",
        raw_output: str = "",
        summary: bool = False,
        profile=REBIRTH_PROFILE,
) -> dict:
    output_handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    output_path = output_handle.name
    output_handle.close()
    command = _bridge_command(
        game_root,
        oodle_dll,
        usmap_path,
        output_path,
        path_filter=path_filter,
        asset_path=asset_path,
        raw_output=raw_output,
        summary=summary,
        profile=profile,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(detail or f"Bridge exited with code {completed.returncode}")
        with open(output_path, encoding="utf-8-sig") as stream:
            return json.load(stream)
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def _run_bridge_asset_request(
        game_root: str,
        oodle_dll: str,
    usmap_path: str,
    payload: dict,
    *,
    profile=REBIRTH_PROFILE,
) -> dict:
    """Run one short-lived asset-server request (used by package pickers)."""
    command = _bridge_command(
        game_root,
        oodle_dll,
        usmap_path,
        "-",
        profile=profile,
        operation="asset-server",
    )
    completed = subprocess.run(
        command,
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"Bridge exited with code {completed.returncode}")
    response_line = next((line for line in completed.stdout.splitlines() if line.strip()), "")
    if not response_line:
        raise RuntimeError("The package bridge returned no response while indexing meshes.")
    response = json.loads(response_line)
    if not response.get("ok"):
        details = response.get("errorDetails")
        if details:
            print("[FF7R bridge ERROR] Asset-server request failed:\n" + str(details))
        raise RuntimeError(response.get("error") or "Package mesh indexing failed")
    return response


def _validate_paths(game_root: str, oodle_dll: str, usmap_path: str) -> None:
    if not game_root or not os.path.isdir(game_root):
        raise FileNotFoundError("Set a valid FINAL FANTASY VII REBIRTH install folder.")
    if oodle_dll and not os.path.isfile(oodle_dll):
        raise FileNotFoundError("The configured Oodle DLL does not exist.")
    if usmap_path and not os.path.isfile(usmap_path):
        raise FileNotFoundError("The configured Rebirth .usmap file does not exist.")


def _package_config_key(game_root: str, oodle_dll: str, usmap_path: str) -> tuple[str, str, str]:
    return tuple(
        os.path.normcase(os.path.abspath(value)) if value else ""
        for value in (game_root, oodle_dll, usmap_path)
    )


def _normalize_offset_faces_mode(value: bool | str | None) -> str:
    """Accept the legacy boolean flag as well as the mesh-import enum values."""
    if value is True:
        return OFFSET_FACES_BAKED
    if value in {OFFSET_FACES_NONE, OFFSET_FACES_BAKED, OFFSET_FACES_MODIFIER}:
        return value
    return OFFSET_FACES_NONE


def _face_y_forward_enabled(value: bool | str | None) -> bool:
    """Accept the legacy boolean flag as well as the forward-axis enum values."""
    return value is True or value == FACE_FORWARD_BLENDER


def _mesh_package_signature(
        game_root: str,
        profile=REBIRTH_PROFILE,
) -> list[tuple[str, int, int]]:
    """Small fingerprint of IoStore containers; changes invalidate disk cache."""
    pak_root = Path(game_root).joinpath(*profile.package_relative_path)
    if not pak_root.is_dir():
        pak_root = Path(game_root)
    signature = []
    for path in pak_root.rglob("*"):
        if path.suffix.casefold() not in {".pak", ".utoc", ".ucas"}:
            continue
        try:
            stat = path.stat()
            signature.append((
                path.relative_to(pak_root).as_posix().casefold(),
                stat.st_size,
                stat.st_mtime_ns,
            ))
        except OSError:
            continue
    return sorted(signature)


def _mesh_disk_cache_path(cache_key: tuple[str, str, str]) -> Path | None:
    try:
        cache_root = bpy.utils.user_resource('CONFIG')
        if not cache_root:
            return None
        cache_root = Path(cache_root) / "ff7r_rebirth_tools"
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
        if (payload.get("version") != _MESH_CACHE_VERSION or
                tuple(payload.get("config") or []) != cache_key or
                payload.get("packageSignature") != [list(item) for item in package_signature]):
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
        temporary_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
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


def refresh_umap_index(game_root: str, oodle_dll: str, usmap_path: str, *, force=False) -> list[str]:
    global _VIRTUAL_UMAPS, _CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    cache_key = _package_config_key(game_root, oodle_dll, usmap_path)
    if force or cache_key != _CACHE_KEY:
        result = _run_bridge(
            game_root,
            oodle_dll,
            usmap_path,
            path_filter=".umap",
        )
        _VIRTUAL_UMAPS = sorted((
            path for path in result.get("files", [])
            if path.lower().endswith(".umap")
            and "/autogencollision/" not in path.replace("\\", "/").casefold()
        ), key=str.casefold)
        _CACHE_KEY = cache_key
    return _VIRTUAL_UMAPS


def _continent_origin_in_blender(continent: str, scale_factor: float) -> tuple[float, float, float]:
    """Convert an Unreal TargetLocation to this add-on's Blender coordinates."""
    x, y, z = MEC_CONTINENTS[continent]["origin_ue"]
    return x * scale_factor, -y * scale_factor, z * scale_factor


def _aabb_intersects_sphere(bounds_min, bounds_max, center, radius: float) -> bool:
    """Whether the nearest point of a Blender-space AABB is in a sphere."""
    distance_sq = 0.0
    for value, minimum, maximum in zip(center, bounds_min, bounds_max):
        if value < minimum:
            distance_sq += (minimum - value) ** 2
        elif value > maximum:
            distance_sq += (value - maximum) ** 2
    return distance_sq <= radius * radius


# A character's KineDriver rig can span several assets: the main pre-physics
# ``<stem>_KDI.uasset`` plus optional secondary passes named ``<stem>_KDI_<suffix>``
# -- Extra1, Head, Hood, StBody, StHair, Extra_Hand are the suffixes Rebirth ships.
# Per a third-party UE4SS capture of the KBD asset user data, the ``_Extra1`` pass is
# the game's *post-physics* KineDriver list (it runs after Bonamik, which this add-on
# does not simulate), so treat these as a best-effort extra layer rather than an
# exact reproduction of the in-game result.
# The suffix may itself contain underscores (Rebirth ships _KDI_Extra_Hand).
_KDI_ASSET_PATTERN = re.compile(r"_KDI(_[A-Za-z0-9_]+)?\.uasset$", re.IGNORECASE)


def refresh_kdi_index(game_root: str, oodle_dll: str, usmap_path: str, *, force=False) -> list[str]:
    global _VIRTUAL_KDIS, _KDI_CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    cache_key = _package_config_key(game_root, oodle_dll, usmap_path)
    if force or cache_key != _KDI_CACHE_KEY:
        result = _run_bridge(
            game_root, oodle_dll, usmap_path,
            path_filter="_KDI",
        )
        _VIRTUAL_KDIS = sorted((
            path for path in result.get("files", [])
            if path.lower().endswith(".uasset")
            and _KDI_ASSET_PATTERN.search(os.path.basename(path)) is not None
            and "/autogencollision/" not in path.replace("\\", "/").casefold()
        ), key=str.casefold)
        _KDI_CACHE_KEY = cache_key
    return _VIRTUAL_KDIS


def _search_virtual_kdis(_self, _context, edit_text):
    return _search_virtual_paths(_VIRTUAL_KDIS, edit_text)


def refresh_skeleton_index(game_root: str, oodle_dll: str, usmap_path: str, *, force=False) -> list[str]:
    global _VIRTUAL_SKELETONS, _SKELETON_CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    cache_key = _package_config_key(game_root, oodle_dll, usmap_path)
    if force or cache_key != _SKELETON_CACHE_KEY:
        result = _run_bridge(
            game_root, oodle_dll, usmap_path,
            path_filter="_Skeleton",
        )
        _VIRTUAL_SKELETONS = sorted((
            path for path in result.get("files", [])
            if path.lower().endswith(".uasset")
            and os.path.basename(path).lower().endswith("_skeleton.uasset")
            and "/autogencollision/" not in path.replace("\\", "/").casefold()
        ), key=str.casefold)
        _SKELETON_CACHE_KEY = cache_key
    return _VIRTUAL_SKELETONS


def _search_virtual_skeletons(_self, _context, edit_text):
    return _search_virtual_paths(_VIRTUAL_SKELETONS, edit_text)


def refresh_mesh_indices(
        game_root: str, oodle_dll: str, usmap_path: str, *, force=False
) -> tuple[list[str], list[str]]:
    """Index actual Unreal StaticMesh/SkeletalMesh export classes for the pickers."""
    global _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES, _MESH_CACHE_KEY, _MESH_CACHE_SOURCE
    _validate_paths(game_root, oodle_dll, usmap_path)
    cache_key = _package_config_key(game_root, oodle_dll, usmap_path)
    if force or cache_key != _MESH_CACHE_KEY:
        package_signature = _mesh_package_signature(game_root)
        cache_path = _mesh_disk_cache_path(cache_key)
        disk_cache = None if force else _load_mesh_disk_cache(
            cache_path, cache_key, package_signature
        )
        if disk_cache is not None:
            _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES = disk_cache
            _MESH_CACHE_SOURCE = "disk cache"
        else:
            # Models hold the game mesh assets and keep the one-time initial index practical.
            result = _run_bridge_asset_request(
                game_root,
                oodle_dll,
                usmap_path,
                {"action": "mesh_index", "pathFilter": "/Model/"},
            )
            mesh_index = result.get("meshIndex") or {}
            _VIRTUAL_STATIC_MESHES = sorted(
                mesh_index.get("staticMeshes") or [], key=_natural_path_key
            )
            _VIRTUAL_SKELETAL_MESHES = sorted(
                mesh_index.get("skeletalMeshes") or [], key=_natural_path_key
            )
            failures = mesh_index.get("failures") or []
            if failures:
                print(f"Package mesh index skipped {len(failures):,} unreadable package(s).")
            _save_mesh_disk_cache(
                cache_path, cache_key, package_signature,
                _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES,
            )
            _MESH_CACHE_SOURCE = "fresh package scan"
        _MESH_CACHE_KEY = cache_key
    return _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES


def _search_virtual_static_meshes(_self, _context, edit_text):
    return _search_virtual_paths(
        _VIRTUAL_STATIC_MESHES, edit_text, sort_key=_natural_path_key
    )


def _search_virtual_skeletal_meshes(_self, _context, edit_text):
    return _search_virtual_paths(
        _VIRTUAL_SKELETAL_MESHES, edit_text, sort_key=_natural_path_key
    )


_MESH_SEARCH_POPULATING = False


def _mesh_search_source(operator) -> list[str]:
    if operator.mesh_search_kind == "SKELETAL":
        return _VIRTUAL_SKELETAL_MESHES
    return _VIRTUAL_STATIC_MESHES


def _populate_mesh_search(operator) -> None:
    """Populate an inline list in natural order, bypassing Blender's fuzzy ranking."""
    global _MESH_SEARCH_POPULATING
    matches = _search_virtual_paths(
        _mesh_search_source(operator),
        operator.mesh_search_text,
        sort_key=_natural_path_key,
    )
    selected_path = operator.virtual_path
    selected_index = -1
    _MESH_SEARCH_POPULATING = True
    try:
        operator.mesh_search_results.clear()
        for index, path in enumerate(matches):
            entry = operator.mesh_search_results.add()
            entry.virtual_path = path
            if path == selected_path:
                selected_index = index
        operator.mesh_search_result_index = selected_index
    finally:
        _MESH_SEARCH_POPULATING = False


def _mesh_search_filter_changed(operator, _context):
    _populate_mesh_search(operator)


def _mesh_search_selection_changed(operator, _context):
    if _MESH_SEARCH_POPULATING:
        return
    index = operator.mesh_search_result_index
    if 0 <= index < len(operator.mesh_search_results):
        operator.virtual_path = operator.mesh_search_results[index].virtual_path


class FF7R_PG_mesh_search_entry(bpy.types.PropertyGroup):
    virtual_path: bpy.props.StringProperty()


class FF7R_UL_mesh_search_results(bpy.types.UIList):
    def draw_item(
            self, _context, layout, _data, item, _icon,
            _active_data, _active_propname, _index,
    ):
        layout.label(text=item.virtual_path, icon='MESH_DATA')


def _draw_mesh_search(layout, operator) -> None:
    layout.prop(operator, "virtual_path", icon='PACKAGE')
    layout.prop(operator, "mesh_search_text", text="Search", icon='VIEWZOOM')
    layout.template_list(
        FF7R_UL_mesh_search_results.__name__,
        operator.mesh_search_kind,
        operator,
        "mesh_search_results",
        operator,
        "mesh_search_result_index",
        rows=7,
    )


def refresh_animation_index(
        game_root: str,
        oodle_dll: str,
        usmap_path: str,
        skeleton_asset_path: str,
        *,
        force=False,
) -> list[str]:
    """Find AnimSequence assets explicitly linked to one game Skeleton."""
    global _VIRTUAL_ANIMATIONS, _ANIMATION_CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    skeleton_asset_path = skeleton_asset_path.replace("\\", "/").lstrip("/")
    cache_key = (*_package_config_key(game_root, oodle_dll, usmap_path), skeleton_asset_path.casefold())
    if force or cache_key != _ANIMATION_CACHE_KEY:
        # Animation packages are distributed through field, battle, and cutscene
        # folders, but character clips consistently carry the Skeleton's family
        # token (for example PC0000_00) in their virtual path.  This is much
        # faster than deserializing the complete game on every armature click.
        skeleton_stem = Path(skeleton_asset_path).stem
        search_token = re.sub(r"_Skeleton$", "", skeleton_stem, flags=re.IGNORECASE)
        response = _run_bridge_asset_request(
            game_root,
            oodle_dll,
            usmap_path,
            {
                "action": "animation_index",
                "skeletonAssetPath": skeleton_asset_path,
                "searchToken": search_token,
            },
        )
        index = response.get("animationIndex") or {}
        _VIRTUAL_ANIMATIONS = sorted({
            str(item.get("assetPath"))
            for item in (index.get("animations") or [])
            if isinstance(item, dict) and item.get("assetPath")
        }, key=_natural_path_key)
        failures = int(index.get("failures") or 0)
        if failures:
            print(f"Package animation index skipped {failures:,} unreadable package(s).")
        _ANIMATION_CACHE_KEY = cache_key
    return _VIRTUAL_ANIMATIONS


def _search_virtual_animations(_self, _context, edit_text):
    return _search_virtual_paths(
        _VIRTUAL_ANIMATIONS, edit_text, sort_key=_natural_path_key
    )


def refresh_cutscene_index(game_root: str, oodle_dll: str, usmap_path: str, *, force=False) -> list[str]:
    """Index cutscene roots by their required Camera sequence package."""
    global _VIRTUAL_CUTSCENES, _CUTSCENE_CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    cache_key = _package_config_key(game_root, oodle_dll, usmap_path)
    if force or cache_key != _CUTSCENE_CACHE_KEY:
        result = _run_bridge(game_root, oodle_dll, usmap_path, path_filter="/Cut/Game/")
        _VIRTUAL_CUTSCENES = sorted(
            (path for path in result.get("files", [])
             if path.casefold().endswith("_camera.uasset") and "/cut/game/" in path.casefold()),
            key=str.casefold,
        )
        _CUTSCENE_CACHE_KEY = cache_key
    return _VIRTUAL_CUTSCENES


def _cutscene_display_path(virtual_path: str) -> str:
    marker = "/cut/game/"
    lowered = virtual_path.casefold()
    offset = lowered.find(marker)
    display = virtual_path[offset + len(marker):] if offset >= 0 else virtual_path
    suffix = "_Camera.uasset"
    return display[:-len(suffix)] if display.casefold().endswith(suffix.casefold()) else display


_CUTSCENE_SEARCH_POPULATING = False


def _populate_cutscene_search(operator) -> None:
    global _CUTSCENE_SEARCH_POPULATING
    matches = _search_virtual_paths(_VIRTUAL_CUTSCENES, operator.cutscene_search_text)
    _CUTSCENE_SEARCH_POPULATING = True
    try:
        operator.cutscene_search_results.clear()
        for path in matches:
            entry = operator.cutscene_search_results.add()
            entry.virtual_path = path
            entry.display_path = _cutscene_display_path(path)
    finally:
        _CUTSCENE_SEARCH_POPULATING = False


def _cutscene_search_filter_changed(operator, _context):
    _populate_cutscene_search(operator)


def _cutscene_search_selection_changed(operator, _context):
    if _CUTSCENE_SEARCH_POPULATING:
        return
    index = operator.cutscene_search_result_index
    if 0 <= index < len(operator.cutscene_search_results):
        operator.virtual_path = operator.cutscene_search_results[index].virtual_path


class FF7R_PG_cutscene_search_entry(bpy.types.PropertyGroup):
    virtual_path: bpy.props.StringProperty()
    display_path: bpy.props.StringProperty()


class FF7R_UL_cutscene_search_results(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.display_path, icon='SEQUENCE')


def _entry_selection_changed(entry, _context):
    if entry.is_directory or not entry.virtual_path:
        return
    if entry.selected:
        _SELECTED_UMAPS.add(entry.virtual_path)
    else:
        _SELECTED_UMAPS.discard(entry.virtual_path)


class FF7R_PG_package_browser_entry(bpy.types.PropertyGroup):
    display_name: bpy.props.StringProperty()
    virtual_path: bpy.props.StringProperty()
    is_directory: bpy.props.BoolProperty(default=False)
    selected: bpy.props.BoolProperty(default=False, update=_entry_selection_changed)


def _browser_filter_changed(_state, context):
    _populate_browser(context)


class FF7R_PG_package_browser_state(bpy.types.PropertyGroup):
    entries: bpy.props.CollectionProperty(type=FF7R_PG_package_browser_entry)
    active_index: bpy.props.IntProperty(default=0)
    current_directory: bpy.props.StringProperty(default="End/Content")
    filter_text: bpy.props.StringProperty(
        name="Search",
        description="Filter package UMAPs by any part of their virtual path",
        options={'TEXTEDIT_UPDATE'},
        update=_browser_filter_changed,
    )


def _browser_state(context):
    return context.window_manager.ff7r_package_browser


def _populate_browser(context) -> None:
    state = _browser_state(context)
    state.entries.clear()
    terms = _package_search_terms(state.filter_text)
    if terms:
        rows = [
            (path, path, False) for path in _VIRTUAL_UMAPS
            if _path_matches_package_search(path, terms)
        ]
    else:
        directory = state.current_directory.strip("/") or "End/Content"
        prefix = directory + "/"
        folders: dict[str, str] = {}
        files: list[tuple[str, str, bool]] = []
        for path in _VIRTUAL_UMAPS:
            if not path.casefold().startswith(prefix.casefold()):
                continue
            remainder = path[len(prefix):]
            if "/" in remainder:
                child = remainder.split("/", 1)[0]
                folders.setdefault(child.casefold(), prefix + child)
            else:
                files.append((remainder, path, False))
        rows = [
            (folder_path.rsplit("/", 1)[-1], folder_path, True)
            for folder_path in sorted(folders.values(), key=str.casefold)
        ]
        rows.extend(sorted(files, key=lambda row: row[0].casefold()))

    for display_name, virtual_path, is_directory in rows:
        entry = state.entries.add()
        entry.display_name = display_name
        entry.virtual_path = virtual_path
        entry.is_directory = is_directory
        entry.selected = virtual_path in _SELECTED_UMAPS
    state.active_index = min(state.active_index, max(0, len(state.entries) - 1))


class FF7R_UL_package_umaps(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        if item.is_directory:
            op = layout.operator(
                FF7R_REBIRTH_OT_package_browser_folder.bl_idname,
                text=item.display_name,
                icon='FILE_FOLDER',
                emboss=False,
            )
            op.virtual_path = item.virtual_path
        else:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")
            row.label(text=item.display_name, icon='FILE')


class FF7R_REBIRTH_OT_package_browser_folder(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_rebirth_package_folder"
    bl_label = "Open Package Folder"
    bl_options = {'INTERNAL'}
    virtual_path: bpy.props.StringProperty()

    def execute(self, context):
        global _LAST_UMAP_BROWSER_DIRECTORY
        state = _browser_state(context)
        state.current_directory = self.virtual_path.strip("/") or "End/Content"
        _LAST_UMAP_BROWSER_DIRECTORY = state.current_directory
        state.filter_text = ""
        _populate_browser(context)
        return {'FINISHED'}


class FF7R_REBIRTH_OT_package_browser_up(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_rebirth_package_up"
    bl_label = "Parent Folder"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _LAST_UMAP_BROWSER_DIRECTORY
        state = _browser_state(context)
        parent = state.current_directory.rstrip("/").rsplit("/", 1)[0]
        state.current_directory = (
            parent if parent.casefold().startswith("end/content") else "End/Content"
        )
        _LAST_UMAP_BROWSER_DIRECTORY = state.current_directory
        state.filter_text = ""
        _populate_browser(context)
        return {'FINISHED'}


class FF7R_REBIRTH_OT_package_browser_select(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_rebirth_package_select"
    bl_label = "Change Package Selection"
    bl_options = {'INTERNAL'}
    mode: bpy.props.EnumProperty(items=(
        ('SELECT', "Select Visible", "Select every visible UMAP"),
        ('CLEAR', "Clear All", "Clear the complete batch selection"),
        ('INVERT', "Invert Visible", "Invert visible UMAP selections"),
    ))

    def execute(self, context):
        state = _browser_state(context)
        if self.mode == 'CLEAR':
            _SELECTED_UMAPS.clear()
        for entry in state.entries:
            if entry.is_directory:
                continue
            if self.mode == 'SELECT':
                entry.selected = True
            elif self.mode == 'INVERT':
                entry.selected = not entry.selected
            else:
                entry.selected = False
        _populate_browser(context)
        return {'FINISHED'}


def _texture_package_path(
        game_path: str,
        *,
        profile=REBIRTH_PROFILE,
) -> tuple[str, str]:
    """Turn a texture object path into the active title's mounted package path."""
    package_path = game_path.split(":", 1)[0]
    slash = package_path.rfind("/")
    dot = package_path.rfind(".")
    if dot > slash:
        package_path = package_path[:dot]
    path_parts = profile.package_relative_path
    content_root = "/".join(
        path_parts[:-1] if path_parts and path_parts[-1].casefold() == "paks" else path_parts
    )
    if package_path.casefold().startswith("/game/"):
        virtual_path = content_root + "/" + package_path[6:]
    elif package_path.casefold().startswith(content_root.casefold() + "/"):
        virtual_path = package_path
    elif package_path.casefold().startswith("/engine/"):
        virtual_path = "Engine/Content/" + package_path[8:]
    else:
        raise ValueError(f"Unsupported Unreal texture path: {game_path}")
    stem = virtual_path.rsplit("/", 1)[-1]
    return virtual_path + ".uasset", stem


def _game_asset_path_to_virtual_umap(asset_path: str) -> str | None:
    """Convert a streamed /Game package reference to its mounted UMAP path."""
    if not isinstance(asset_path, str):
        return None
    path = asset_path.strip().strip("'")
    if "'" in path:
        path = path.split("'", 1)[1].rsplit("'", 1)[0]
    if not path.casefold().startswith("/game/"):
        return None
    package_path = path.split(".", 1)[0]
    return "End/Content/" + package_path[6:] + ".umap"


def _continent_root_streaming_map(continent: str) -> str:
    root_map = MEC_CONTINENTS[continent]["root_map"]
    return f"End/Content/Level/Game/Field/{root_map}/{root_map}.umap"


def _continent_streaming_root_candidates(
        virtual_umaps: list[str], continent: str,
) -> list[str]:
    """Find top-level field maps that own streaming volumes for a continent.

    The continent map is not the only world root.  Gold Saucer, for example,
    is ``2350-GOLDS``: it shares West's coordinate frame but owns the volumes
    that select its Square terrain.  Limit probing to a field map's root UMAP
    (``.../2350-GOLDS/2350-GOLDS.umap``), rather than opening every child
    layout/MEC package.
    """
    prefix = str(MEC_CONTINENTS[continent]["level_prefix"])
    candidates: dict[str, str] = {}
    for asset_path in virtual_umaps:
        normalized = str(asset_path).replace("\\", "/")
        parts = normalized.rsplit("/", 2)
        if len(parts) != 3:
            continue
        parent, folder, filename = parts
        if not parent.casefold().endswith("/level/game/field"):
            continue
        if not re.fullmatch(rf"{re.escape(prefix)}\d{{3}}-[^/]+", folder, re.IGNORECASE):
            continue
        if not filename.casefold().endswith(".umap"):
            continue
        if filename[:-5].casefold() != folder.casefold():
            continue
        candidates.setdefault(normalized.casefold(), normalized)

    # Include the established continent root even if a title update or an
    # incomplete mount index omitted it from the candidate listing.
    continent_root = _continent_root_streaming_map(continent)
    candidates.setdefault(continent_root.casefold(), continent_root)
    return sorted(candidates.values(), key=_natural_path_key)


def _streaming_level_asset_paths(value) -> list[str]:
    """Flatten CUE4Parse's single-item/list representations of StreamingLevels."""
    if isinstance(value, dict):
        asset_path = value.get("AssetPathName")
        if isinstance(asset_path, str):
            return [asset_path]
        for nested in value.values():
            paths = _streaming_level_asset_paths(nested)
            if paths:
                return paths
        return []
    if isinstance(value, (list, tuple)):
        paths = []
        for item in value:
            paths.extend(_streaming_level_asset_paths(item))
        return paths
    return [value] if isinstance(value, str) and value else []


def _nearby_streaming_level_paths(
        streaming_probe: dict,
        location_ue: tuple[float, float, float],
        radius_ue: float,
) -> list[str]:
    """Select the package levels the game's root map streams near one point.

    The root map's EndStreamingVolume brush is the authoritative level-selection
    rule.  Geometry bounds are deliberately not consulted here: once a level is
    chosen by its brush, its MEC component is imported as a whole, as the game
    does.  High-spec-only volumes are excluded because this operator is the
    deliberately coarse context loader.
    """
    selected: dict[str, str] = {}
    for volume in streaming_probe.get("streamingVolumes") or []:
        properties = volume.get("properties") or {}
        if properties.get("bDisabled"):
            continue
        target_type = str(properties.get("StreamingTarget") or "")
        if "HighSpecOnly" in target_type or "Editor" in target_type:
            continue

        bounds_min = volume.get("boundsWorldMin")
        bounds_max = volume.get("boundsWorldMax")
        if bounds_min is not None and bounds_max is not None:
            if not _aabb_intersects_sphere(
                    bounds_min, bounds_max, location_ue, radius_ue):
                continue
        elif not properties.get("bForce"):
            # A volume without a brush cannot be spatially tested.  It is not a
            # nearby-level candidate unless the game marks it permanently loaded.
            continue

        for asset_path in _streaming_level_asset_paths(properties.get("StreamingLevels")):
            virtual_path = _game_asset_path_to_virtual_umap(asset_path)
            if virtual_path is not None:
                selected.setdefault(virtual_path.casefold(), virtual_path)
    return sorted(selected.values(), key=_natural_path_key)


def _game_asset_path_to_virtual_uasset(
        asset_path: str,
        *,
        profile=REBIRTH_PROFILE,
) -> str | None:
    """Convert a UE ObjectName such as StaticMesh'/Game/A/B.B' to a package path."""
    if not isinstance(asset_path, str):
        return None
    path = asset_path.strip().strip("'")
    if "'" in path:
        parts = path.split("'", 2)
        if len(parts) >= 2:
            path = parts[1]
    path = path.split(":", 1)[0].strip()
    package_path = path.split(".", 1)[0]
    # ``package_relative_path`` identifies the on-disk Paks directory; virtual
    # package paths stop one segment earlier at the Unreal content root.
    path_parts = profile.package_relative_path
    content_root = "/".join(
        path_parts[:-1] if path_parts and path_parts[-1].casefold() == "paks" else path_parts
    )
    if package_path.casefold().startswith("/game/"):
        return content_root + "/" + package_path[6:] + ".uasset"
    # Conventional package exports may expose an FPackageIndex as an already
    # mounted virtual path (for example ``End/Content/.../Wall.1``) instead of
    # the ``/Game/...`` object path used by Rebirth IoStore packages.  Both
    # describe the same asset; retain the title's own content root and discard
    # only the UE object suffix before addressing the package bridge.
    if package_path.casefold().startswith(content_root.casefold() + "/"):
        return package_path + ".uasset"
    if package_path.casefold().startswith("/engine/"):
        return "Engine/Content/" + package_path[8:] + ".uasset"
    return None


class PackageAssetSession:
    """Keep CUE4Parse mounted for a complete multi-asset import batch."""

    UMAP_RESTART_WORKING_SET_MB = 2048

    def __init__(
        self,
        game_root: str,
        oodle_dll: str,
        usmap_path: str,
        *,
        profile=REBIRTH_PROFILE,
    ):
        self.game_root = game_root
        self.oodle_dll = oodle_dll
        self.usmap_path = usmap_path
        self.profile = profile
        self.process = None
        self.cache: dict[str, bpy.types.Image | None] = {}
        self.material_cache: dict[str, dict] = {}
        self.loaded = 0
        self.failed = 0

    def __enter__(self):
        self._start_process()
        return self

    def _start_process(self):
        command = _bridge_command(
            self.game_root,
            self.oodle_dll,
            self.usmap_path,
            "-",
            profile=self.profile,
            operation="asset-server",
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def _stop_process(self):
        if self.process is not None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=10)
            except Exception:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except Exception:
                    self.process.kill()
            finally:
                self.process = None

    def __exit__(self, _exc_type, _exc, _traceback):
        self._stop_process()
        if self.loaded or self.failed:
            print(f"Package textures: {self.loaded} packed DDS image(s), {self.failed} failed")

    def release_batch_memory(self) -> dict:
        """Release transient package data and recycle a bridge that remains large."""
        threshold_bytes = self.UMAP_RESTART_WORKING_SET_MB * 1024 * 1024
        response = self.request({
            "action": "release_batch_memory",
            "restartThresholdBytes": threshold_bytes,
        })
        memory = response.get("memory") or {}
        if memory.get("restartRecommended"):
            working_set_mb = int(memory.get("workingSetBytes") or 0) / (1024 * 1024)
            print(
                f"Package bridge retained {working_set_mb:,.0f} MiB after cleanup; "
                "recycling it before the next map."
            )
            self._stop_process()
            self._start_process()
        return memory

    def request(self, payload: dict, *, report_errors: bool = True) -> dict:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("The package bridge is not running.")
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        response_line = self.process.stdout.readline()
        if not response_line:
            raise RuntimeError("The package bridge stopped unexpectedly.")
        response = json.loads(response_line)
        if not response.get("ok"):
            details = response.get("errorDetails")
            if details and report_errors:
                print("[FF7R bridge ERROR] " + str(details))
            raise RuntimeError(response.get("error") or "Unknown package bridge error")
        return response

    def extract_raw(
        self,
        asset_path: str,
        output_path: str,
        *,
        report_errors: bool = True,
    ) -> None:
        self.request(
            {"action": "raw", "assetPath": asset_path, "output": output_path},
            report_errors=report_errors,
        )

    def import_names(self, asset_path: str) -> list[str | None]:
        response = self.request({"action": "metadata", "assetPath": asset_path})
        return response.get("importNames") or []

    def kdi_asset(self, asset_path: str) -> dict:
        return self.request({"action": "kdi", "assetPath": asset_path}).get("kdi") or {}

    def skeleton_asset(self, asset_path: str) -> dict:
        return self.request({"action": "skeleton", "assetPath": asset_path}).get("skeleton") or {}

    def animation_asset(self, asset_path: str, *, report_errors: bool = True) -> dict:
        return self.request(
            {"action": "animation", "assetPath": asset_path},
            report_errors=report_errors,
        ).get("animation") or {}

    def static_mesh(self, asset_path: str) -> dict:
        return self.request({"action": "static_mesh", "assetPath": asset_path}).get("staticMesh") or {}

    def material_instance(self, asset_path: str) -> dict:
        cache_key = asset_path.casefold()
        if cache_key not in self.material_cache:
            self.material_cache[cache_key] = self.request(
                {"action": "material", "assetPath": asset_path}
            ).get("material") or {}
        return self.material_cache[cache_key]

    def niagara_asset(self, asset_path: str) -> dict:
        """Return the bridge's partial Niagara report for one system package."""
        return self.request({"action": "niagara", "assetPath": asset_path}).get("niagara") or {}

    def skeletal_mesh(self, asset_path: str, *, report_errors: bool = True) -> dict:
        return self.request(
            {"action": "skeletal_mesh", "assetPath": asset_path},
            report_errors=report_errors,
        ).get("skeletalMesh") or {}

    def skeleton_bone_usage(self, asset_path: str, search_path: str) -> dict:
        return self.request({
            "action": "skeleton_bone_usage",
            "assetPath": asset_path,
            "searchPath": search_path,
        }).get("skeletonBoneUsage") or {}

    def skeleton_users(self, asset_path: str, search_path: str) -> list[dict]:
        """Return package SkeletalMeshes that use one Skeleton in its model family."""
        return self.request({
            "action": "skeleton_users",
            "assetPath": asset_path,
            "searchPath": search_path,
        }).get("users") or []

    def umap_actors(self, asset_path: str) -> dict:
        return self.request({"action": "umap_actors", "assetPath": asset_path}).get("umapActors") or {}

    def umap_data(self, asset_path: str) -> tuple[list[str | None], dict]:
        response = self.request({"action": "umap_data", "assetPath": asset_path})
        return response.get("importNames") or [], response.get("umapActors") or {}

    def streaming_probe(self, asset_path: str) -> dict:
        return self.request(
            {"action": "streaming_probe", "assetPath": asset_path}
        ).get("streamingProbe") or {}

    def cutscene_asset(self, asset_path: str) -> dict:
        """Decode an EndCinemaSequence package into FModel-compatible exports."""
        return self.request({"action": "cutscene", "assetPath": asset_path}).get("cutscene") or {}

    def __call__(self, game_path: str):
        cache_key = game_path.casefold()
        if cache_key in self.cache:
            return self.cache[cache_key]

        for image in bpy.data.images:
            if image.get("ff7r_virtual_path", "").casefold() == cache_key:
                self.cache[cache_key] = image
                return image

        temp_path = ""
        temp_dir = None
        try:
            asset_path, image_name = _texture_package_path(
                game_path, profile=self.profile
            )
            # Blender records the source file's basename when packing an image,
            # then uses that recorded name when the Blend file is unpacked. Give
            # the bridge a disposable directory but retain the DDS's game name
            # instead of NamedTemporaryFile's random ``tmp...`` basename.
            temp_dir = tempfile.TemporaryDirectory(prefix="ff7r_texture_")
            temp_path = os.path.join(temp_dir.name, f"{image_name}.dds")
            response = self.request({
                "action": "texture",
                "assetPath": asset_path,
                "ddsOutput": temp_path,
            })
            dds_info = response.get("dds") or {}
            if int(dds_info.get("byteLength") or 0) <= 128:
                raise RuntimeError(
                    f"CUE4Parse returned no usable DDS payload for {dds_info.get('pixelFormat', 'unknown format')}"
                )
            image = bpy.data.images.load(temp_path, check_existing=False)
            if image.size[0] <= 0 or image.size[1] <= 0:
                bpy.data.images.remove(image)
                raise RuntimeError("Blender could not decode the extracted DDS payload.")
            image.name = image_name
            image["ff7r_virtual_path"] = game_path
            image["ff7r_pixel_format"] = dds_info.get("pixelFormat", "")
            image.pack()
            self.cache[cache_key] = image
            self.loaded += 1
            return image
        except Exception as exc:
            print(f"  Warning: package texture '{game_path}' could not be loaded: {exc}")
            self.cache[cache_key] = None
            self.failed += 1
            return None
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()


def _static_mesh_material(name: str, virtual_path: str):
    """Reuse an imported package material placeholder when possible."""
    if virtual_path:
        path_key = virtual_path.casefold()
        for material in bpy.data.materials:
            if material.get("ff7r_virtual_path", "").casefold() == path_key:
                return material
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)
    if virtual_path:
        material["ff7r_virtual_path"] = virtual_path
    return material


def _apply_face_y_forward(vectors: np.ndarray) -> np.ndarray:
    """Rotate an (N, 3) array of already-UE-mirrored Blender vectors -90 deg about Z.

    The base UE->Blender conversion elsewhere in this module is the mirror
    ``(X, -Y, Z)``. Composing a further -90 degree Z rotation on top of that
    mirror algebraically reduces to swapping the mirrored X/Y columns and
    negating the new Y (see ``face_y_forward`` in ``skeleton/importer.py`` for
    the same identity applied to bones). It is a pure rotation stacked on the
    existing mirror, so it is safe to apply identically to positions, normals,
    and tangents -- the overall handedness flip (needed for the tangent sign)
    is unchanged.
    """
    swapped = vectors[:, [1, 0, 2]].copy()
    swapped[:, 1] *= -1.0
    return swapped


def import_static_mesh_asset(
        context,
        static_mesh: dict,
        virtual_path: str,
        *,
        scale_factor: float = 0.01,
        offset_opposite_faces: bool | str = False,
        material_session: PackageAssetSession | None = None,
        material_builder=None,
        face_y_forward: bool = False,
):
    """Build one Blender mesh from the bridge's selected conventional static-mesh LOD."""
    offset_mode = _normalize_offset_faces_mode(offset_opposite_faces)
    positions = static_mesh.get("positions") or []
    normals = static_mesh.get("normals") or []
    tangents = static_mesh.get("tangents") or []
    uv_channels = static_mesh.get("uvChannels") or []
    colors = static_mesh.get("colors")
    indices = static_mesh.get("indices") or []
    sections = static_mesh.get("sections") or []
    if not positions or len(indices) % 3:
        raise ValueError("The package bridge returned incomplete static-mesh geometry.")
    if len(normals) != len(positions):
        raise ValueError("The package bridge returned a mismatched normal stream.")
    if any(len(channel) != len(positions) for channel in uv_channels):
        raise ValueError("The package bridge returned a mismatched UV stream.")
    if min(indices, default=0) < 0 or max(indices, default=0) >= len(positions):
        raise ValueError("The package bridge returned an out-of-range mesh index.")

    mesh_name = static_mesh.get("name") or Path(virtual_path).stem
    vertices = np.asarray([
        (float(value[0]) * scale_factor,
         -float(value[1]) * scale_factor,
         float(value[2]) * scale_factor)
        for value in positions
    ], dtype=np.float32)
    faces = np.asarray(indices, dtype=np.int32).reshape(-1, 3)
    converted_normals = np.asarray([
        (float(value[0]), -float(value[1]), float(value[2]))
        for value in normals
    ], dtype=np.float32)
    if face_y_forward:
        vertices = _apply_face_y_forward(vertices)
        converted_normals = _apply_face_y_forward(converted_normals)
    offset_count = 0
    if offset_mode == OFFSET_FACES_BAKED:
        offset_count = offset_opposite_face_geometry(
            vertices,
            converted_normals,
            faces,
            offset=scaled_opposite_face_offset(scale_factor),
        )
        if offset_count:
            print(f"  {mesh_name}: offset {offset_count} opposite-face vertices")
    mesh = bpy.data.meshes.new(mesh_name)
    obj = None
    try:
        mesh.from_pydata(vertices.tolist(), [], faces.tolist())
        mesh.update()
        if offset_mode == OFFSET_FACES_BAKED:
            # Store this on the datablock because UMAP actors reuse it after the
            # temporary source object has been removed.
            mesh["ff7r_opposite_face_offset_vertices"] = offset_count
        for polygon in mesh.polygons:
            polygon.use_smooth = True

        if hasattr(mesh, "normals_split_custom_set_from_vertices"):
            mesh.normals_split_custom_set_from_vertices(converted_normals.tolist())

        for channel_index, channel in enumerate(uv_channels):
            # Preserve the names used by Rebirth material parameters, e.g.
            # TextureCoordinate0 / Coordinate0 in the cooked material data.
            layer_name = f"Coordinate{channel_index}"
            uv_layer = mesh.uv_layers.new(name=layer_name)
            for loop in mesh.loops:
                uv = channel[loop.vertex_index]
                uv_layer.data[loop.index].uv = (float(uv[0]), 1.0 - float(uv[1]))

        if colors is not None:
            if len(colors) != len(positions):
                raise ValueError("The package bridge returned a mismatched color stream.")
            color_layer = mesh.color_attributes.new(
                name="Color", type='BYTE_COLOR', domain='POINT'
            )
            for vertex_index, color in enumerate(colors):
                color_layer.data[vertex_index].color = tuple(
                    float(component) / 255.0 for component in color
                )

        if tangents:
            if len(tangents) != len(positions):
                raise ValueError("The package bridge returned a mismatched tangent stream.")
            tangent_layer = mesh.attributes.new(
                name="ff7r_tangent", type='FLOAT_VECTOR', domain='POINT'
            )
            tangent_sign_layer = mesh.attributes.new(
                name="ff7r_tangent_sign", type='FLOAT', domain='POINT'
            )
            # Adding an attribute can reallocate Blender's CustomData array and
            # invalidate an earlier RNA data view. Reacquire both before writes.
            tangent_layer = mesh.attributes["ff7r_tangent"]
            tangent_sign_layer = mesh.attributes["ff7r_tangent_sign"]
            converted_tangents = np.asarray([
                (float(tangent[0]), -float(tangent[1]), float(tangent[2]))
                for tangent in tangents
            ], dtype=np.float32)
            if face_y_forward:
                converted_tangents = _apply_face_y_forward(converted_tangents)
            for vertex_index, tangent in enumerate(tangents):
                tangent_layer.data[vertex_index].vector = tuple(converted_tangents[vertex_index])
                # Mirroring Unreal Y changes the tangent-frame handedness; the
                # optional +90 degree Z rotation on top is a pure rotation and
                # does not affect this sign.
                tangent_sign_layer.data[vertex_index].value = -float(tangent[3])

        material_count = max(
            (int(section.get("materialIndex", -1)) for section in sections),
            default=-1,
        ) + 1
        material_specs = [None] * material_count
        for section in sections:
            material_index = int(section.get("materialIndex", -1))
            if 0 <= material_index < material_count:
                material_specs[material_index] = section
        for material_index, section in enumerate(material_specs):
            section = section or {}
            material_name = section.get("materialName") or f"Material_{material_index}"
            material_path = section.get("materialPath") or ""
            mesh.materials.append(_static_mesh_material(material_name, material_path))
        for section in sections:
            material_index = int(section.get("materialIndex", 0))
            first_face = int(section.get("firstIndex", 0)) // 3
            face_count = int(section.get("triangleCount", 0))
            if not 0 <= material_index < len(mesh.materials):
                continue
            for face_index in range(first_face, min(first_face + face_count, len(mesh.polygons))):
                mesh.polygons[face_index].material_index = material_index

        obj = bpy.data.objects.new(mesh_name, mesh)
        context.collection.objects.link(obj)
        obj["ff7r_virtual_path"] = virtual_path
        obj["ff7r_source_type"] = static_mesh.get("sourceType", "")
        obj["ff7r_render_data"] = static_mesh.get("renderData", "")
        obj["ff7r_static_mesh_lod"] = int(static_mesh.get("lodIndex", 0))
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        if material_session is not None:
            material_builder = material_builder or rmi_surface.build_material
            for material_index, section in enumerate(material_specs):
                section = section or {}
                material_path = section.get("materialPath") or ""
                material_asset = _game_asset_path_to_virtual_uasset(
                    material_path, profile=material_session.profile
                )
                if not material_asset:
                    continue
                try:
                    material_data = material_session.material_instance(material_asset)
                    material = material_builder(
                        section.get("materialName") or f"Material_{material_index}",
                        material_path,
                        material_data,
                        material_session,
                    )
                    if material is not None:
                        mesh.materials[material_index] = material
                except Exception as exc:
                    # Surface material failures must never discard imported mesh data.
                    print(f"  Warning: package material '{material_path}' could not be built: {exc}")
        rmi_surface.initialize_external_emissive_context(obj)
        if offset_mode == OFFSET_FACES_MODIFIER:
            # Use the same implementation as Object > Retrilogy tools >
            # Find Opposite Faces so the generated vertex group, material mask,
            # and Alpha Displace modifier stay identical.
            from .z_fighting import MESH_OT_find_opposite_faces

            if MESH_OT_find_opposite_faces.process_object(obj):
                mesh["ff7r_opposite_face_offset_mode"] = OFFSET_FACES_MODIFIER
        return obj
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


class PackageStaticMeshResolver:
    """Build each game StaticMesh once, then hand its shared mesh datablock to UMAP actors."""

    def __init__(
            self,
            context,
            session: PackageAssetSession,
            scale_factor: float,
            *,
            offset_opposite_faces: bool = False,
            build_materials: bool = True,
            material_builder=None,
    ):
        self.context = context
        self.session = session
        self.scale_factor = scale_factor
        self.offset_opposite_faces = offset_opposite_faces
        self.build_materials = build_materials
        self.material_builder = material_builder
        self._mesh_cache: dict[str, bpy.types.Mesh] = {}

    def __call__(self, asset_path: str):
        virtual_path = _game_asset_path_to_virtual_uasset(
            asset_path, profile=self.session.profile
        )
        if virtual_path is None:
            raise ValueError(f"Unsupported StaticMesh game path: {asset_path!r}")

        cache_key = virtual_path.casefold()
        mesh = self._mesh_cache.get(cache_key)
        if mesh is not None:
            return mesh

        static_mesh = self.session.static_mesh(virtual_path)
        source_obj = import_static_mesh_asset(
            self.context,
            static_mesh,
            virtual_path,
            scale_factor=self.scale_factor,
            offset_opposite_faces=self.offset_opposite_faces,
            material_session=self.session if self.build_materials else None,
            material_builder=self.material_builder,
        )
        mesh = source_obj.data
        bpy.data.objects.remove(source_obj, do_unlink=True)
        mesh["ff7r_virtual_path"] = virtual_path
        self._mesh_cache[cache_key] = mesh
        return mesh


def import_skeletal_mesh_asset(
        context,
        skeletal_mesh: dict,
        virtual_path: str,
        *,
        armature_obj=None,
        scale_factor: float = 0.01,
        offset_opposite_faces: bool | str = False,
        material_session: PackageAssetSession | None = None,
        material_builder=None,
        face_y_forward: bool = False,
):
    """Build a Rebirth SkeletalMesh and transfer its section-local bone weights.

    `material_session` is forwarded untouched to the StaticMesh importer, which
    is where RMI_Surface materials are actually built.  The bridge fills in each
    section's `materialName`/`materialPath` for a SkeletalMesh exactly as it
    does for a StaticMesh (SkeletalMaterials vs StaticMaterials), so the two
    paths need no separate material handling -- passing the session is the whole
    difference between textured and placeholder characters."""
    obj = import_static_mesh_asset(
        context,
        skeletal_mesh,
        virtual_path,
        scale_factor=scale_factor,
        offset_opposite_faces=offset_opposite_faces,
        material_session=material_session,
        material_builder=material_builder,
        face_y_forward=face_y_forward,
    )
    try:
        weighted_vertices, influence_count = bind_skeletal_mesh_object(
            obj, skeletal_mesh, armature_obj
        )

        obj["ff7r_skeletal_mesh_lod"] = int(skeletal_mesh.get("lodIndex", 0))
        obj["ff7r_normal_format"] = skeletal_mesh.get("normalFormat") or ""
        obj["ff7r_linked_skeleton_path"] = skeletal_mesh.get("skeletonPath") or ""
        obj["ff7r_weighted_vertices"] = weighted_vertices
        obj["ff7r_weight_influences"] = influence_count
        return obj, weighted_vertices, influence_count
    except Exception:
        bpy.data.objects.remove(obj, do_unlink=True)
        raise


def bind_skeletal_mesh_object(
        obj,
        skeletal_mesh: dict,
        armature_obj=None,
        *,
        preserve_world_transform: bool = True,
):
    """Add skinning data to an object sharing a package mesh datablock.

    Vertex groups and modifiers belong to Blender Objects, whereas geometry
    belongs to the Mesh datablock.  This lets package UMAP placements share the
    latter without needing a hidden source collection or an empty wrapper.
    """
    bone_names = skeletal_mesh.get("boneNames") or []
    weights = skeletal_mesh.get("weights") or []
    if len(weights) != len(obj.data.vertices):
        raise ValueError("The package bridge returned a mismatched skin-weight stream.")

    vertex_groups = {
        name: obj.vertex_groups.new(name=name)
        for name in bone_names
        if name
    }
    weighted_vertices = 0
    influence_count = 0
    for vertex_index, influences in enumerate(weights):
        has_weight = False
        for influence in influences:
            if len(influence) != 2:
                continue
            bone_index, weight = int(influence[0]), float(influence[1])
            if weight <= 0.0 or not 0 <= bone_index < len(bone_names):
                continue
            group = vertex_groups.get(bone_names[bone_index])
            if group is None:
                continue
            group.add([vertex_index], weight, 'REPLACE')
            has_weight = True
            influence_count += 1
        if has_weight:
            weighted_vertices += 1

    if armature_obj is not None:
        if armature_obj.type != 'ARMATURE':
            raise ValueError("The selected binding object is not an armature.")
        matching_bones = sum(name in armature_obj.data.bones for name in vertex_groups)
        if not matching_bones:
            raise ValueError(f"The selected armature has no bones matching '{obj.name}'.")
        modifier = obj.modifiers.new(name="Armature", type='ARMATURE')
        modifier.object = armature_obj
        modifier.use_deform_preserve_volume = True
        # A mesh imported with its skeleton is a normal child of that armature.
        # Keep an existing selected rig's world-space mesh transform, while map
        # actors deliberately inherit their armature placement as local origin.
        obj.parent = armature_obj
        if preserve_world_transform:
            obj.matrix_parent_inverse = armature_obj.matrix_world.inverted()
        else:
            obj.matrix_parent_inverse.identity()
        obj["ff7r_armature"] = armature_obj.name
        obj["ff7r_matching_bones"] = matching_bones

        limbal_drivers = rmi_surface.configure_limbal_eye_drivers(obj, armature_obj)
        if limbal_drivers:
            obj["ff7r_limbal_eye_drivers"] = limbal_drivers

    return weighted_vertices, influence_count


map_import.configure_package_adapters(
    bind_skeletal_mesh_object=bind_skeletal_mesh_object,
    initialize_external_emissive_context=rmi_surface.initialize_external_emissive_context,
)


class PackageSkeletalMeshResolver:
    """Build each game Skeleton+SkeletalMesh once and share its datablocks."""

    def __init__(
            self,
            context,
            session: PackageAssetSession,
            scale_factor: float,
            *,
            offset_opposite_faces: bool = False,
            build_materials: bool = True,
            material_builder=None,
    ):
        self.context = context
        self.session = session
        self.scale_factor = scale_factor
        self.offset_opposite_faces = offset_opposite_faces
        self.build_materials = build_materials
        self.material_builder = material_builder
        self._asset_cache: dict[str, map_import.SkeletalMeshDatablocks] = {}
        self._skeleton_cache: dict[str, bpy.types.Armature] = {}

    def __call__(self, asset_path: str) -> map_import.SkeletalMeshDatablocks:
        virtual_path = _game_asset_path_to_virtual_uasset(
            asset_path, profile=self.session.profile
        )
        if virtual_path is None:
            raise ValueError(f"Unsupported SkeletalMesh game path: {asset_path!r}")

        cache_key = virtual_path.casefold()
        asset = self._asset_cache.get(cache_key)
        if asset is not None:
            return asset

        # Map components can legitimately reference skeletal packages without
        # a renderable LOD (collision or animation-only environment helpers).
        # Let the map importer classify that expected case without a bridge
        # stack trace, while standalone mesh imports retain full diagnostics.
        skeletal_mesh = self.session.skeletal_mesh(virtual_path, report_errors=False)
        skeleton_path = skeletal_mesh.get("skeletonPath")
        armature_obj = None
        try:
            skeleton_key = (skeleton_path or f"{virtual_path}#inline").casefold()
            armature_data = self._skeleton_cache.get(skeleton_key)
            if armature_data is not None:
                armature_obj = bpy.data.objects.new(armature_data.name, armature_data)
                self.context.collection.objects.link(armature_obj)
            else:
                skeleton = None
                if skeleton_path:
                    try:
                        skeleton = self.session.skeleton_asset(skeleton_path)
                    except Exception as exc:
                        print(
                            f"  Warning: linked Skeleton '{skeleton_path}' could not be loaded; "
                            f"using the SkeletalMesh reference skeleton: {exc}"
                        )
                skeleton = skeleton or skeletal_mesh.get("inlineSkeleton") or {}
                if not skeleton.get("bones"):
                    raise ValueError("The associated Skeleton has no usable linked or inline bones.")
                armature_obj = build_armature_from_bones(
                    self.context,
                    skeleton.get("name") or Path(skeleton_path or virtual_path).stem,
                    _bones_from_bridge(skeleton),
                    skeleton.get("sockets") or [],
                    scale_factor=self.scale_factor,
                    create_socket_empties=False,
                    create_socket_bones=True,
                )
                if skeleton_path:
                    armature_obj[SKELETON_ASSET_PATH_PROPERTY] = skeleton_path
                self._skeleton_cache[skeleton_key] = armature_obj.data
        except Exception as exc:
            print(f"  Warning: Skeleton for '{virtual_path}' could not be built: {exc}")
            armature_obj = None

        mesh_obj, _weighted_vertices, _influence_count = import_skeletal_mesh_asset(
            self.context,
            skeletal_mesh,
            virtual_path,
            armature_obj=armature_obj,
            scale_factor=self.scale_factor,
            offset_opposite_faces=self.offset_opposite_faces,
            material_session=self.session if self.build_materials else None,
            material_builder=self.material_builder,
        )

        mesh = mesh_obj.data
        armature_data = armature_obj.data if armature_obj is not None else None
        if armature_obj is not None:
            # The temporary pair only builds the shared datablocks. Every map
            # actor gets its own ordinary objects below.
            bpy.data.objects.remove(armature_obj, do_unlink=True)
        bpy.data.objects.remove(mesh_obj, do_unlink=True)
        asset = map_import.SkeletalMeshDatablocks(
            mesh=mesh,
            armature=armature_data,
            skeletal_mesh=skeletal_mesh,
            virtual_path=virtual_path,
        )
        self._asset_cache[cache_key] = asset
        return asset


def _cutscene_animation_names(data: list[dict] | None) -> list[str]:
    """Return the package clip names referenced by skeletal sequence sections."""
    names = set()
    for entry in data or []:
        if not isinstance(entry, dict) or entry.get("Type") != "MovieSceneSkeletalAnimationSection":
            continue
        params = entry.get("Properties", {}).get("Params", {})
        name = params.get("RefOnDisconnected") if isinstance(params, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return sorted(names, key=str.casefold)


def _cutscene_actor_ids(data: list[dict] | None, scene_name: str) -> set[str]:
    """Get possessable actor IDs from decoded EndCinemaSequence bindings."""
    actor_ids = set()
    scene_prefix = scene_name + "_"
    for entry in data or []:
        if not isinstance(entry, dict) or entry.get("Type") != "EndCinemaSequence":
            continue
        bindings = entry.get("Properties", {}).get("BindingReferences", {})
        references = bindings.get("BindingIdToReferences", []) if isinstance(bindings, dict) else []
        if not isinstance(references, list):
            continue
        for binding in references:
            refs = binding.get("Value", {}).get("References", []) if isinstance(binding, dict) else []
            external_path = refs[0].get("ExternalObjectPath", {}) if refs else {}
            sub_path = external_path.get("SubPathString", "") if isinstance(external_path, dict) else ""
            actor_name = sub_path.rsplit(".", 1)[-1] if isinstance(sub_path, str) else ""
            if actor_name:
                actor_ids.add(actor_name[len(scene_prefix):] if actor_name.startswith(scene_prefix) else actor_name)
    return actor_ids


def _cutscene_actor_id_for_animation(animation_name: str, actor_ids: set[str]) -> str | None:
    padded_name = f"_{animation_name}_".casefold()
    return next(
        (actor_id for actor_id in sorted(actor_ids, key=len, reverse=True)
         if f"_{actor_id}_".casefold() in padded_name),
        None,
    )


def _armature_from_object(obj) -> bpy.types.Object | None:
    """Find an object's armature root without relying on legacy helper empties."""
    if obj is None:
        return None
    if obj.type == 'ARMATURE':
        return obj
    for candidate in (obj.parent, *obj.children_recursive):
        if candidate is not None and candidate.type == 'ARMATURE':
            return candidate
    return None


def _find_cutscene_armature(scene, actor_id: str | None, skeleton_path: str) -> bpy.types.Object | None:
    """Prefer the bound cutscene actor, falling back to a matching package rig."""
    if actor_id:
        direct = _armature_from_object(scene.objects.get(actor_id))
        if direct is not None:
            return direct
        for obj in scene.objects:
            if obj.get("source_name") == actor_id:
                direct = _armature_from_object(obj)
                if direct is not None:
                    return direct
        # A second actor can use the same Skeleton, but still needs its own mesh.
        return None
    for obj in scene.objects:
        if obj.type == 'ARMATURE' and obj.get(SKELETON_ASSET_PATH_PROPERTY) == skeleton_path:
            return obj
    return None


def _existing_package_animation(virtual_path: str):
    normalized = virtual_path.casefold()
    return next(
        (action for action in bpy.data.actions
         if str(action.get("ff7r_animation_virtual_path", "")).casefold() == normalized),
        None,
    )


def _create_cutscene_skeletal_actor(
        context,
        session: PackageAssetSession,
        skeleton_path: str,
        actor_id: str | None,
        scale_factor: float,
) -> bpy.types.Object:
    """Load a package mesh and parent it to its newly created package rig.

    The rig is built by delegating to the Skeleton package operator rather than
    calling ``build_armature_from_bones`` directly, so a cutscene actor gets the
    same rig the Skeleton and SkeletalMesh importers produce -- KDI drivers (and
    their secondary passes), the C_Limbal eye controller, variant bone
    collections, and the KDI coordinate-profile marker -- instead of a bare
    bone hierarchy.  That operator opens its own short-lived bridge process; the
    session passed in here stays open for the mesh and material fetches below.
    """
    result = bpy.ops.import_scene.ff7r_rebirth_skeleton_game_packages(
        virtual_path=skeleton_path,
        armature_name=actor_id or "",
        scale_factor=scale_factor,
        attachment_sockets=ATTACHMENT_SOCKETS_BONES,
        import_kdi=True,
        create_limbal_bone=True,
        create_variant_bone_collections=True,
    )
    if result != {'FINISHED'}:
        raise RuntimeError(f"Building the cutscene actor's skeleton '{skeleton_path}' failed.")
    armature_obj = context.view_layer.objects.active
    if armature_obj is None or armature_obj.type != 'ARMATURE':
        raise RuntimeError("Could not identify the built cutscene actor armature.")
    armature_obj[SKELETON_ASSET_PATH_PROPERTY] = skeleton_path
    if actor_id:
        armature_obj["source_name"] = actor_id

    model_marker = "/Model/"
    family_path = skeleton_path.split(model_marker, 1)[0] if model_marker in skeleton_path else str(Path(skeleton_path).parent)
    users = session.skeleton_users(skeleton_path, family_path)
    expected_mesh_name = re.sub(r"_Skeleton$", "", Path(skeleton_path).stem, flags=re.IGNORECASE)
    mesh_info = next(
        (item for item in users
         if isinstance(item, dict) and Path(str(item.get("assetPath", ""))).stem.casefold() == expected_mesh_name.casefold()),
        next((item for item in users if isinstance(item, dict) and item.get("assetPath")), None),
    )
    if mesh_info is None:
        print(f"[FF7R Cutscene] No SkeletalMesh package was found for '{skeleton_path}'.")
        return armature_obj

    mesh_path = str(mesh_info["assetPath"])
    skeletal_mesh = session.skeletal_mesh(mesh_path)
    mesh_obj, _weighted_vertices, _influence_count = import_skeletal_mesh_asset(
        context,
        skeletal_mesh,
        mesh_path,
        armature_obj=armature_obj,
        scale_factor=scale_factor,
        offset_opposite_faces=OFFSET_FACES_BAKED,
        material_session=session,
    )
    mesh_obj.name = f"{armature_obj.name}_Mesh"
    if actor_id:
        mesh_obj["source_name"] = actor_id
    return armature_obj


# A cutscene names its props by CutsceneID only (WE0007_00), never by asset
# path -- the path would have come from the uncooked temporary level.
_PROP_ID_PATTERN = re.compile(r"^WE\d{4}_\d{2}$")

# UE attaches a weapon to one of these sockets; the importer already brings
# them in as bones under the rig's "Sockets" collection.
_WEAPON_SOCKET_NAMES = ("Attach_Weapon01", "Attach_Weapon_Right01", "Attach_Weapon_Left01")
# Cloud's sword follows R_Weapon_a, including when he shoulders it in GOLDE_0500.
# Attach_Weapon01 belongs to C_Weapon_b and is not the sword's attachment point.
_WEAPON_SOCKET_NAMES_BY_FAMILY = {"0000": ("Attach_Weapon_Right01",)}


def _resolve_prop_mesh_path(cutscene_id: str, *indexes) -> str | None:
    """Map a CutsceneID such as WE0007_00 to its package mesh by exact stem."""
    suffix = f"/{cutscene_id}.uasset".casefold()
    for index in indexes:
        for path in index or ():
            if path.casefold().endswith(suffix):
                return path
    return None


def _attach_prop_to_owner(context, prop_obj, cutscene_id: str):
    """Constrain a weapon to its owner's socket bone.

    The sequence names the weapon and keys its visibility, but its transform
    track is all zeros -- placement lives in the game's equipment system, not in
    the cutscene.  What the data does give is the owner: a weapon's numeric
    family matches its wielder's (WE0007 -> PC0007), and the rigs carry the
    Attach_Weapon sockets UE parents to.  Reconstructing the attachment from
    those two facts is the only route on cooked data.
    """
    family = cutscene_id[2:6]
    owner = next(
        (obj for obj in context.scene.objects
         if obj.type == 'ARMATURE' and re.match(rf"^PC{family}_\d\d$", obj.name)),
        None,
    )
    if owner is None:
        return None, None
    socket_names = _WEAPON_SOCKET_NAMES_BY_FAMILY.get(family, _WEAPON_SOCKET_NAMES)
    bone = next((n for n in socket_names if n in owner.data.bones), None)
    if bone is None:
        return owner, None
    constraint = prop_obj.constraints.new(type='CHILD_OF')
    constraint.name = "FF7R Weapon Socket"
    constraint.target = owner
    constraint.subtarget = bone
    # Blender creates Child Of with the inverse pending, which holds the object
    # where it already is instead of snapping it onto the socket.  Verified: as
    # created the prop stays 0.373 m from the socket; with the inverse cleared
    # the distance is 0.00000.
    constraint.inverse_matrix.identity()
    if hasattr(constraint, "set_inverse_pending"):
        constraint.set_inverse_pending = False

    # Cancel the socket bone's display roll.  A posed bone's matrix is
    # ``UE_socket_matrix @ DISPLAY_CORRECTION`` (see animations.py), and UE
    # attaches a weapon with an identity transform relative to the socket, so
    # the Child Of basis has to be DISPLAY_CORRECTION's inverse for the prop to
    # land in the UE socket's own frame.  That inverse maps X->+Y, Y->-Z, Z->-X,
    # i.e. -90 deg X then +90 deg Z in local object space -- which is exactly
    # the correction observed by eye on Cloud's back-mounted sword and Barret's
    # gun-arm, two objects asymmetric enough to judge all three axes.
    from .animations import DISPLAY_CORRECTION_INVERSE
    prop_obj.rotation_mode = 'XYZ'
    prop_obj.rotation_euler = DISPLAY_CORRECTION_INVERSE.to_euler('XYZ')
    return owner, bone


def _apply_cutscene_prop_attachment_events(context, attachment_events) -> int:
    """Key prop ownership from EndCinema's serialized attachment events."""
    applied = 0
    events_by_prop: dict[str, list[dict]] = {}
    for event in attachment_events or ():
        actor_match = re.search(r"(WE\d{4}_\d\d)$", str(event.get("actor", "")))
        parent_match = re.search(r"((?:PC|FA)\d{4}_\d\d)$", str(event.get("parent", "")))
        if actor_match is None or parent_match is None or not event.get("socket"):
            continue
        event = dict(event)
        event["prop_id"] = actor_match.group(1)
        event["parent_id"] = parent_match.group(1)
        events_by_prop.setdefault(event["prop_id"], []).append(event)

    for prop_id, events in events_by_prop.items():
        prop_obj = context.scene.objects.get(prop_id)
        if prop_obj is None:
            continue
        static_constraint = prop_obj.constraints.get("FF7R Weapon Socket")
        if static_constraint is not None:
            prop_obj.constraints.remove(static_constraint)
        for constraint in list(prop_obj.constraints):
            if constraint.name.startswith("FF7R Cutscene Socket "):
                prop_obj.constraints.remove(constraint)
        events.sort(key=lambda event: int(event["tick"]))
        for index, event in enumerate(events):
            owner = context.scene.objects.get(event["parent_id"])
            socket = str(event["socket"])
            if owner is None or owner.type != 'ARMATURE' or socket not in owner.data.bones:
                print(f"[FF7R Cutscene] Attachment skipped: {prop_id} -> "
                      f"{event['parent_id']}:{socket}")
                continue
            constraint = prop_obj.constraints.new(type='CHILD_OF')
            constraint.name = f"FF7R Cutscene Socket {index + 1}"
            constraint.target = owner
            constraint.subtarget = socket
            constraint.inverse_matrix.identity()
            # Constraint sequences use the shared 24,000 Hz movie-scene clock;
            # at their 30 fps display rate there are 800 ticks per Blender frame.
            start = float(event["tick"]) / 800.0
            end = (float(events[index + 1]["tick"]) / 800.0
                   if index + 1 < len(events) else None)
            constraint.influence = 0.0
            constraint.keyframe_insert("influence", frame=start - 1.0)
            constraint.influence = 1.0
            constraint.keyframe_insert("influence", frame=start)
            if end is not None:
                constraint.keyframe_insert("influence", frame=end - 1.0)
                constraint.influence = 0.0
                constraint.keyframe_insert("influence", frame=end)
            action = prop_obj.animation_data.action if prop_obj.animation_data else None
            data_path = f'constraints["{constraint.name}"].influence'
            if action is not None:
                curves = getattr(action, "fcurves", None)
                if curves is None:
                    slot = getattr(prop_obj.animation_data, "action_slot", None)
                    channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
                    curves = channelbag.fcurves
                curve = curves.find(data_path)
                if curve is not None:
                    for keyframe in curve.keyframe_points:
                        keyframe.interpolation = 'CONSTANT'
                    curve.update()
            applied += 1
    return applied


def _load_cutscene_prop_assets(
        context,
        session: PackageAssetSession,
        character_data: list[dict] | None,
        scene_name: str,
        scale_factor: float,
        skeletal_meshes,
        static_meshes,
) -> int:
    """Import weapon props bound by the sequence but carrying no animation.

    These are possessables like WE0007_00 (Cait Sith's megaphone) that
    ``_load_cutscene_character_assets`` never reaches, because that walks
    animation clips and a prop has none.  Naming the object after its
    CutsceneID is what lets the existing visibility keying find it.
    """
    loaded = 0
    for cutscene_id in sorted(_cutscene_actor_ids(character_data, scene_name)):
        if not _PROP_ID_PATTERN.match(cutscene_id):
            continue
        if context.scene.objects.get(cutscene_id) is not None:
            continue
        mesh_path = _resolve_prop_mesh_path(cutscene_id, skeletal_meshes, static_meshes)
        if mesh_path is None:
            print(f"[FF7R Cutscene] No package mesh for prop '{cutscene_id}'.")
            continue
        try:
            prop_obj, _weighted, _influences = import_skeletal_mesh_asset(
                context,
                session.skeletal_mesh(mesh_path),
                mesh_path,
                armature_obj=None,
                scale_factor=scale_factor,
                offset_opposite_faces=OFFSET_FACES_BAKED,
                material_session=session,
            )
        except Exception as exc:
            print(f"[FF7R Cutscene] Prop '{cutscene_id}' could not be loaded: {exc}")
            continue
        prop_obj.name = cutscene_id
        prop_obj["source_name"] = cutscene_id
        if prop_obj.name != cutscene_id:
            print(f"[FF7R Cutscene] Prop '{cutscene_id}' renamed to "
                  f"'{prop_obj.name}'; visibility keying will not find it.")
        owner, bone = _attach_prop_to_owner(context, prop_obj, cutscene_id)
        loaded += 1
        where = f" -> {owner.name}:{bone}" if bone else (
            f" -> {owner.name} (no Attach_Weapon socket)" if owner else " (no owner rig)")
        print(f"[FF7R Cutscene] Prop '{cutscene_id}' from {mesh_path}{where}")
    return loaded


def _load_cutscene_character_assets(
        context,
        session: PackageAssetSession,
        root: str,
        character_data: list[dict] | None,
        scene_name: str,
        scale_factor: float,
) -> tuple[int, int]:
    """Ensure the cutscene's character rigs, meshes, and referenced clips exist."""
    from . import animations

    actor_ids = _cutscene_actor_ids(character_data, scene_name)
    package_directory = root.rsplit("/", 1)[0]
    animation_names = _cutscene_animation_names(character_data)
    loaded_rigs = 0
    loaded_actions = 0
    window_manager = context.window_manager
    workspace = context.workspace
    window_manager.progress_begin(0, max(1, len(animation_names)))
    try:
        for animation_index, animation_name in enumerate(animation_names, 1):
            window_manager.progress_update(animation_index - 1)
            if workspace is not None:
                workspace.status_text_set(
                    f"FF7R: loading cutscene animation {animation_index}/{len(animation_names)} "
                    f"({animation_name})"
                )
            if animation_index == 1 or animation_index % 10 == 0:
                print(
                    f"[FF7R Cutscene] Loading animation {animation_index}/"
                    f"{len(animation_names)}: {animation_name}"
                )
            facial = animation_name.casefold().endswith("_fa")
            candidate_paths = (
                [f"{package_directory}/Facial/JP/{animation_name}.uasset",
                 f"{package_directory}/Facial/US/{animation_name}.uasset"]
                if facial else [f"{package_directory}/Motion/{animation_name}.uasset"]
            )
            virtual_path = next(
                (path for path in candidate_paths if _existing_package_animation(path)),
                None,
            )
            animation = None
            if virtual_path is None:
                for candidate in candidate_paths:
                    try:
                        animation = session.animation_asset(candidate, report_errors=False)
                        if animation:
                            virtual_path = candidate
                            break
                    except Exception:
                        continue
            if not virtual_path:
                print(
                    f"[FF7R Cutscene] Animation unavailable or unsupported: "
                    f"'{animation_name}'."
                )
                continue

            existing_action = _existing_package_animation(virtual_path)
            skeleton_path = (
                (animation or {}).get("skeletonPath")
                or (existing_action.get("ff7r_skeleton_asset_path") if existing_action else "")
            )
            if not isinstance(skeleton_path, str) or not skeleton_path:
                print(f"[FF7R Cutscene] Animation '{animation_name}' has no Skeleton source.")
                continue
            actor_id = _cutscene_actor_id_for_animation(animation_name, actor_ids)
            armature_obj = _find_cutscene_armature(context.scene, actor_id, skeleton_path)
            if armature_obj is None:
                try:
                    armature_obj = _create_cutscene_skeletal_actor(
                        context, session, skeleton_path, actor_id, scale_factor
                    )
                    loaded_rigs += 1
                except Exception as exc:
                    print(
                        f"[FF7R Cutscene] Character rig for '{animation_name}' "
                        f"could not be loaded: {exc}"
                    )
                    continue
            # Prop/environment clips flagged bPoseAnimation use a bone codec the
            # bridge cannot decode yet.  The actor is still worth having at its
            # bind pose -- a static pillow beats a missing one -- so only the
            # animation is skipped, not the rig built above.
            if animation is not None and animation.get("undecodable") and not animation.get("tracks"):
                print(
                    f"[FF7R Cutscene] '{animation_name}' has no decodable animation "
                    f"({'pose animation' if animation.get('poseAnimation') else 'unknown codec'}); "
                    f"actor imported at bind pose."
                )
                continue

            if existing_action is None:
                try:
                    if animation is None:
                        animation = session.animation_asset(virtual_path)
                    animations.import_animation_asset(
                        armature_obj,
                        virtual_path,
                        animation,
                        replace_current_action=False,
                        scene=context.scene,
                    )
                    loaded_actions += 1
                except Exception as exc:
                    print(
                        f"[FF7R Cutscene] Animation '{animation_name}' "
                        f"could not be loaded: {exc}"
                    )
        window_manager.progress_update(len(animation_names))
    finally:
        window_manager.progress_end()
        if workspace is not None:
            workspace.status_text_set(None)
    return loaded_rigs, loaded_actions


def _ensure_scene_collection(scene, name: str) -> bpy.types.Collection:
    """Get or create *name* as a direct child of the scene's master collection."""
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if scene.collection.children.get(collection.name) is None:
        scene.collection.children.link(collection)
    return collection


def _layer_collection_for(layer_collection, collection):
    """Depth-first search for the LayerCollection wrapping *collection*."""
    if layer_collection.collection is collection:
        return layer_collection
    for child in layer_collection.children:
        found = _layer_collection_for(child, collection)
        if found is not None:
            return found
    return None


@contextmanager
def _active_collection(context, collection):
    """Temporarily make *collection* the active one.

    Most of this add-on's object creation links into ``context.collection``
    (the armature builder, the mesh importer, socket empties, the UMAP actor
    paths), so pointing the active collection at the cutscene's own collection
    is what routes all of it there without threading a parameter through every
    call site.
    """
    view_layer = context.view_layer
    target = _layer_collection_for(view_layer.layer_collection, collection)
    previous = view_layer.active_layer_collection
    if target is not None:
        view_layer.active_layer_collection = target
    try:
        yield
    finally:
        try:
            view_layer.active_layer_collection = previous
        except Exception:
            pass


def _adopt_new_scene_collections(scene, collection, known: set) -> int:
    """Move top-level collections created during an import under *collection*.

    ``json/map_import.py`` links a collection per source UMAP straight into the
    scene's master collection, so a cutscene's temporary levels would otherwise
    sit outside the cutscene's own collection.
    """
    moved = 0
    for child in list(scene.collection.children):
        if child is collection or child.name in known:
            continue
        if collection.children.get(child.name) is None:
            collection.children.link(child)
        scene.collection.children.unlink(child)
        moved += 1
    return moved


class FF7R_REBIRTH_OT_import_cutscene_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_cutscene_game_packages"
    bl_label = "Cutscene from Rebirth Packages"
    bl_description = "Import an EndCinemaSequence directly from mounted Rebirth packages"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Cutscene Path",
        description="Selected package Camera sequence",
    )
    cutscene_search_text: bpy.props.StringProperty(
        name="Search",
        description="Space-separated terms may occur anywhere in the cutscene path",
        options={'SKIP_SAVE'},
        update=_cutscene_search_filter_changed,
    )
    cutscene_search_results: bpy.props.CollectionProperty(
        type=FF7R_PG_cutscene_search_entry, options={'HIDDEN', 'SKIP_SAVE'}
    )
    cutscene_search_result_index: bpy.props.IntProperty(
        default=-1,
        options={'HIDDEN', 'SKIP_SAVE'},
        update=_cutscene_search_selection_changed,
    )
    import_lights: bpy.props.BoolProperty(name="Import Lights", default=True)
    always_cast_shadows: bpy.props.BoolProperty(
        name="Always Cast Shadows",
        description="Force imported point and spot lights to cast shadows",
        default=False,
    )
    import_cameras: bpy.props.BoolProperty(name="Import Cameras", default=True)
    import_characters: bpy.props.BoolProperty(name="Import Characters", default=True)

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        try:
            refresh_cutscene_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            self.report({'ERROR'}, f"Package cutscene index failed: {exc}")
            return {'CANCELLED'}
        self.cutscene_search_text = ""
        _populate_cutscene_search(self)
        return context.window_manager.invoke_props_dialog(self, width=750)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "cutscene_search_text", icon='VIEWZOOM')
        layout.template_list(
            FF7R_UL_cutscene_search_results.__name__, "cutscene_search",
            self, "cutscene_search_results", self, "cutscene_search_result_index", rows=9,
        )
        layout.prop(self, "import_characters")
        layout.prop(self, "import_cameras")
        layout.prop(self, "import_lights")
        layout.prop(self, "always_cast_shadows")
        layout.label(
            text=f"{len(_VIRTUAL_CUTSCENES):,} Camera sequence packages indexed",
            icon='INFO',
        )

    def execute(self, context):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        root = self.virtual_path.strip().replace("\\", "/").lstrip("/")
        if root.lower().endswith(".uasset"):
            root = root[:-7]
        if root.casefold().endswith("_camera"):
            root = root[:-7]
        if not root:
            self.report({'ERROR'}, "Enter a cutscene root or _Camera package path.")
            return {'CANCELLED'}
        sequence_paths = {
            "camera": root + "_Camera.uasset",
            "character": root + "_Character.uasset",
            "light": root + "_Light.uasset",
            "constraint": root + "_Constraint.uasset",
        }
        cutscene_name = Path(root).name
        scene = context.scene
        cutscene_collection = _ensure_scene_collection(scene, cutscene_name)
        known_collections = {child.name for child in scene.collection.children}
        try:
            from ....formats.ue_map import cutscene_import
            game_root = bpy.path.abspath(prefs.rebirth_install_root)
            oodle_dll = bpy.path.abspath(prefs.rebirth_oodle_dll)
            usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
            with PackageAssetSession(game_root, oodle_dll, usmap_path) as session,                     _active_collection(context, cutscene_collection):
                decoded = {}
                requested_kinds = set()
                if self.import_cameras or self.import_characters:
                    # Character strip placement uses camera cuts even when camera
                    # objects themselves are not requested.
                    requested_kinds.add("camera")
                if self.import_characters:
                    requested_kinds.add("character")
                    requested_kinds.add("constraint")
                if self.import_lights:
                    requested_kinds.add("light")
                if not requested_kinds:
                    raise ValueError("Select at least one cutscene import type.")

                for kind in ("camera", "character", "light", "constraint"):
                    if kind not in requested_kinds:
                        continue
                    path = sequence_paths[kind]
                    try:
                        package_data = session.cutscene_asset(path)
                        decoded[kind] = package_data.get("exports") or []
                        if kind == "constraint":
                            decoded["attachment_events"] = package_data.get("attachmentEvents") or []
                    except Exception as exc:
                        if kind == "camera":
                            raise
                        print(f"[FF7R Cutscene] {kind} sequence unavailable: {exc}")

                # Possessable characters live in the cut's temporary level.
                # Import it first so its package SkeletalMesh actors are present
                # under the same CutsceneID names used by BindingReferences.
                if self.import_characters and decoded.get("character"):
                    temp_paths = set()
                    for entry in decoded["character"]:
                        if entry.get("Type") != "EndCinemaSequence":
                            continue
                        refs = entry.get("Properties", {}).get("BindingReferences", {}).get("BindingIdToReferences", [])
                        for ref in refs:
                            asset_path = (ref.get("Value", {}).get("References", [{}])[0]
                                          .get("ExternalObjectPath", {}).get("AssetPathName", ""))
                            temp_path = _game_asset_path_to_virtual_umap(asset_path)
                            if temp_path:
                                temp_paths.add(temp_path)
                    static_resolver = PackageStaticMeshResolver(context, session, prefs.map_scale_factor)
                    skeletal_resolver = PackageSkeletalMeshResolver(context, session, prefs.map_scale_factor)
                    for temp_path in sorted(temp_paths):
                        try:
                            actors = session.umap_actors(temp_path).get("actors") or []
                            map_import.import_map_entries(
                                actors, temp_path, 1.0, 1.0,
                                location_scale=prefs.map_scale_factor,
                                always_cast_shadows=self.always_cast_shadows,
                                static_mesh_resolver=static_resolver,
                                skeletal_mesh_resolver=skeletal_resolver,
                            )
                        except Exception as exc:
                            # Some cutscene bindings point at runtime-only temporary
                            # levels that have no separately mounted UMAP package.
                            # Their model and animation packages are still available.
                            print(f"[FF7R Cutscene] Temporary level unavailable '{temp_path}': {exc}")
                    loaded_rigs, loaded_actions = _load_cutscene_character_assets(
                        context,
                        session,
                        root,
                        decoded.get("character"),
                        Path(root).name,
                        prefs.map_scale_factor,
                    )
                    if loaded_rigs or loaded_actions:
                        print(
                            f"[FF7R Cutscene] Loaded {loaded_rigs} character rig(s) and "
                            f"{loaded_actions} required animation(s)."
                        )
                    # Props are bound like actors but carry no animation, so the
                    # rig loader above never sees them.
                    _static_meshes, _skeletal_meshes = refresh_mesh_indices(
                        game_root, oodle_dll, usmap_path)
                    loaded_props = _load_cutscene_prop_assets(
                        context, session, decoded.get("character"), cutscene_name,
                        prefs.map_scale_factor, _skeletal_meshes, _static_meshes,
                    )
                    if loaded_props:
                        print(f"[FF7R Cutscene] Loaded {loaded_props} prop(s).")
                cutscene_import.import_ue_cutscene_data(
                    decoded.get("camera"), decoded.get("character"), decoded.get("light"),
                    cutscene_name,
                    import_lights=self.import_lights,
                    always_cast_shadows=self.always_cast_shadows,
                    import_cameras=self.import_cameras,
                    import_characters=self.import_characters,
                    target_collection=cutscene_collection,
                )
                if self.import_characters:
                    attached_props = _apply_cutscene_prop_attachment_events(
                        context, decoded.get("attachment_events"))
                    if attached_props:
                        print(f"[FF7R Cutscene] Applied {attached_props} timed prop attachment(s).")
        except Exception as exc:
            print(f"[FF7R Cutscene] Import failed for '{root}':")
            traceback.print_exc()
            self.report({'ERROR'}, f"Package cutscene import failed: {exc}")
            return {'CANCELLED'}
        adopted = _adopt_new_scene_collections(scene, cutscene_collection, known_collections)
        object_count = len(cutscene_collection.all_objects)
        self.report(
            {'INFO'},
            f"Imported package cutscene '{cutscene_name}' into collection "
            f"'{cutscene_collection.name}' ({object_count} object(s)"
            + (f", {adopted} level collection(s)" if adopted else "") + ").",
        )
        return {'FINISHED'}


class FF7R_REBIRTH_OT_import_static_mesh_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_static_mesh_game_packages"
    bl_label = "Static Mesh from Rebirth Packages"
    bl_description = "Import a Rebirth StaticMesh directly from its mounted virtual package path"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Static Mesh Path",
        description="Mounted Unreal virtual path to an indexed StaticMesh .uasset",
        default=DEFAULT_STATIC_MESH_PATH,
    )
    mesh_search_kind: bpy.props.StringProperty(
        default="STATIC", options={'HIDDEN', 'SKIP_SAVE'}
    )
    mesh_search_text: bpy.props.StringProperty(
        name="Search",
        description="Filter indexed StaticMesh paths while preserving numeric order",
        options={'SKIP_SAVE'},
        update=_mesh_search_filter_changed,
    )
    mesh_search_results: bpy.props.CollectionProperty(
        type=FF7R_PG_mesh_search_entry, options={'HIDDEN', 'SKIP_SAVE'}
    )
    mesh_search_result_index: bpy.props.IntProperty(
        default=-1,
        options={'HIDDEN', 'SKIP_SAVE'},
        update=_mesh_search_selection_changed,
    )
    scale_factor: bpy.props.FloatProperty(
        name="Scale",
        description="Convert Unreal centimeters to Blender units",
        default=0.01,
        min=0.0001,
        max=100.0,
    )
    offset_opposite_faces: bpy.props.EnumProperty(
        name="Offset Faces",
        description="Choose how overlapping opposite-facing faces are handled",
        items=OFFSET_FACES_ITEMS,
        default=OFFSET_FACES_BAKED,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward",
        description="Choose the imported mesh's forward axis",
        items=FACE_FORWARD_ITEMS,
        default=FACE_FORWARD_UNREAL,
    )

    _persisted_props = ("scale_factor", "offset_opposite_faces", "face_y_forward")

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        self.offset_opposite_faces = (
            OFFSET_FACES_BAKED if prefs.offset_mec_opposite_faces else OFFSET_FACES_NONE
        )
        try:
            refresh_mesh_indices(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            self.report({'ERROR'}, f"Package mesh index failed: {exc}")
            return {'CANCELLED'}
        self._load_last_import_settings(context)
        package_browser.activate(context, _STATIC_MESH_BROWSER, _VIRTUAL_STATIC_MESHES)
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, _STATIC_MESH_BROWSER)
        layout.prop(self, "scale_factor")
        layout.prop(self, "offset_opposite_faces")
        layout.prop(self, "face_y_forward")
        layout.label(
            text=f"{len(_VIRTUAL_STATIC_MESHES):,} StaticMesh assets indexed ({_MESH_CACHE_SOURCE or 'memory'})",
            icon='PACKAGE',
        )
        layout.label(text="Supports updated flattened meshes and earlier conventional layouts.")

    def execute(self, context):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        try:
            game_root = bpy.path.abspath(prefs.rebirth_install_root)
            oodle_dll = bpy.path.abspath(prefs.rebirth_oodle_dll)
            usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
            static_meshes, _skeletal_meshes = refresh_mesh_indices(game_root, oodle_dll, usmap_path)
            _STATIC_MESH_BROWSER["paths"] = list(static_meshes)
            virtual_paths = package_browser.resolve_paths(
                context, _STATIC_MESH_BROWSER, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError("Select at least one StaticMesh in the package browser.")
            vertex_count = triangle_count = material_count = 0
            with PackageAssetSession(game_root, oodle_dll, usmap_path) as session:
                for virtual_path in virtual_paths:
                    static_mesh = session.static_mesh(virtual_path)
                    obj = import_static_mesh_asset(
                        context,
                        static_mesh,
                        virtual_path,
                        scale_factor=self.scale_factor,
                        offset_opposite_faces=self.offset_opposite_faces,
                        material_session=session,
                        face_y_forward=_face_y_forward_enabled(self.face_y_forward),
                    )
                    vertex_count += len(obj.data.vertices)
                    triangle_count += len(obj.data.polygons)
                    material_count += len(obj.data.materials)
        except Exception as exc:
            self.report({'ERROR'}, f"Package StaticMesh import failed: {exc}")
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        self.report(
            {'INFO'},
            f"Imported {len(virtual_paths):,} Rebirth StaticMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{material_count:,} material slots",
        )
        return {'FINISHED'}


class FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_skeletal_mesh_game_packages"
    bl_label = "Skeletal Mesh from Rebirth Packages"
    bl_description = "Import a Rebirth SkeletalMesh and bind it to the selected armature"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Skeletal Mesh Path",
        description="Mounted Unreal virtual path to an indexed SkeletalMesh .uasset",
        default="",
    )
    mesh_search_kind: bpy.props.StringProperty(
        default="SKELETAL", options={'HIDDEN', 'SKIP_SAVE'}
    )
    mesh_search_text: bpy.props.StringProperty(
        name="Search",
        description="Filter indexed SkeletalMesh paths while preserving numeric order",
        options={'SKIP_SAVE'},
        update=_mesh_search_filter_changed,
    )
    mesh_search_results: bpy.props.CollectionProperty(
        type=FF7R_PG_mesh_search_entry, options={'HIDDEN', 'SKIP_SAVE'}
    )
    mesh_search_result_index: bpy.props.IntProperty(
        default=-1,
        options={'HIDDEN', 'SKIP_SAVE'},
        update=_mesh_search_selection_changed,
    )
    scale_factor: bpy.props.FloatProperty(
        name="Scale",
        description="Convert Unreal centimeters to Blender units",
        default=0.01,
        min=0.0001,
        max=100.0,
    )
    offset_opposite_faces: bpy.props.EnumProperty(
        name="Offset Faces",
        description="Choose how overlapping opposite-facing faces are handled",
        items=OFFSET_FACES_ITEMS,
        default=OFFSET_FACES_BAKED,
    )
    bind_active_armature: bpy.props.BoolProperty(
        name="Bind Active Armature",
        description="Add matching vertex groups and an Armature modifier for the active armature",
        default=True,
    )
    build_skeleton: bpy.props.BoolProperty(
        name="Build Skeleton from Package",
        description=(
            "Ignore Bind Active Armature and build a new armature from this mesh's "
            "associated Skeleton asset before importing, exactly as the Skeleton "
            "importer would"
        ),
        default=True,
    )
    attachment_sockets: bpy.props.EnumProperty(
        name="Attachment Sockets",
        description="Choose how attachment sockets are materialized on the generated armature",
        items=ATTACHMENT_SOCKETS_ITEMS,
        default=ATTACHMENT_SOCKETS_EMPTIES,
    )
    import_kdi: bpy.props.BoolProperty(
        name="Also import KDI",
        description="After building the skeleton, also import its KineDriver rig (and any secondary passes)",
        default=True,
    )
    setup_naive_ik: bpy.props.BoolProperty(
        name="Setup IK (naive)",
        description=(
            "Add a chain-length-3 IK constraint (no target) to R_Foot_a/L_Foot_a/"
            "R_Hand_a/L_Hand_a, and lock Y/Z rotation to 0 on R_Foreleg_a/L_Foreleg_a/"
            "R_Forearm_a/L_Forearm_a so they only bend as a hinge. Bones not present "
            "on this skeleton are skipped"
        ),
        default=False,
    )
    create_limbal_bone: bpy.props.BoolProperty(
        name="Create C_Limbal eye controller",
        description=(
            "When L_Eye or R_Eye exists, create a centered non-deforming controller "
            "one foot in front of the character and use it for imported eye materials"
        ),
        default=False,
    )
    create_variant_bone_collections: bpy.props.BoolProperty(
        name="Create variant bone collections",
        description=(
            "For player skeletons, scan meshes sharing this skeleton and create a "
            "collection named after each variant that has uniquely weighted bones"
        ),
        default=True,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward",
        description="Choose the imported mesh and armature's forward axis",
        items=FACE_FORWARD_ITEMS,
        default=FACE_FORWARD_UNREAL,
    )

    _persisted_props = (
        "scale_factor",
        "offset_opposite_faces",
        "bind_active_armature",
        "build_skeleton",
        "attachment_sockets",
        "import_kdi",
        "setup_naive_ik",
        "create_limbal_bone",
        "create_variant_bone_collections",
        "face_y_forward",
    )

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        self.offset_opposite_faces = (
            OFFSET_FACES_BAKED if prefs.offset_mec_opposite_faces else OFFSET_FACES_NONE
        )
        try:
            refresh_mesh_indices(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            self.report({'ERROR'}, f"Package mesh index failed: {exc}")
            return {'CANCELLED'}
        self._load_last_import_settings(context)
        package_browser.activate(
            context, _SKELETAL_MESH_BROWSER, _VIRTUAL_SKELETAL_MESHES
        )
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, _SKELETAL_MESH_BROWSER)
        layout.prop(self, "scale_factor")
        layout.prop(self, "offset_opposite_faces")
        bind_row = layout.row()
        bind_row.enabled = not self.build_skeleton
        bind_row.prop(self, "bind_active_armature")
        layout.prop(self, "build_skeleton")
        socket_row = layout.row()
        socket_row.enabled = self.build_skeleton
        socket_row.prop(self, "attachment_sockets")
        kdi_row = layout.row()
        kdi_row.enabled = self.build_skeleton
        kdi_row.prop(self, "import_kdi")
        ik_row = layout.row()
        ik_row.enabled = self.build_skeleton
        ik_row.prop(self, "setup_naive_ik")
        limbal_row = layout.row()
        limbal_row.enabled = self.build_skeleton
        limbal_row.prop(self, "create_limbal_bone")
        variant_row = layout.row()
        variant_row.enabled = self.build_skeleton
        variant_row.prop(self, "create_variant_bone_collections")
        layout.prop(self, "face_y_forward")
        layout.label(
            text=f"{len(_VIRTUAL_SKELETAL_MESHES):,} SkeletalMesh assets indexed ({_MESH_CACHE_SOURCE or 'memory'})",
            icon='PACKAGE',
        )
        layout.label(text="Imports Coordinate0–Coordinate3, per-vertex bone weights, "
                          "and RMI_Surface materials.")

    def execute(self, context):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        binding_armature = (
            context.active_object
            if self.bind_active_armature and not self.build_skeleton
            else None
        )
        if self.bind_active_armature and not self.build_skeleton and (
            binding_armature is None or binding_armature.type != 'ARMATURE'
        ):
            self.report({'ERROR'}, "Select the matching armature before importing, or disable Bind Active Armature.")
            return {'CANCELLED'}
        try:
            game_root = bpy.path.abspath(prefs.rebirth_install_root)
            oodle_dll = bpy.path.abspath(prefs.rebirth_oodle_dll)
            usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
            _static_meshes, skeletal_meshes = refresh_mesh_indices(game_root, oodle_dll, usmap_path)
            _SKELETAL_MESH_BROWSER["paths"] = list(skeletal_meshes)
            virtual_paths = package_browser.resolve_paths(
                context, _SKELETAL_MESH_BROWSER, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError("Select at least one SkeletalMesh in the package browser.")
            vertex_count = triangle_count = weighted_count = influence_total = 0
            material_count = bound_count = 0
            # The import has to happen INSIDE the session: building RMI
            # materials reads the material instance and streams its textures
            # back over the same bridge process, so closing the session first
            # (as this operator used to) leaves nothing to load them with.
            with PackageAssetSession(game_root, oodle_dll, usmap_path) as session:
                for virtual_path in virtual_paths:
                    armature_obj = binding_armature
                    skeletal_mesh = session.skeletal_mesh(virtual_path)
                    if self.build_skeleton:
                        skeleton_path = skeletal_mesh.get("skeletonPath")
                        if not skeleton_path:
                            raise ValueError(
                                f"'{virtual_path}' has no associated Skeleton asset."
                            )
                        mesh_kdi_paths = _skeletal_mesh_kdi_paths(skeletal_mesh)
                        kdi_override = mesh_kdi_paths[0] if mesh_kdi_paths else ""
                        result = bpy.ops.import_scene.ff7r_rebirth_skeleton_game_packages(
                            virtual_path=skeleton_path,
                            scale_factor=self.scale_factor,
                            import_kdi=self.import_kdi,
                            kdi_virtual_path_override=kdi_override,
                            attachment_sockets=self.attachment_sockets,
                            setup_naive_ik=self.setup_naive_ik,
                            create_limbal_bone=self.create_limbal_bone,
                            create_variant_bone_collections=self.create_variant_bone_collections,
                            face_y_forward=self.face_y_forward,
                        )
                        if result != {'FINISHED'}:
                            raise RuntimeError(
                                f"Building the associated Skeleton for '{virtual_path}' failed."
                            )
                        armature_obj = context.view_layer.objects.active
                        if armature_obj is None or armature_obj.type != 'ARMATURE':
                            raise RuntimeError("Could not identify the built armature.")
                    obj, weighted_vertices, influence_count = import_skeletal_mesh_asset(
                        context,
                        skeletal_mesh,
                        virtual_path,
                        armature_obj=armature_obj,
                        scale_factor=self.scale_factor,
                        offset_opposite_faces=self.offset_opposite_faces,
                        material_session=session,
                        face_y_forward=_face_y_forward_enabled(self.face_y_forward),
                    )
                    vertex_count += len(obj.data.vertices)
                    triangle_count += len(obj.data.polygons)
                    weighted_count += weighted_vertices
                    influence_total += influence_count
                    material_count += len(obj.data.materials)
                    bound_count += int(armature_obj is not None)
        except Exception as exc:
            self.report({'ERROR'}, f"Package SkeletalMesh import failed: {exc}")
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        self.report(
            {'INFO'},
            f"Imported {len(virtual_paths):,} Rebirth SkeletalMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{weighted_count:,} weighted vertices, {influence_total:,} influences, "
            f"{material_count:,} material slots, {bound_count:,} bound",
        )
        return {'FINISHED'}


class FF7R_REBIRTH_OT_import_nearby_mec_terrain(FF7R_LoggedOperator):
    """Bring in only the coarse MEC culling groups near one Blender position."""

    bl_idname = "import_scene.ff7r_rebirth_nearby_mec_terrain"
    bl_label = "Experimental Nearby MEC Terrain"
    bl_description = (
        "Import untextured lowest-detail Massive Environment terrain near a Blender location"
    )
    bl_options = {'REGISTER', 'UNDO'}

    continent: bpy.props.EnumProperty(
        name="Continent",
        description="The continent whose streaming volumes are queried",
        items=tuple(
            (key, config["label"], f"Use {config['label']} world origin")
            for key, config in MEC_CONTINENTS.items()
        ),
        default="WEST",
    )
    location: bpy.props.FloatVectorProperty(
        name="Continent-local Blender location",
        description=(
            "Blender position within the selected continent around which to load terrain"
        ),
        size=3,
        subtype='TRANSLATION',
        default=(0.0, 0.0, 0.0),
    )
    place_in_world_space: bpy.props.BoolProperty(
        name="Place at continent world origin",
        description=(
            "Add the selected continent's MassiveEnvironmentOrigin when placing terrain"
        ),
        default=False,
    )
    view_distance: bpy.props.FloatProperty(
        name="View distance",
        description=(
            "Blender-space radius used to select the game's EndStreamingVolume brushes"
        ),
        default=MEC_NEARBY_DEFAULT_VIEW_DISTANCE,
        min=1.0,
        soft_max=2000.0,
        subtype='DISTANCE',
    )

    _persisted_props = (
        "continent", "location", "place_in_world_space", "view_distance"
    )

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        self._load_last_import_settings(context)
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "continent")
        layout.prop(self, "location")
        layout.prop(self, "place_in_world_space")
        layout.prop(self, "view_distance")
        prefs = _preferences(context)
        scale = prefs.map_scale_factor if prefs else 0.01
        origin = _continent_origin_in_blender(self.continent, scale)
        box = layout.box()
        box.label(text="Coordinates are local to the selected continent.", icon='INFO')
        placement = (
            f"World origin applied: ({origin[0]:.2f}, {origin[1]:.2f}, {origin[2]:.2f})"
            if self.place_in_world_space else
            "Terrain will be placed at continent-local coordinates."
        )
        box.label(text=placement)
        box.label(text="Uses the game's streaming volumes, then imports coarsest LoD without textures.")

    def execute(self, context):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}

        game_root = bpy.path.abspath(prefs.rebirth_install_root)
        oodle_dll = bpy.path.abspath(prefs.rebirth_oodle_dll)
        usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
        scale_factor = float(prefs.map_scale_factor)
        target_location = tuple(float(value) for value in self.location)
        view_distance = float(self.view_distance)
        continent_world_offset = _continent_origin_in_blender(
            self.continent, scale_factor
        )
        placement_offset = (
            continent_world_offset if self.place_in_world_space else (0.0, 0.0, 0.0)
        )
        # Root-map EndStreamingVolume brushes are expressed in their
        # continent-local UE coordinates.  The user enters that same local
        # Blender coordinate; MassiveEnvironmentOrigin is only added when the
        # selected MEC geometry is placed in the Blender world below.
        location_ue = (
            target_location[0] / scale_factor,
            -target_location[1] / scale_factor,
            target_location[2] / scale_factor,
        )
        root_streaming_map = _continent_root_streaming_map(self.continent)

        continent_label = MEC_CONTINENTS[self.continent]["label"]
        nearby_collection = bpy.data.collections.new(
            f"MEC Nearby - {continent_label}"
        )
        context.scene.collection.children.link(nearby_collection)
        nearby_collection["ff7r_mec_nearby_continent"] = self.continent
        nearby_collection["ff7r_mec_nearby_location"] = target_location
        nearby_collection["ff7r_mec_nearby_view_distance"] = view_distance
        nearby_collection["ff7r_mec_place_in_world_space"] = self.place_in_world_space
        nearby_collection["ff7r_mec_continent_world_offset"] = continent_world_offset
        nearby_collection["ff7r_mec_world_offset"] = placement_offset

        maps_with_geometry = 0
        failures: list[tuple[str, str]] = []
        window_manager = context.window_manager
        try:
            with tempfile.TemporaryDirectory(prefix="ff7r_nearby_mec_") as temp_dir:
                candidate_roots = _continent_streaming_root_candidates(
                    refresh_umap_index(game_root, oodle_dll, usmap_path),
                    self.continent,
                )
                with PackageAssetSession(game_root, oodle_dll, usmap_path) as package_session:
                    selected_paths: dict[str, str] = {}
                    selected_roots: list[str] = []
                    probe_failures: list[tuple[str, str]] = []
                    for root_index, candidate_root in enumerate(candidate_roots, 1):
                        try:
                            streaming_probe = package_session.streaming_probe(candidate_root)
                            paths = _nearby_streaming_level_paths(
                                streaming_probe,
                                location_ue,
                                view_distance / scale_factor,
                            )
                            if paths:
                                selected_roots.append(candidate_root)
                            for virtual_path in paths:
                                selected_paths.setdefault(
                                    virtual_path.casefold(), virtual_path
                                )
                        except Exception as exc:
                            probe_failures.append((candidate_root, str(exc)))
                            print(
                                "Nearby MEC streaming probe failed: "
                                f"{candidate_root}: {exc}"
                            )
                        finally:
                            # Probing map roots is far cheaper than decoding
                            # MEC packages, but a full continent can still
                            # visit many maps. Periodically trim the bridge's
                            # package cache before starting actual imports.
                            if root_index % 8 == 0:
                                package_session.release_batch_memory()

                    virtual_paths = sorted(selected_paths.values(), key=_natural_path_key)
                    if not virtual_paths:
                        raise RuntimeError(
                            "The selected point does not intersect a usable streaming volume "
                            "in this continent's map roots."
                        )
                    nearby_collection["ff7r_mec_streaming_root"] = root_streaming_map
                    nearby_collection["ff7r_mec_streaming_roots"] = selected_roots
                    nearby_collection["ff7r_mec_streaming_root_count"] = len(candidate_roots)
                    nearby_collection["ff7r_mec_streaming_probe_failures"] = len(probe_failures)
                    nearby_collection["ff7r_mec_streaming_location_ue"] = location_ue
                    package_session.release_batch_memory()
                    window_manager.progress_begin(0, max(1, len(virtual_paths)))
                    for index, virtual_path in enumerate(virtual_paths, 1):
                        window_manager.progress_update(index - 1)
                        try:
                            map_temp_dir = os.path.join(temp_dir, f"{index:04d}")
                            os.makedirs(map_temp_dir, exist_ok=True)
                            local_umap = os.path.join(
                                map_temp_dir, os.path.basename(virtual_path)
                            )
                            package_session.extract_raw(virtual_path, local_umap)
                            try:
                                package_session.extract_raw(
                                    os.path.splitext(virtual_path)[0] + ".ubulk",
                                    os.path.splitext(local_umap)[0] + ".ubulk",
                                    report_errors=False,
                                )
                            except Exception:
                                pass

                            previous_children = len(nearby_collection.children)
                            normalized_local = os.path.normcase(os.path.realpath(local_umap))
                            import_umap_paths(
                                context,
                                [local_umap],
                                lod_mode="QUALITY",
                                lod_quality=0.0,
                                import_originals=False,
                                offset_opposite_faces=False,
                                import_sway=False,
                                scale_factor=scale_factor,
                                tex_root="",
                                tex_match_by_filename=False,
                                import_names_by_path={normalized_local: []},
                                world_offset=placement_offset,
                                untextured=True,
                                parent_collection=nearby_collection,
                                collection_prefix=f"{nearby_collection.name} :: ",
                            )
                            if len(nearby_collection.children) > previous_children:
                                maps_with_geometry += 1
                        except Exception as exc:
                            failures.append((virtual_path, str(exc)))
                            print(f"Nearby MEC map failed: {virtual_path}: {exc}")
                        finally:
                            try:
                                package_session.release_batch_memory()
                            except Exception as exc:
                                print(f"Nearby MEC bridge cleanup failed: {exc}")
                        window_manager.progress_update(index)
        except Exception as exc:
            if not nearby_collection.children:
                bpy.data.collections.remove(nearby_collection)
            self.report({'ERROR'}, f"Nearby MEC terrain import failed: {exc}")
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()

        if not nearby_collection.children:
            bpy.data.collections.remove(nearby_collection)
            detail = f" First failure: {failures[0][1]}" if failures else ""
            self.report(
                {'WARNING'},
                "The selected streaming levels contained no Massive Environment terrain." + detail,
            )
            return {'CANCELLED'}

        self._save_last_import_settings(context)
        message = (
            f"Imported nearby untextured lowest-LoD MEC terrain from {maps_with_geometry} map(s)"
        )
        if failures:
            message += f"; {len(failures)} package(s) could not be scanned"
        self.report({'INFO'}, message)
        return {'FINISHED'}


class FF7R_REBIRTH_OT_import_mec_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_mec_game_packages"
    bl_label = "UMAP from Rebirth Packages"
    bl_description = "Browse UMAPs inside Rebirth's mounted package files and import geometry, actors, and lights"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Package UMAP",
        description="Single Unreal virtual path for scripted/non-interactive imports",
        options={'HIDDEN'},
    )
    import_originals: bpy.props.BoolProperty(name="Import originals at origin", default=False)
    offset_opposite_faces: bpy.props.BoolProperty(name="Offset opposite overlapping faces", default=True)
    import_sway: bpy.props.BoolProperty(name="Import wind sway as shape keys", default=True)
    import_textures: bpy.props.BoolProperty(
        name="Import and pack DDS textures",
        description="Read original DDS texture data from the game packages and pack it into the Blend file",
        default=True,
    )
    import_models: bpy.props.BoolProperty(
        name="Import Models",
        description=(
            "Create StaticMesh and SkeletalMesh UMAP actors directly from the "
            "mounted game packages. Repeated actors "
            "share one Blender datablock and missing game assets are reported. "
            "Skeletal actors import in bind pose; no in-level animation/pose "
            "data is available from the package."
        ),
        default=True,
    )
    import_lights: bpy.props.BoolProperty(
        name="Import Lights",
        description="Create point and spot lights from the UMAP actor data",
        default=True,
    )
    always_cast_shadows: bpy.props.BoolProperty(
        name="Always Cast Shadows",
        description="Force imported point and spot lights to cast shadows, overriding their Unreal CastShadows setting",
        default=False,
    )
    recursive_import: bpy.props.BoolProperty(
        name="Recursively import streaming levels",
        description="Also import UMAPs referenced by Level Streaming actors",
        default=False,
    )
    lod_mode: bpy.props.EnumProperty(
        name="LoD level",
        items=(
            ("QUALITY", "Quality", "Select LoD by normalized quality"),
            ("LEVEL", "Level", "Select an explicit LoD level"),
            ("ALL", "All LoDs", "Import every available LoD"),
        ),
        default="QUALITY",
    )
    lod_quality: bpy.props.FloatProperty(name="Quality", default=1.0, min=0.0, max=1.0, subtype='FACTOR')
    lod_level: bpy.props.IntProperty(name="Level", default=0, min=-13, max=0)
    scale_factor: bpy.props.FloatProperty(name="Scale", default=0.01, min=0.0001, max=100.0)

    _persisted_props = (
        "import_originals",
        "offset_opposite_faces",
        "import_sway",
        "import_textures",
        "import_models",
        "import_lights",
        "always_cast_shadows",
        "recursive_import",
        "lod_mode",
        "lod_quality",
        "lod_level",
        "scale_factor",
    )

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        self.offset_opposite_faces = prefs.offset_mec_opposite_faces
        self.scale_factor = prefs.map_scale_factor
        self._load_last_import_settings(context)
        try:
            paths = refresh_umap_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not paths:
            self.report({'WARNING'}, "No UMAP files were found in the mounted game packages.")
            return {'CANCELLED'}
        _SELECTED_UMAPS.clear()
        state = _browser_state(context)
        state.current_directory = _LAST_UMAP_BROWSER_DIRECTORY
        state.filter_text = ""
        _populate_browser(context)
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        state = _browser_state(context)
        header = layout.row(align=True)
        header.label(
            text=f"{len(_VIRTUAL_UMAPS):,} UMAPs available — {len(_SELECTED_UMAPS):,} selected",
            icon='PACKAGE',
        )
        header.operator(FF7R_REBIRTH_OT_package_browser_up.bl_idname, text="", icon='FILE_PARENT')
        header.label(text=state.current_directory)
        layout.prop(state, "filter_text", text="", icon='VIEWZOOM')
        layout.template_list(
            FF7R_UL_package_umaps.__name__,
            "",
            state,
            "entries",
            state,
            "active_index",
            rows=12,
        )
        selection = layout.row(align=True)
        selection.operator(
            FF7R_REBIRTH_OT_package_browser_select.bl_idname,
            text="Select Visible",
        ).mode = 'SELECT'
        selection.operator(
            FF7R_REBIRTH_OT_package_browser_select.bl_idname,
            text="Invert Visible",
        ).mode = 'INVERT'
        selection.operator(
            FF7R_REBIRTH_OT_package_browser_select.bl_idname,
            text="Clear All",
        ).mode = 'CLEAR'
        layout.separator()
        layout.prop(self, "import_originals")
        layout.prop(self, "offset_opposite_faces")
        layout.prop(self, "import_sway")
        layout.prop(self, "import_textures")
        layout.prop(self, "import_models")
        layout.prop(self, "import_lights")
        shadows_row = layout.row()
        shadows_row.enabled = self.import_lights
        shadows_row.prop(self, "always_cast_shadows")
        layout.prop(self, "recursive_import")
        layout.prop(self, "lod_mode", expand=True)
        if self.lod_mode == "QUALITY":
            layout.prop(self, "lod_quality", slider=True)
        elif self.lod_mode == "LEVEL":
            layout.prop(self, "lod_level", slider=True)
        layout.prop(self, "scale_factor")
        box = layout.box()
        box.label(text="Package paths are configured in Add-on Preferences.", icon='INFO')

    def execute(self, context):
        prefs = _preferences(context)
        game_root = bpy.path.abspath(prefs.rebirth_install_root)
        oodle_dll = bpy.path.abspath(prefs.rebirth_oodle_dll)
        usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
        if not _VIRTUAL_UMAPS:
            refresh_umap_index(game_root, oodle_dll, usmap_path)
        virtual_paths = [path for path in _VIRTUAL_UMAPS if path in _SELECTED_UMAPS]
        scripted_path = self.virtual_path.strip().replace("\\", "/")
        if not virtual_paths and scripted_path:
            virtual_paths = [scripted_path]
        if not virtual_paths and not scripted_path:
            state = _browser_state(context)
            if 0 <= state.active_index < len(state.entries):
                highlighted = state.entries[state.active_index]
                if not highlighted.is_directory:
                    virtual_paths = [highlighted.virtual_path]
        invalid_paths = [path for path in virtual_paths if path not in _VIRTUAL_UMAPS]
        if invalid_paths:
            self.report({'ERROR'}, f"Package UMAP was not found: {invalid_paths[0]}")
            return {'CANCELLED'}
        if not virtual_paths:
            self.report({'ERROR'}, "Highlight or select at least one UMAP from the package browser.")
            return {'CANCELLED'}
        queued_paths = set(virtual_paths)

        completed_map_total = 0
        processed_total = 0
        skipped_total = 0
        unresolved_total = 0
        actor_created_total = 0
        actor_missing_total: set[str] = set()
        failures: list[tuple[str, str]] = []
        window_manager = context.window_manager
        progress_max = len(_VIRTUAL_UMAPS) if self.recursive_import else len(virtual_paths)
        window_manager.progress_begin(0, max(1, progress_max))
        try:
            with tempfile.TemporaryDirectory(prefix="ff7r_mec_") as temp_dir:
                package_session = PackageAssetSession(game_root, oodle_dll, usmap_path)
                with package_session:
                    static_mesh_resolver = (
                        PackageStaticMeshResolver(
                            context,
                            package_session,
                            self.scale_factor,
                            offset_opposite_faces=self.offset_opposite_faces,
                        )
                        if self.import_models
                        else None
                    )
                    skeletal_mesh_resolver = (
                        PackageSkeletalMeshResolver(
                            context,
                            package_session,
                            self.scale_factor,
                            offset_opposite_faces=self.offset_opposite_faces,
                        )
                        if self.import_models
                        else None
                    )
                    loader_context = (
                        image_loader_override(package_session)
                        if self.import_textures
                        else nullcontext()
                    )
                    with loader_context:
                        for map_index, virtual_path in enumerate(virtual_paths, 1):
                            window_manager.progress_update(map_index - 1)
                            print(
                                f"Package batch map {map_index}/{len(virtual_paths)}: {virtual_path}"
                            )
                            try:
                                map_temp_dir = os.path.join(temp_dir, f"{map_index:04d}")
                                os.makedirs(map_temp_dir, exist_ok=True)
                                local_umap = os.path.join(map_temp_dir, os.path.basename(virtual_path))
                                package_session.extract_raw(virtual_path, local_umap)
                                virtual_ubulk = os.path.splitext(virtual_path)[0] + ".ubulk"
                                local_ubulk = os.path.splitext(local_umap)[0] + ".ubulk"
                                try:
                                    package_session.extract_raw(
                                        virtual_ubulk,
                                        local_ubulk,
                                        report_errors=False,
                                    )
                                except Exception:
                                    pass

                                actor_payload = None
                                if self.import_models or self.import_lights or self.recursive_import:
                                    try:
                                        import_names, actor_payload = package_session.umap_data(virtual_path)
                                    except Exception as actor_read_error:
                                        # Actor parsing is newer and less universal than
                                        # MEC; retain the established MEC import path.
                                        import_names = package_session.import_names(virtual_path)
                                        failures.append((f"{virtual_path} [actor data]", str(actor_read_error)))
                                        print(f"Package actor data read failed: {virtual_path}: {actor_read_error}")
                                else:
                                    import_names = package_session.import_names(virtual_path)
                                try:
                                    # The bridge has handed the package-derived payload
                                    # to Python; release its decoded export graph before
                                    # Blender begins the potentially long geometry build.
                                    package_session.release_batch_memory()
                                except Exception as cleanup_error:
                                    # Cleanup is an optimization; it must never discard
                                    # an otherwise successful map import.
                                    print(f"Package bridge cleanup failed: {cleanup_error}")
                                normalized_local = os.path.normcase(os.path.realpath(local_umap))
                                try:
                                    processed, skipped, unresolved = import_umap_paths(
                                        context,
                                        [local_umap],
                                        lod_mode=self.lod_mode,
                                        lod_quality=self.lod_quality,
                                        lod_level=self.lod_level,
                                        import_originals=self.import_originals,
                                        offset_opposite_faces=self.offset_opposite_faces,
                                        import_sway=self.import_sway,
                                        scale_factor=self.scale_factor,
                                        tex_root="",
                                        tex_match_by_filename=False,
                                        import_names_by_path={normalized_local: import_names},
                                    )
                                    processed_total += processed
                                    skipped_total += skipped
                                    unresolved_total += unresolved
                                except Exception as mec_error:
                                    failures.append((f"{virtual_path} [MEC]", str(mec_error)))
                                    print(f"Package MEC import failed: {virtual_path}: {mec_error}")

                                actor_data = (actor_payload or {}).get("actors") or []
                                if (self.import_models or self.import_lights) and actor_data:
                                    try:
                                        actor_created, actor_missing = map_import.import_map_entries(
                                            actor_data,
                                            virtual_path,
                                            exposure_mult=1.0,
                                            attenuation_radius_mult=1.0,
                                            location_scale=self.scale_factor,
                                            always_cast_shadows=self.always_cast_shadows,
                                            static_mesh_resolver=static_mesh_resolver,
                                            skeletal_mesh_resolver=skeletal_mesh_resolver,
                                            import_models=self.import_models,
                                            import_lights=self.import_lights,
                                        )
                                        actor_created_total += actor_created
                                        actor_missing_total |= actor_missing
                                    except Exception as actor_error:
                                        failures.append((f"{virtual_path} [actors]", str(actor_error)))
                                        print(f"Package actor import failed: {virtual_path}: {actor_error}")

                                if self.recursive_import:
                                    for asset_path in map_import.collect_level_streaming_asset_paths(actor_data):
                                        child_path = _game_asset_path_to_virtual_umap(asset_path)
                                        if child_path and child_path in _VIRTUAL_UMAPS and child_path not in queued_paths:
                                            queued_paths.add(child_path)
                                            virtual_paths.append(child_path)
                                completed_map_total += 1
                            except Exception as map_error:
                                failures.append((virtual_path, str(map_error)))
                                print(f"Package batch map failed: {virtual_path}: {map_error}")
                            if self.import_textures:
                                try:
                                    # Texture requests happen during Blender's import,
                                    # after the early package cleanup above.
                                    package_session.release_batch_memory()
                                except Exception as cleanup_error:
                                    print(f"Package bridge cleanup failed: {cleanup_error}")
                            window_manager.progress_update(map_index)
        except Exception as exc:
            self.report({'ERROR'}, f"Package import failed: {exc}")
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()

        if not processed_total and not actor_created_total:
            detail = f" First failure: {failures[0][1]}" if failures else ""
            self.report({'WARNING'}, f"No selected UMAP produced importable geometry or actors.{detail}")
            return {'CANCELLED'}
        message = f"Completed {completed_map_total}/{len(virtual_paths)} package UMAP(s)"
        if processed_total:
            message += f"; {processed_total} MEC dataset(s)"
        if skipped_total:
            message += f"; {skipped_total} skipped"
        if failures:
            message += f"; {len(failures)} stage failure(s)"
        if unresolved_total:
            message += f"; {unresolved_total} unresolved texture path(s)"
        if actor_created_total:
            message += f"; {actor_created_total} actor/light object(s)"
        if actor_missing_total:
            message += f"; {len(actor_missing_total)} actor asset(s) unavailable"
            missing_preview = sorted(actor_missing_total, key=str.casefold)
            if len(missing_preview) > 20:
                missing_preview = missing_preview[:20] + ["..."]
            print(
                "[FF7R Package UMAP] ERROR: "
                f"{len(actor_missing_total)} actor asset(s) could not be loaded: "
                + ", ".join(missing_preview)
            )
        self._save_last_import_settings(context)
        self.report({'INFO'}, message)
        return {'FINISHED'}


class FF7R_REBIRTH_OT_import_kdi_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_kdi_game_packages"
    bl_label = "KineDriver JSON from Rebirth Packages"
    bl_description = "Search the mounted game packages for a _KDI asset and build its drivers on the active armature"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Package KDI",
        description="Unreal virtual path. Type any part of a folder or filename to search",
        search=_search_virtual_kdis,
        search_options={'SORT'},
    )
    replace_previous_generated: bpy.props.BoolProperty(
        name="Replace previous generated KDI layer",
        default=True,
    )
    # The package skeleton applies a +90-degree roll to align with the established
    # loose-JSON KDI convention. Its KDI scalar target channels therefore cycle
    # X -> Y, Y -> Z, Z -> X. Loose-file/umodel armatures retain XZY.
    translation_axis_order: bpy.props.EnumProperty(
        name="Translation axis mapping",
        items=AXIS_ORDER_ITEMS,
        default="YZX",
    )
    scale_axis_order: bpy.props.EnumProperty(
        name="Scale axis mapping",
        items=AXIS_ORDER_ITEMS,
        default="YZX",
    )

    # Deliberately excludes translation/scale axis order: those are re-derived
    # from the active armature's coordinate profile below on every invoke, and
    # persisting a stale value could silently pick the wrong convention for a
    # different rig type.
    _persisted_props = ("replace_previous_generated",)

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        armature = context.active_object
        if armature and armature.type == "ARMATURE":
            package_profile = armature.get(KDI_COORDINATE_PROFILE_PROPERTY)
            if package_profile == COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90:
                self.translation_axis_order = "YZX"
                self.scale_axis_order = "YZX"
            else:
                self.translation_axis_order = "XZY"
                self.scale_axis_order = "XZY"
        self._load_last_import_settings(context)
        try:
            paths = refresh_kdi_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not paths:
            self.report({'WARNING'}, "No _KDI assets were found in the mounted game packages.")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=850)

    def draw(self, _context):
        layout = self.layout
        layout.label(text=f"{len(_VIRTUAL_KDIS):,} KDI assets mounted", icon='PACKAGE')
        layout.prop(self, "virtual_path", icon='VIEWZOOM')
        layout.separator()
        layout.prop(self, "replace_previous_generated")
        layout.label(text="Experimental target-axis mapping")
        layout.prop(self, "translation_axis_order")
        layout.prop(self, "scale_axis_order")

    def execute(self, context):
        prefs = _preferences(context)
        virtual_path = self.virtual_path.strip().replace("\\", "/")
        if not _VIRTUAL_KDIS:
            refresh_kdi_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        if virtual_path not in _VIRTUAL_KDIS:
            self.report({'ERROR'}, "Choose a KDI path from the package search results.")
            return {'CANCELLED'}

        try:
            with tempfile.TemporaryDirectory(prefix="ff7r_kdi_") as temp_dir:
                session = PackageAssetSession(
                    bpy.path.abspath(prefs.rebirth_install_root),
                    bpy.path.abspath(prefs.rebirth_oodle_dll),
                    bpy.path.abspath(prefs.rebirth_usmap_path),
                )
                with session:
                    kdi_asset = session.kdi_asset(virtual_path)
                kdi_path = os.path.join(temp_dir, os.path.basename(virtual_path) + ".json")
                with open(kdi_path, "w", encoding="utf-8") as stream:
                    json.dump([kdi_asset], stream, ensure_ascii=False, indent=2)
                result = bpy.ops.import_scene.ff7r_kinedriver_json(
                    filepath=kdi_path,
                    replace_previous_generated=self.replace_previous_generated,
                    translation_axis_order=self.translation_axis_order,
                    scale_axis_order=self.scale_axis_order,
                    coordinate_profile=(
                        context.active_object.get(
                            KDI_COORDINATE_PROFILE_PROPERTY,
                            COORDINATE_PROFILE_REFERENCE,
                        )
                        if context.active_object and context.active_object.type == "ARMATURE"
                        else COORDINATE_PROFILE_REFERENCE
                    ),
                )
        except Exception as exc:
            self.report({'ERROR'}, f"Package KDI import failed: {exc}")
            return {'CANCELLED'}
        if result != {'FINISHED'}:
            self.report({'ERROR'}, "The KDI driver generator could not complete.")
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        self.report({'INFO'}, f"Imported KDI drivers from {virtual_path}")
        return {'FINISHED'}


def _kdi_path_for_skeleton(virtual_path: str) -> str | None:
    """Derive the associated KDI asset's virtual path from a Skeleton's, if any.

    Character asset folders name these as siblings, e.g. ``PC0000_00_Skeleton.uasset``
    next to ``PC0000_00_KDI.uasset`` -- same directory, ``_Skeleton`` swapped for
    ``_KDI``. Confirmed for Cloud; callers must still check the mounted _KDI index,
    since plenty of Skeletons (most enemies/props) have no KineDriver rig at all.
    """
    suffix = "_skeleton.uasset"
    if not virtual_path.casefold().endswith(suffix):
        return None
    return virtual_path[: -len(suffix)] + "_KDI.uasset"


def _secondary_kdi_paths_for_skeleton(virtual_path: str, available: list[str]) -> list[str]:
    """Sibling ``<stem>_KDI_<suffix>.uasset`` passes for a Skeleton, if any."""
    main = _kdi_path_for_skeleton(virtual_path)
    if main is None:
        return []
    return _secondary_kdi_paths_for_main(main, available)


def _secondary_kdi_paths_for_main(main: str, available: list[str]) -> list[str]:
    """Return secondary passes belonging to one explicit main KDI asset."""
    prefix = main[: -len(".uasset")] + "_"
    lowered = prefix.casefold()
    return sorted(
        (path for path in available
         if path.casefold().startswith(lowered) and path.casefold().endswith(".uasset")),
        key=str.casefold,
    )


def _skeletal_mesh_kdi_paths(skeletal_mesh: dict) -> list[str]:
    """Normalized KDI references authored on this exact SkeletalMesh variant."""
    paths = []
    seen = set()
    for value in skeletal_mesh.get("kdiPaths") or []:
        if not isinstance(value, str):
            continue
        path = value.strip().replace("\\", "/").lstrip("/")
        key = path.casefold()
        if path and key not in seen:
            paths.append(path)
            seen.add(key)
    return paths


def _import_secondary_kdi_passes(
        secondary_assets: list[tuple[str, dict]],
        temp_dir: str,
) -> str:
    """Stack a character's secondary KDI passes onto the main layer.

    Takes assets already fetched from the bridge rather than a live session:
    drivers are built after the session block has closed, so anything read
    lazily here would find the bridge gone.

    Each is imported additively, so a pass that re-drives a channel the main
    layer already owns has that channel skipped rather than clobbering it. A
    failure here only shortens the report -- it must never fail the import,
    since the skeleton and the main KDI layer are already in place.
    """
    imported, skipped = [], []
    for secondary_path, asset in secondary_assets:
        label = os.path.basename(secondary_path)
        try:
            if not (asset and asset.get("Properties")):
                skipped.append(label)
                continue
            path = os.path.join(temp_dir, label + ".json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump([asset], stream, ensure_ascii=False, indent=2)
            result = bpy.ops.import_scene.ff7r_kinedriver_json(
                filepath=path,
                replace_previous_generated=False,
                additive=True,
                translation_axis_order="YZX",
                scale_axis_order="YZX",
                coordinate_profile=COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
            )
            (imported if result == {'FINISHED'} else skipped).append(label)
        except Exception as exc:
            print(f"  Warning: secondary KDI '{secondary_path}' was not imported: {exc}")
            skipped.append(label)
    note = ""
    if imported:
        note += f"; stacked {len(imported)} secondary KDI pass(es): {', '.join(imported)}"
    if skipped:
        note += f"; {len(skipped)} secondary pass(es) skipped: {', '.join(skipped)}"
    return note


def _character_family_search_path(virtual_path: str) -> str | None:
    """Return the narrow game-package prefix for one playable-character family."""
    match = re.search(r"/Character/Player/(PC\d{4})_\d{2}(?:_|/)", virtual_path, re.IGNORECASE)
    if match is None:
        return None
    return f"Character/Player/{match.group(1).upper()}_"


def _create_variant_bone_collections(armature_obj, usage: dict) -> dict[str, int]:
    """Assign variant-exclusive, directly weighted bones to named collections.

    Collections are additional memberships: unlike KDI's hidden-helper collections,
    these never remove a bone from a normal visible collection or alter its hide state.
    The bridge returns names rather than mesh-local indices, which lets a mesh's
    reduced ReferenceSkeleton map back to the armature's complete master skeleton.
    """
    armature = armature_obj.data
    created: dict[str, int] = {}
    collection_data: dict[str, list[str]] = {}
    for variant_id, variant_info in (usage.get("variants") or {}).items():
        bone_names = {
            name for name in (variant_info.get("exclusiveWeightedBoneNames") or [])
            if armature.bones.get(name) is not None
        }
        if not bone_names:
            continue
        collection = armature.collections.get(variant_id)
        if collection is None:
            collection = armature.collections.new(variant_id)
        for bone_name in sorted(bone_names, key=str.casefold):
            bone = armature.bones[bone_name]
            if collection not in list(bone.collections):
                collection.assign(bone)
        created[variant_id] = len(bone_names)
        collection_data[variant_id] = sorted(bone_names, key=str.casefold)

    armature_obj["ff7r_variant_bone_usage"] = json.dumps({
        "skeletonAssetPath": usage.get("skeletonAssetPath", ""),
        "searchedMeshCount": usage.get("searchedMeshCount", 0),
        "parsedMeshCount": usage.get("parsedMeshCount", 0),
        "collections": collection_data,
    }, ensure_ascii=False, sort_keys=True)
    return created


def _restrict_skeleton_to_folder_mesh_bones(
        skeleton_asset: dict,
        usage: dict,
        skeleton_virtual_path: str,
) -> tuple[dict, int, int]:
    """Keep the folder mesh's complete ReferenceSkeleton and parent hierarchy."""
    folder = skeleton_virtual_path.split("/Model/", 1)[0].casefold()
    referenced_bones = set()
    for mesh in usage.get("meshes") or []:
        if str(mesh.get("variantFolder") or "").casefold() == folder:
            # Mesh ReferenceSkeleton is the subset FModel/umodel export. It includes
            # unweighted procedural/KDI bones such as R_TopBeltOsKdi; BoneMap and
            # ActiveBoneIndices intentionally do not.
            referenced_bones.update(mesh.get("referenceBoneNames") or [])
    if not referenced_bones:
        raise ValueError("No mesh ReferenceSkeleton bones were found beside this Skeleton.")

    source_bones = list(skeleton_asset.get("bones") or [])
    index_by_name = {bone.get("name"): index for index, bone in enumerate(source_bones)}
    included = {index_by_name[name] for name in referenced_bones if name in index_by_name}
    if not included:
        raise ValueError("The mesh-referenced bone names did not occur in this Skeleton.")

    # A mesh can weight a child while Blender still needs every parent in order to
    # reconstruct that child's component-space bind transform.
    pending = list(included)
    while pending:
        index = pending.pop()
        parent_index = int(source_bones[index].get("parentIndex", -1))
        if 0 <= parent_index < len(source_bones) and parent_index not in included:
            included.add(parent_index)
            pending.append(parent_index)

    retained_indices = [index for index in range(len(source_bones)) if index in included]
    remapped_indices = {old_index: new_index for new_index, old_index in enumerate(retained_indices)}
    reduced_bones = []
    for old_index in retained_indices:
        bone = dict(source_bones[old_index])
        parent_index = int(bone.get("parentIndex", -1))
        bone["parentIndex"] = remapped_indices.get(parent_index, -1)
        reduced_bones.append(bone)

    reduced_asset = dict(skeleton_asset)
    reduced_asset["bones"] = reduced_bones
    reduced_asset["sockets"] = [
        socket for socket in (skeleton_asset.get("sockets") or [])
        if socket.get("boneName") in {bone.get("name") for bone in reduced_bones}
    ]
    return reduced_asset, len(referenced_bones), len(reduced_bones)


class FF7R_REBIRTH_OT_import_skeleton_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_skeleton_game_packages"
    bl_label = "Skeleton from Rebirth Packages"
    bl_description = "Search the mounted game packages for a _Skeleton asset and build its armature"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Package Skeleton",
        description="Unreal virtual path. Type any part of a folder or filename to search",
        search=_search_virtual_skeletons,
        search_options={'SORT'},
    )
    armature_name: bpy.props.StringProperty(
        name="Armature Name",
        description="Leave blank to name the armature after the skeleton asset",
        default="",
    )
    scale_factor: bpy.props.FloatProperty(name="Scale", default=0.01, min=0.0001, max=100.0)
    connect_bones: bpy.props.BoolProperty(
        name="Connect bones close to their parent's tail",
        description=(
            "Move the parent's tail to the imported child head, then enable Blender's "
            "connected-bone display, preserving the child's original head position"
        ),
        default=False,
    )
    attachment_sockets: bpy.props.EnumProperty(
        name="Attachment Sockets",
        description="Choose how attachment sockets are materialized on the generated armature",
        items=ATTACHMENT_SOCKETS_ITEMS,
        default=ATTACHMENT_SOCKETS_EMPTIES,
    )
    setup_naive_ik: bpy.props.BoolProperty(
        name="Setup IK (naive)",
        description=(
            "Add a chain-length-3 IK constraint (no target) to R_Foot_a/L_Foot_a/"
            "R_Hand_a/L_Hand_a, and lock Y/Z rotation to 0 on R_Foreleg_a/L_Foreleg_a/"
            "R_Forearm_a/L_Forearm_a so they only bend as a hinge. Bones not present "
            "on this skeleton are skipped"
        ),
        default=False,
    )
    create_limbal_bone: bpy.props.BoolProperty(
        name="Create C_Limbal eye controller",
        description=(
            "When L_Eye or R_Eye exists, create a centered non-deforming controller "
            "one foot in front of the character for imported eye materials"
        ),
        default=False,
    )
    import_secondary_kdi: bpy.props.BoolProperty(
        name="Also import secondary KDI passes",
        description=(
            "Stack any sibling _KDI_Extra1/_Head/_Hood/_StBody/_StHair passes onto the "
            "main KDI layer. In-game _Extra1 runs after Bonamik physics, which this "
            "add-on does not simulate, so it is an approximation; channels the main "
            "layer already drives are left alone"
        ),
        default=True,
    )
    import_kdi: bpy.props.BoolProperty(
        name="Import associated KDI",
        description=(
            "After building the armature, also search the mounted packages for a "
            "matching _KDI asset (e.g. PC0000_00_KDI beside PC0000_00_Skeleton) and "
            "import its drivers onto it. Skipped silently if none exists"
        ),
        # KineDriver has its own importer.  Keep this internal override for
        # callers that intentionally assemble a full rig (for example, the
        # cutscene importer), while the visible "Skeleton only" entry stays
        # limited to the armature.
        default=False,
    )
    kdi_virtual_path_override: bpy.props.StringProperty(
        name="KDI Path Override",
        description=(
            "Internal SkeletalMesh-provided KineDriver path; blank keeps the "
            "Skeleton-name fallback"
        ),
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    create_variant_bone_collections: bpy.props.BoolProperty(
        name="Create variant bone collections",
        description=(
            "For player skeletons, scan meshes sharing this skeleton and create a "
            "collection named after each variant that has uniquely weighted bones"
        ),
        default=True,
    )
    import_mesh_referenced_bones_only: bpy.props.BoolProperty(
        name="Only import bones used by meshes in this folder",
        description=(
            "Keep this folder's complete mesh ReferenceSkeleton, including unweighted "
            "KDI/helper bones, rather than every bone in the master Skeleton. This "
            "matches FModel/umodel; variant-collection creation is skipped"
        ),
        default=False,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward",
        description="Choose the generated armature's forward axis",
        items=FACE_FORWARD_ITEMS,
        default=FACE_FORWARD_UNREAL,
    )

    _persisted_props = (
        "scale_factor",
        "connect_bones",
        "attachment_sockets",
        "setup_naive_ik",
        "create_limbal_bone",
        "create_variant_bone_collections",
        "import_mesh_referenced_bones_only",
        "face_y_forward",
    )

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        self._load_last_import_settings(context)
        try:
            paths = refresh_skeleton_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not paths:
            self.report({'WARNING'}, "No _Skeleton assets were found in the mounted game packages.")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=850)

    def draw(self, _context):
        layout = self.layout
        layout.label(text=f"{len(_VIRTUAL_SKELETONS):,} Skeleton assets mounted", icon='PACKAGE')
        layout.prop(self, "virtual_path", icon='VIEWZOOM')
        layout.separator()
        layout.prop(self, "armature_name")
        layout.prop(self, "scale_factor")
        layout.prop(self, "connect_bones")
        layout.prop(self, "attachment_sockets")
        layout.prop(self, "setup_naive_ik")
        layout.prop(self, "create_limbal_bone")
        layout.prop(self, "create_variant_bone_collections")
        layout.prop(self, "import_mesh_referenced_bones_only")
        layout.prop(self, "face_y_forward")

    def execute(self, context):
        prefs = _preferences(context)
        virtual_path = self.virtual_path.strip().replace("\\", "/")
        if not _VIRTUAL_SKELETONS:
            refresh_skeleton_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        if virtual_path not in _VIRTUAL_SKELETONS:
            self.report({'ERROR'}, "Choose a Skeleton path from the package search results.")
            return {'CANCELLED'}

        kdi_override = self.kdi_virtual_path_override.strip().replace("\\", "/").lstrip("/")
        kdi_virtual_path = None
        if self.import_kdi:
            kdi_virtual_path = kdi_override or _kdi_path_for_skeleton(virtual_path)
        secondary_kdi_paths: list[str] = []
        if kdi_virtual_path is not None:
            try:
                if not _VIRTUAL_KDIS:
                    refresh_kdi_index(
                        bpy.path.abspath(prefs.rebirth_install_root),
                        bpy.path.abspath(prefs.rebirth_oodle_dll),
                        bpy.path.abspath(prefs.rebirth_usmap_path),
                    )
                if self.import_secondary_kdi:
                    secondary_kdi_paths = _secondary_kdi_paths_for_main(
                        kdi_virtual_path, _VIRTUAL_KDIS
                    )
                if kdi_virtual_path not in _VIRTUAL_KDIS:
                    kdi_virtual_path = None  # no matching KDI asset for this character
            except Exception:
                kdi_virtual_path = None  # non-fatal: proceed with the skeleton alone
                secondary_kdi_paths = []

        try:
            with tempfile.TemporaryDirectory(prefix="ff7r_skeleton_") as temp_dir:
                session = PackageAssetSession(
                    bpy.path.abspath(prefs.rebirth_install_root),
                    bpy.path.abspath(prefs.rebirth_oodle_dll),
                    bpy.path.abspath(prefs.rebirth_usmap_path),
                )
                with session:
                    skeleton_asset = session.skeleton_asset(virtual_path)
                    kdi_asset = None
                    secondary_kdi_assets: list[tuple[str, dict]] = []
                    variant_bone_usage = None
                    if kdi_virtual_path is not None:
                        try:
                            kdi_asset = session.kdi_asset(kdi_virtual_path)
                        except Exception as exc:
                            print(f"  Warning: associated KDI '{kdi_virtual_path}' could not be fetched: {exc}")
                        # Fetch the secondary passes here too: the drivers are
                        # built after this block, by which point the bridge
                        # session has already been torn down.
                        for secondary_path in secondary_kdi_paths:
                            try:
                                secondary_kdi_assets.append(
                                    (secondary_path, session.kdi_asset(secondary_path))
                                )
                            except Exception as exc:
                                print(f"  Warning: secondary KDI '{secondary_path}' could not be fetched: {exc}")
                    family_search_path = _character_family_search_path(virtual_path)
                    needs_variant_usage = (
                        (self.create_variant_bone_collections or self.import_mesh_referenced_bones_only)
                        and family_search_path is not None
                    )
                    if needs_variant_usage:
                        try:
                            variant_bone_usage = session.skeleton_bone_usage(
                                virtual_path, family_search_path
                            )
                        except Exception as exc:
                            # Collection organization is convenient metadata, not a
                            # reason to throw away an otherwise valid skeleton import.
                            print(f"  Warning: variant bone usage could not be read: {exc}")
                if not skeleton_asset.get("bones"):
                    raise RuntimeError("The bridge returned no bones for this asset.")
                reduced_bone_note = ""
                if self.import_mesh_referenced_bones_only:
                    if not variant_bone_usage:
                        raise RuntimeError(
                            "Mesh bone usage is unavailable; cannot make a reduced skeleton."
                        )
                    skeleton_asset, referenced_count, retained_count = _restrict_skeleton_to_folder_mesh_bones(
                        skeleton_asset, variant_bone_usage, virtual_path
                    )
                    reduced_bone_note = (
                        f"; retained {retained_count} hierarchy bone(s) from "
                        f"{referenced_count} mesh ReferenceSkeleton bone(s)"
                    )
                skeleton_stem = os.path.basename(virtual_path)
                if skeleton_stem.lower().endswith(".uasset"):
                    skeleton_stem = skeleton_stem[: -len(".uasset")]
                socket_data = (
                    skeleton_asset.get("sockets") or []
                    if self.attachment_sockets != ATTACHMENT_SOCKETS_NONE
                    else []
                )
                armature_obj = build_armature_from_bones(
                    context,
                    self.armature_name.strip()
                    or skeleton_asset.get("name")
                    or skeleton_stem,
                    _bones_from_bridge(skeleton_asset),
                    socket_data,
                    scale_factor=self.scale_factor,
                    connect_bones=self.connect_bones,
                    create_socket_empties=(
                        self.attachment_sockets == ATTACHMENT_SOCKETS_EMPTIES
                    ),
                    create_socket_bones=(
                        self.attachment_sockets == ATTACHMENT_SOCKETS_BONES
                    ),
                    setup_naive_ik=self.setup_naive_ik,
                    create_limbal_bone=self.create_limbal_bone,
                    face_y_forward=_face_y_forward_enabled(self.face_y_forward),
                )
                armature_obj[SKELETON_ASSET_PATH_PROPERTY] = virtual_path
                armature_obj[KDI_COORDINATE_PROFILE_PROPERTY] = COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90

                collection_note = ""
                if variant_bone_usage and not self.import_mesh_referenced_bones_only:
                    created_collections = _create_variant_bone_collections(
                        armature_obj, variant_bone_usage
                    )
                    if created_collections:
                        bone_count = sum(created_collections.values())
                        collection_note = (
                            f"; created {len(created_collections)} variant bone collection(s) "
                            f"with {bone_count} exclusive bone(s)"
                        )

                kdi_note = ""
                if kdi_asset and kdi_asset.get("Properties"):
                    for obj in context.selected_objects:
                        obj.select_set(False)
                    context.view_layer.objects.active = armature_obj
                    armature_obj.select_set(True)
                    kdi_path = os.path.join(temp_dir, os.path.basename(kdi_virtual_path) + ".json")
                    with open(kdi_path, "w", encoding="utf-8") as stream:
                        json.dump([kdi_asset], stream, ensure_ascii=False, indent=2)
                    try:
                        kdi_result = bpy.ops.import_scene.ff7r_kinedriver_json(
                            filepath=kdi_path,
                            replace_previous_generated=True,
                            translation_axis_order="YZX",
                            scale_axis_order="YZX",
                            coordinate_profile=COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
                        )
                        kdi_note = (
                            f"; also imported KDI drivers from {kdi_virtual_path}"
                            if kdi_result == {'FINISHED'}
                            else "; the associated KDI could not be imported"
                        )
                        if kdi_result == {'FINISHED'} and secondary_kdi_assets:
                            kdi_note += _import_secondary_kdi_passes(
                                secondary_kdi_assets,
                                temp_dir,
                            )
                    except RuntimeError as exc:
                        kdi_note = f"; the associated KDI could not be imported: {exc}"
        except Exception as exc:
            self.report({'ERROR'}, f"Package Skeleton import failed: {exc}")
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        self.report({'INFO'}, f"Imported skeleton as '{armature_obj.name}'{reduced_bone_note}{collection_note}{kdi_note}")
        return {'FINISHED'}


CLASSES = (
    FF7R_PG_mesh_search_entry,
    FF7R_UL_mesh_search_results,
    FF7R_PG_cutscene_search_entry,
    FF7R_UL_cutscene_search_results,
    FF7R_PG_package_browser_entry,
    FF7R_PG_package_browser_state,
    FF7R_UL_package_umaps,
    FF7R_REBIRTH_OT_package_browser_folder,
    FF7R_REBIRTH_OT_package_browser_up,
    FF7R_REBIRTH_OT_package_browser_select,
    FF7R_REBIRTH_OT_import_static_mesh_game_packages,
    FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages,
    FF7R_REBIRTH_OT_import_cutscene_game_packages,
    FF7R_REBIRTH_OT_import_nearby_mec_terrain,
    FF7R_REBIRTH_OT_import_mec_game_packages,
    FF7R_REBIRTH_OT_import_kdi_game_packages,
    FF7R_REBIRTH_OT_import_skeleton_game_packages,
)


def register_runtime_properties():
    # Replacing the class generation after a script reload also requires
    # replacing this RNA PointerProperty, otherwise its type can refer to the
    # previous PropertyGroup class.
    unregister_runtime_properties()
    bpy.types.WindowManager.ff7r_package_browser = bpy.props.PointerProperty(
        type=FF7R_PG_package_browser_state
    )


def unregister_runtime_properties():
    if hasattr(bpy.types.WindowManager, "ff7r_package_browser"):
        del bpy.types.WindowManager.ff7r_package_browser
