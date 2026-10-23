"""Browse and import maps and character data directly from Rebirth packages."""

from __future__ import annotations

from ....language import strings

import json
import os
import re
import tempfile
import traceback
from contextlib import nullcontext
from pathlib import Path

import bpy
from bpy_extras import anim_utils

from ....core.profiles import GamePaths
from ..profile import PROFILE as REBIRTH_PROFILE
from ....formats.mec.importer import import_umap_paths
from ....formats.mec.material import image_loader_override
from ....ui.textures import TEXTURE_OPTION_NAMES, texture_properties, texture_options, draw_texture_options
from ....formats.ue_map.package_importer import MapBrowserState, PackageMapSource, make_package_map_importer
from ....formats.ue_map.streaming import StreamingMapQueue
from ....formats.ue_map.landscapes import import_options as landscape_options
from ....formats.ue_map import map_import
from ....formats.bnm import parser as bnm_parser
from ....formats.bnm import storage as bnm_storage
from ..materials import rmi_surface
from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....core.package_utils import addon_package_name
from ....core.blender.mouth_rig import generate_mouth_rig
from ....formats.kdi.drivers import (
    AXIS_ORDER_ITEMS,
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
    COORDINATE_PROFILE_REFERENCE,
    COORDINATE_PROFILE_SOURCE_AXES,
    coordinate_profile_axis_order,
)
from ....core.blender.skeletons import (
    _bones_from_gargoyle,
    build_armature_from_bones,
    FACE_FORWARD_UNREAL,
    AXIS_ORDER_UNREAL,
    AXIS_ORDER_PROPERTY,
)
from ... import package_browser
from ....ui.mesh_importer import (
    SKELETAL_OPTION_NAMES,
)
from ....formats.unreal_package.importer import (
    MeshBrowserState, PackageMeshSource, make_package_mesh_importer,
)


# Compatibility adapters preserve the Rebirth-facing API used by older scripts.
# General importers depend on formats.unreal_package directly.
from ....formats import unreal_package as package_runtime
from ....formats.unreal_package.indexing import MeshAssetIndex, AnimationAssetIndex
from ....formats.unreal_package import (  # noqa: F401 - compatibility reexports
    _package_config_key, _mesh_disk_cache_path, _natural_path_key,
    _load_mesh_disk_cache, _save_mesh_disk_cache, _package_search_terms,
    _path_matches_package_search, _search_virtual_paths,
    _static_mesh_material, _apply_face_y_forward,
    _create_variant_bone_collections, _restrict_skeleton_to_referenced_bones,
    _normalize_offset_faces_mode, _face_y_forward_enabled,
    KDI_COORDINATE_PROFILE_PROPERTY, SKELETON_ASSET_PATH_PROPERTY,
    OFFSET_FACES_NONE, OFFSET_FACES_BAKED, OFFSET_FACES_MODIFIER, OFFSET_FACES_ITEMS,
    ATTACHMENT_SOCKETS_NONE, ATTACHMENT_SOCKETS_EMPTIES, ATTACHMENT_SOCKETS_BONES,
    ATTACHMENT_SOCKETS_ITEMS, FACE_FORWARD_ITEMS,
    _ensure_scene_collection, _layer_collection_for, _active_collection,
    _adopt_new_scene_collections,
)


def _gargoyle_command(game_root, oodle_dll, usmap_path, output_json,
                      profile=REBIRTH_PROFILE, aes_key="", **options):
    return package_runtime._gargoyle_command(
        game_root, oodle_dll, usmap_path, output_json,
        profile=profile, aes_key=aes_key, **options,
    )


def _run_gargoyle(*args, profile=REBIRTH_PROFILE, **kwargs):
    return package_runtime._run_gargoyle(*args, profile=profile, **kwargs)


def _run_gargoyle_asset_request(*args, profile=REBIRTH_PROFILE, **kwargs):
    return package_runtime._run_gargoyle_asset_request(*args, profile=profile, **kwargs)


def _mesh_package_signature(game_root, profile=REBIRTH_PROFILE):
    return package_runtime._mesh_package_signature(game_root, profile=profile)


def _texture_package_path(game_path, *, profile=REBIRTH_PROFILE):
    return package_runtime._texture_package_path(game_path, profile=profile)


def _game_asset_path_to_virtual_uasset(asset_path, *, profile=REBIRTH_PROFILE):
    return package_runtime._game_asset_path_to_virtual_uasset(asset_path, profile=profile)


class PackageAssetSession(package_runtime.PackageAssetSession):
    def __init__(self, *args, profile=REBIRTH_PROFILE, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)


def _mesh_hooks():
    return package_runtime.MeshImportHooks(
        material_builder=rmi_surface.build_material,
        initialize_object=rmi_surface.initialize_external_emissive_context,
        configure_binding=rmi_surface.configure_limbal_eye_drivers,
    )


def import_static_mesh_asset(*args, **kwargs):
    kwargs.setdefault("hooks", _mesh_hooks())
    return package_runtime.import_static_mesh_asset(*args, **kwargs)


def import_skeletal_mesh_asset(*args, **kwargs):
    kwargs.setdefault("hooks", _mesh_hooks())
    return package_runtime.import_skeletal_mesh_asset(*args, **kwargs)


def bind_skeletal_mesh_object(*args, **kwargs):
    kwargs.setdefault("hooks", _mesh_hooks())
    return package_runtime.bind_skeletal_mesh_object(*args, **kwargs)


class PackageStaticMeshResolver(package_runtime.PackageStaticMeshResolver):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("hooks", _mesh_hooks())
        super().__init__(*args, **kwargs)


class PackageSkeletalMeshResolver(package_runtime.PackageSkeletalMeshResolver):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("hooks", _mesh_hooks())
        super().__init__(*args, **kwargs)


_VIRTUAL_UMAPS: list[str] = []
_CACHE_KEY: tuple[str, str, str] | None = None
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
_UMAP_BROWSER = package_browser.make_state(
    "Rebirth UMAP assets",
    initial_directory="End/Content/Level/Game/Field",
    root_directory="End/Content",
    file_icon="FILE",
)

_VIRTUAL_ANIMATIONS: list[str] = []
_ANIMATION_CACHE_KEY: tuple[str, str, str, str] | None = None
_VIRTUAL_CUTSCENES: list[str] = []
_CUTSCENE_CACHE_KEY: tuple[str, str, str] | None = None

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
    return addon_package_name(__package__)


def _preferences(context):
    addon = context.preferences.addons.get(_addon_package_name())
    return addon.preferences if addon else None


def _validate_paths(game_root: str, oodle_dll: str, usmap_path: str) -> None:
    if not game_root or not os.path.isdir(game_root):
        raise FileNotFoundError("Set a valid FINAL FANTASY VII REBIRTH install folder.")
    if oodle_dll and not os.path.isfile(oodle_dll):
        raise FileNotFoundError("The configured Oodle DLL does not exist.")
    if usmap_path and not os.path.isfile(usmap_path):
        raise FileNotFoundError("The configured Rebirth .usmap file does not exist.")


def refresh_umap_index(game_root: str, oodle_dll: str, usmap_path: str, *, force=False) -> list[str]:
    global _VIRTUAL_UMAPS, _CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    cache_key = _package_config_key(game_root, oodle_dll, usmap_path)
    if force or cache_key != _CACHE_KEY:
        result = _run_gargoyle(
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
        result = _run_gargoyle(
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
        result = _run_gargoyle(
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


_mesh_asset_index = MeshAssetIndex()
_animation_asset_index = AnimationAssetIndex()


def refresh_mesh_indices(game_root, oodle_dll, usmap_path, *, force=False):
    """Rebirth's Model-folder policy on the shared package index."""
    global _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES, _MESH_CACHE_KEY, _MESH_CACHE_SOURCE
    _validate_paths(game_root, oodle_dll, usmap_path)
    meshes = _mesh_asset_index.refresh(
        GamePaths(game_root, oodle_dll, usmap_path), REBIRTH_PROFILE,
        path_filter="/Model/", force=force,
    )
    _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES = meshes
    _MESH_CACHE_KEY, _MESH_CACHE_SOURCE = _mesh_asset_index.cache_key, _mesh_asset_index.source
    return meshes


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


def refresh_animation_index(game_root, oodle_dll, usmap_path, skeleton_asset_path, *,
                            force=False, profile=REBIRTH_PROFILE, aes_key="", include_unlinked=False):
    """FF7 character-family search policy on the shared compatible-clip index."""
    global _VIRTUAL_ANIMATIONS, _ANIMATION_CACHE_KEY
    _validate_paths(game_root, oodle_dll, usmap_path)
    skeleton_asset_path = skeleton_asset_path.replace("\\", "/").lstrip("/")
    family = re.sub(r"_Skeleton$", "", Path(skeleton_asset_path).stem, flags=re.IGNORECASE)
    object_id = family.split("_", 1)[0]
    token = f"{object_id}_" if len(object_id) == 6 else family
    _VIRTUAL_ANIMATIONS = _animation_asset_index.refresh(
        GamePaths(game_root, oodle_dll, usmap_path, aes_key), profile,
        skeleton_asset_path, search_token=token, include_unlinked=include_unlinked, force=force,
    )
    _ANIMATION_CACHE_KEY = _animation_asset_index.cache_key
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
        result = _run_gargoyle(game_root, oodle_dll, usmap_path, path_filter="/Cut/Game/")
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


map_import.configure_package_adapters(
    bind_skeletal_mesh_object=bind_skeletal_mesh_object,
    initialize_external_emissive_context=rmi_surface.initialize_external_emissive_context,
)


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
         if str(action.get("sqex_animation_virtual_path", "")).casefold() == normalized),
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
    bone hierarchy.  That operator opens its own short-lived gargoyle process; the
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

    # Cancel the owner's actual socket display correction. Source-axis rigs
    # need no correction, while older saved rigs retain their original basis.
    from .animations import _display_corrections_for_armature
    prop_obj.rotation_mode = 'XYZ'
    prop_obj.rotation_euler = _display_corrections_for_armature(owner)[1].to_euler('XYZ')
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
                or (existing_action.get("sqex_skeleton_asset_path") if existing_action else "")
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
            # gargoyle cannot decode yet.  The actor is still worth having at its
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


class FF7R_REBIRTH_OT_import_cutscene_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_cutscene_game_packages"
    bl_label = "Cutscene from Rebirth Packages"
    bl_description = strings.REBIRTH_CUTSCENE_DESCRIPTION
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Cutscene Path",
        description=strings.REBIRTH_CUTSCENE_VIRTUAL_PATH,
    )
    cutscene_search_text: bpy.props.StringProperty(
        name="Search",
        description=strings.REBIRTH_CUTSCENE_CUTSCENE_SEARCH_TEXT,
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
        description=strings.REBIRTH_CUTSCENE_ALWAYS_CAST_SHADOWS,
        default=False,
    )
    import_cameras: bpy.props.BoolProperty(name="Import Cameras", default=True)
    import_characters: bpy.props.BoolProperty(name="Import Characters", default=True)

    _persisted_props = ("import_cameras", "import_lights", "import_characters", "always_cast_shadows")

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        try:
            refresh_cutscene_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            report(self, {'ERROR'}, f"Package cutscene index failed: {exc}")
            return {'CANCELLED'}
        self.cutscene_search_text = ""
        self._load_last_import_settings(context)
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
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        root = self.virtual_path.strip().replace("\\", "/").lstrip("/")
        if root.lower().endswith(".uasset"):
            root = root[:-7]
        if root.casefold().endswith("_camera"):
            root = root[:-7]
        if not root:
            report(self, {'ERROR'}, "Enter a cutscene root or _Camera package path.")
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
            oodle_dll = bpy.path.abspath(prefs.oodle_dll)
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
                                light_texture_loader=session,
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
                    light_texture_loader=session,
                )
                if self.import_characters:
                    attached_props = _apply_cutscene_prop_attachment_events(
                        context, decoded.get("attachment_events"))
                    if attached_props:
                        print(f"[FF7R Cutscene] Applied {attached_props} timed prop attachment(s).")
        except Exception as exc:
            print(f"[FF7R Cutscene] Import failed for '{root}':")
            traceback.print_exc()
            report(self, {'ERROR'}, f"Package cutscene import failed: {exc}")
            return {'CANCELLED'}
        adopted = _adopt_new_scene_collections(scene, cutscene_collection, known_collections)
        object_count = len(cutscene_collection.all_objects)
        report(self,
            {'INFO'},
            f"Imported package cutscene '{cutscene_name}' into collection "
            f"'{cutscene_collection.name}' ({object_count} object(s)"
            + (f", {adopted} level collection(s)" if adopted else "") + ").",
        )
        self._save_last_import_settings(context)
        return {'FINISHED'}


def _mesh_import_defaults(operator, context):
    prefs = _preferences(context)
    if prefs is None:
        raise RuntimeError("FF7R Rebirth add-on preferences are unavailable.")
    operator.offset_opposite_faces = OFFSET_FACES_BAKED if prefs.offset_mec_opposite_faces else OFFSET_FACES_NONE


def _mesh_import_browser(operator, context, *, refresh=False):
    if refresh:
        prefs = _preferences(context)
        refresh_mesh_indices(bpy.path.abspath(prefs.rebirth_install_root),
                             bpy.path.abspath(prefs.oodle_dll), bpy.path.abspath(prefs.rebirth_usmap_path))
    skeletal = operator.mesh_kind == "SKELETAL"
    return MeshBrowserState(
        _SKELETAL_MESH_BROWSER if skeletal else _STATIC_MESH_BROWSER,
        _VIRTUAL_SKELETAL_MESHES if skeletal else _VIRTUAL_STATIC_MESHES,
        key=_MESH_CACHE_KEY, source=_MESH_CACHE_SOURCE or "memory",
    )


def _execute_static_meshes(self, context):
    prefs = _preferences(context)
    if prefs is None:
        report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
        return {'CANCELLED'}
    try:
        game_root = bpy.path.abspath(prefs.rebirth_install_root)
        oodle_dll = bpy.path.abspath(prefs.oodle_dll)
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
        report(self, {'ERROR'}, f"Package StaticMesh import failed: {exc}")
        return {'CANCELLED'}
    report(self,
        {'INFO'},
        f"Imported {len(virtual_paths):,} Rebirth StaticMesh asset(s): "
        f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
        f"{material_count:,} material slots",
    )
    return {'FINISHED'}


def _execute_skeletal_meshes(self, context):
    prefs = _preferences(context)
    if prefs is None:
        report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
        return {'CANCELLED'}
    binding_armature = (
        context.active_object
        if self.bind_active_armature and not self.build_skeleton
        else None
    )
    if self.bind_active_armature and not self.build_skeleton and (
        binding_armature is None or binding_armature.type != 'ARMATURE'
    ):
        report(self, {'ERROR'}, "Select the matching armature before importing, or disable Bind Active Armature.")
        return {'CANCELLED'}
    try:
        game_root = bpy.path.abspath(prefs.rebirth_install_root)
        oodle_dll = bpy.path.abspath(prefs.oodle_dll)
        usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
        _static_meshes, skeletal_meshes = refresh_mesh_indices(game_root, oodle_dll, usmap_path)
        _SKELETAL_MESH_BROWSER["paths"] = list(skeletal_meshes)
        virtual_paths = package_browser.resolve_paths(
            context, _SKELETAL_MESH_BROWSER, self.virtual_path
        )
        if not virtual_paths:
            raise ValueError("Select at least one SkeletalMesh in the package browser.")
        vertex_count = triangle_count = weighted_count = influence_total = 0
        material_count = bound_count = bonamik_asset_count = 0
        # The import has to happen inside the session: building RMI
        # materials reads the material instance and streams its textures
        # back over the same gargoyle process, which must remain open.
        with PackageAssetSession(game_root, oodle_dll, usmap_path) as session:
            for virtual_path in virtual_paths:
                armature_obj = binding_armature
                skeletal_mesh = session.skeletal_mesh(virtual_path)
                # Read the exact Bonamik association while this package
                # session is alive.  The parsed data is embedded after the
                # mesh exists; no physics is created or evaluated here.
                bonamik_assets = _load_skeletal_mesh_bnm_assets(
                    session, skeletal_mesh
                )
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
                        connect_bones=self.connect_bones,
                        setup_naive_ik=self.setup_naive_ik,
                        create_limbal_bone=self.create_limbal_bone,
                        generate_mouth_controls=self.generate_mouth_controls,
                        create_variant_bone_collections=self.create_variant_bone_collections,
                        import_mesh_referenced_bones_only=(
                            self.import_mesh_referenced_bones_only
                        ),
                        referenced_bone_names_json=json.dumps(
                            skeletal_mesh.get("boneNames") or []
                        ),
                        face_y_forward=self.face_y_forward,
                        preserve_ue_axis_order=self.preserve_ue_axis_order,
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
                if bonamik_assets:
                    try:
                        bnm_storage.store_bnm_assets(
                            armature_obj or obj,
                            bonamik_assets,
                            source_mesh_path=virtual_path,
                        )
                        bonamik_asset_count += len(bonamik_assets)
                    except Exception as exc:
                        print(
                            f"  Warning: associated BNM data for '{virtual_path}' "
                            f"could not be stored: {exc}"
                        )
    except Exception as exc:
        report(self, {'ERROR'}, f"Package SkeletalMesh import failed: {exc}")
        return {'CANCELLED'}
    report(self,
        {'INFO'},
        f"Imported {len(virtual_paths):,} Rebirth SkeletalMesh asset(s): "
        f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
        f"{weighted_count:,} weighted vertices, {influence_total:,} influences, "
        f"{material_count:,} material slots, {bound_count:,} bound"
        + (
            f", {bonamik_asset_count:,} Bonamik data asset(s) recorded"
            if bonamik_asset_count else ""
        ),
    )
    return {'FINISHED'}


FF7R_REBIRTH_OT_import_static_mesh_game_packages = make_package_mesh_importer(
    class_name="FF7R_REBIRTH_OT_import_static_mesh_game_packages",
    bl_idname="import_scene.ff7r_rebirth_static_mesh_game_packages", module_name=__name__, mesh_kind="STATIC",
    default_virtual_path=DEFAULT_STATIC_MESH_PATH, description=strings.REBIRTH_STATIC_MESH_DESCRIPTION,
    source=PackageMeshSource(
        "Rebirth", _mesh_import_browser, _execute_static_meshes, defaults=_mesh_import_defaults,
        property_defaults={"offset_opposite_faces": OFFSET_FACES_BAKED},
        material_summary="Supports updated flattened meshes and earlier conventional layouts."),
)
FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages = make_package_mesh_importer(
    class_name="FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages",
    bl_idname="import_scene.ff7r_rebirth_skeletal_mesh_game_packages", module_name=__name__, mesh_kind="SKELETAL",
    description=strings.REBIRTH_SKELETAL_MESH_DESCRIPTION,
    source=PackageMeshSource(
        "Rebirth", _mesh_import_browser, _execute_skeletal_meshes, defaults=_mesh_import_defaults,
        game_options=SKELETAL_OPTION_NAMES,
        property_defaults={"offset_opposite_faces": OFFSET_FACES_BAKED},
        material_summary="Imports Coordinate0-Coordinate3, skin weights, and RMI_Surface materials."),
)


class FF7R_REBIRTH_OT_import_nearby_mec_terrain(SQEX_LoggedOperator):
    """Bring in only the coarse MEC culling groups near one Blender position."""

    bl_idname = "import_scene.ff7r_rebirth_nearby_mec_terrain"
    bl_label = "Experimental Nearby MEC Terrain"
    bl_description = (
        strings.REBIRTH_NEARBY_MEC_TERRAIN_DESCRIPTION
    )
    bl_options = {'REGISTER', 'UNDO'}

    continent: bpy.props.EnumProperty(
        name="Continent",
        description=strings.REBIRTH_NEARBY_MEC_TERRAIN_CONTINENT,
        items=tuple(
            (key, config["label"], f"Use {config['label']} world origin")
            for key, config in MEC_CONTINENTS.items()
        ),
        default="WEST",
    )
    location: bpy.props.FloatVectorProperty(
        name="Continent-local Blender location",
        description=(
            strings.REBIRTH_NEARBY_MEC_TERRAIN_LOCATION
        ),
        size=3,
        subtype='TRANSLATION',
        default=(0.0, 0.0, 0.0),
    )
    place_in_world_space: bpy.props.BoolProperty(
        name="Place at continent world origin",
        description=(
            strings.REBIRTH_NEARBY_MEC_TERRAIN_PLACE_IN_WORLD_SPACE
        ),
        default=False,
    )
    view_distance: bpy.props.FloatProperty(
        name="View distance",
        description=(
            strings.REBIRTH_NEARBY_MEC_TERRAIN_VIEW_DISTANCE
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
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
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
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}

        game_root = bpy.path.abspath(prefs.rebirth_install_root)
        oodle_dll = bpy.path.abspath(prefs.oodle_dll)
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
                            # visit many maps. Periodically trim the gargoyle's
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
            report(self, {'ERROR'}, f"Nearby MEC terrain import failed: {exc}")
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()

        if not nearby_collection.children:
            bpy.data.collections.remove(nearby_collection)
            detail = f" First failure: {failures[0][1]}" if failures else ""
            report(self,
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
        report(self, {'INFO'}, message)
        return {'FINISHED'}


def _package_umap_defaults(operator, context):
    prefs = _preferences(context)
    if prefs is None:
        raise RuntimeError("FF7R Rebirth add-on preferences are unavailable.")
    operator.offset_opposite_faces = prefs.offset_mec_opposite_faces
    operator.scale_factor = prefs.map_scale_factor


def _package_umap_browser(operator, context, *, refresh=False):
    if refresh:
        prefs = _preferences(context)
        refresh_umap_index(
            bpy.path.abspath(prefs.rebirth_install_root),
            bpy.path.abspath(prefs.oodle_dll),
            bpy.path.abspath(prefs.rebirth_usmap_path),
        )
    return MapBrowserState(_UMAP_BROWSER, _VIRTUAL_UMAPS, key=(_CACHE_KEY, len(_VIRTUAL_UMAPS)))


def _execute_package_umaps(self, context):
    prefs = _preferences(context)
    game_root = bpy.path.abspath(prefs.rebirth_install_root)
    oodle_dll = bpy.path.abspath(prefs.oodle_dll)
    usmap_path = bpy.path.abspath(prefs.rebirth_usmap_path)
    if not _VIRTUAL_UMAPS:
        refresh_umap_index(game_root, oodle_dll, usmap_path)
    _UMAP_BROWSER["paths"] = list(_VIRTUAL_UMAPS)
    virtual_paths = package_browser.resolve_paths(
        context, _UMAP_BROWSER, self.virtual_path
    )
    if not virtual_paths:
        report(self, {'ERROR'}, "Highlight or select at least one UMAP from the package browser.")
        return {'CANCELLED'}
    queue = StreamingMapQueue(virtual_paths, _VIRTUAL_UMAPS, content_root="End/Content")
    virtual_paths = queue.paths
    exposure_mult = 2.0 ** self.exposure

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
            package_session = PackageAssetSession(game_root, oodle_dll, usmap_path, import_textures=self.import_textures, **texture_options(self))
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
                            if self.import_models:
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
                            if self.import_models or self.import_splines or (self.import_lights and (self.import_point_lights or self.import_spot_lights or self.import_rect_lights or self.import_directional_lights)) or self.import_light_probes or self.recursive_import:
                                try:
                                    import_names, actor_payload = package_session.umap_data(virtual_path)
                                except Exception as actor_read_error:
                                    # Actor parsing is newer and less universal than
                                    # MEC; retain the established MEC import path.
                                    import_names = package_session.import_names(virtual_path) if self.import_models else []
                                    failures.append((f"{virtual_path} [actor data]", str(actor_read_error)))
                                    print(f"Package actor data read failed: {virtual_path}: {actor_read_error}")
                            else:
                                import_names = package_session.import_names(virtual_path) if self.import_models else []
                            try:
                                # Check package pressure before Blender's geometry
                                # build, retaining small useful dependency caches
                                # while the bridge stays within its memory budget.
                                package_session.release_batch_memory()
                            except Exception as cleanup_error:
                                # Cleanup is an optimization; it must never discard
                                # an otherwise successful map import.
                                print(f"Package bridge cleanup failed: {cleanup_error}")
                            normalized_local = os.path.normcase(os.path.realpath(local_umap))
                            if self.import_models:
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
                            if (self.import_models or self.import_splines or self.import_lights or self.import_light_probes) and actor_data:
                                try:
                                    actor_created, actor_missing = map_import.import_map_entries(
                                        actor_data,
                                        virtual_path,
                                        exposure_mult=exposure_mult,
                                        attenuation_radius_mult=self.attenuation_radius_mult,
                                        location_scale=self.scale_factor,
                                        always_cast_shadows=self.always_cast_shadows,
                                        static_mesh_resolver=static_mesh_resolver,
                                        skeletal_mesh_resolver=skeletal_mesh_resolver,
                                        import_models=self.import_models,
                                        import_lights=self.import_lights,
                                        import_point_lights=self.import_point_lights,
                                        import_spot_lights=self.import_spot_lights,
                                        import_rect_lights=self.import_rect_lights,
                                        import_directional_lights=self.import_directional_lights,
                                        import_splines=self.import_splines,
                                        bake_light_parameters=self.bake_light_parameters,
                                        import_reflection_probes=self.import_light_probes,
                                        light_texture_loader=package_session,
                                        **landscape_options(self),
                                    )
                                    actor_created_total += actor_created
                                    actor_missing_total |= actor_missing
                                except Exception as actor_error:
                                    failures.append((f"{virtual_path} [actors]", str(actor_error)))
                                    print(f"Package actor import failed: {virtual_path}: {actor_error}")

                            if self.recursive_import:
                                queue.extend(actor_data)
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
        report(self, {'ERROR'}, f"Package import failed: {exc}")
        return {'CANCELLED'}
    finally:
        window_manager.progress_end()

    if not processed_total and not actor_created_total:
        detail = f" First failure: {failures[0][1]}" if failures else ""
        report(self, {'WARNING'}, f"No selected UMAP produced importable geometry or actors.{detail}")
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
    report(self, {'INFO'}, message)
    return {'FINISHED'}


FF7R_REBIRTH_OT_import_mec_game_packages = make_package_map_importer(
    class_name="FF7R_REBIRTH_OT_import_mec_game_packages",
    bl_idname="import_scene.ff7r_rebirth_mec_game_packages",
    module_name=__name__,
    source=PackageMapSource("Rebirth", _package_umap_browser, _execute_package_umaps,
                            defaults=_package_umap_defaults),
    massive_environment=True,
    offset_faces_default=True,
    light_probes_default=False,
)


class FF7R_REBIRTH_OT_import_kdi_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_kdi_game_packages"
    bl_label = "KineDriver JSON from Rebirth Packages"
    bl_description = strings.REBIRTH_KDI_DESCRIPTION
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Package KDI",
        description=strings.REBIRTH_KDI_VIRTUAL_PATH,
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
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        armature = context.active_object
        if armature and armature.type == "ARMATURE":
            package_profile = armature.get(KDI_COORDINATE_PROFILE_PROPERTY)
            axis_order = coordinate_profile_axis_order(package_profile or COORDINATE_PROFILE_REFERENCE)
            self.translation_axis_order = axis_order
            self.scale_axis_order = axis_order
        self._load_last_import_settings(context)
        try:
            paths = refresh_kdi_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            report(self, {'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not paths:
            report(self, {'WARNING'}, "No _KDI assets were found in the mounted game packages.")
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
                bpy.path.abspath(prefs.oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        if virtual_path not in _VIRTUAL_KDIS:
            report(self, {'ERROR'}, "Choose a KDI path from the package search results.")
            return {'CANCELLED'}

        try:
            with tempfile.TemporaryDirectory(prefix="sqex_kdi_") as temp_dir:
                session = PackageAssetSession(
                    bpy.path.abspath(prefs.rebirth_install_root),
                    bpy.path.abspath(prefs.oodle_dll),
                    bpy.path.abspath(prefs.rebirth_usmap_path),
                )
                with session:
                    kdi_asset = session.kdi_asset(virtual_path)
                kdi_path = os.path.join(temp_dir, os.path.basename(virtual_path) + ".json")
                with open(kdi_path, "w", encoding="utf-8") as stream:
                    json.dump([kdi_asset], stream, ensure_ascii=False, indent=2)
                result = bpy.ops.import_scene.sqex_kinedriver_json(
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
            report(self, {'ERROR'}, f"Package KDI import failed: {exc}")
            return {'CANCELLED'}
        if result != {'FINISHED'}:
            report(self, {'ERROR'}, "The KDI driver generator could not complete.")
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        report(self, {'INFO'}, f"Imported KDI drivers from {virtual_path}")
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


def _skeletal_mesh_bnm_paths(skeletal_mesh: dict) -> tuple[str, ...]:
    """Return the exact Bonamik assets authored for this mesh variant.

    BNM follows the mesh's AssetUserData association, rather than the shared
    Skeleton naming convention.  Keep this beside the KDI resolver because the
    two lists are siblings in ``SQEX_KBD_AssetUserData``.
    """
    return bnm_parser.associated_bnm_paths(skeletal_mesh)


def _load_skeletal_mesh_bnm_assets(
        session: PackageAssetSession,
        skeletal_mesh: dict,
) -> list[tuple[str, bnm_parser.BonamikAsset]]:
    """Read and validate BNM data without turning it into Blender physics.

    This is deliberately best-effort.  A new or partially mapped Bonamik
    record must not prevent its render mesh from importing; it is reported to
    the console and can be investigated with the gargoyle's standalone ``bnm``
    action.
    """
    assets: list[tuple[str, bnm_parser.BonamikAsset]] = []
    for bnm_path in _skeletal_mesh_bnm_paths(skeletal_mesh):
        try:
            asset = bnm_parser.parse_bnm(
                session.bnm_asset(bnm_path, report_errors=False)
            )
            assets.append((bnm_path, asset))
        except Exception as exc:
            print(f"  Warning: associated BNM '{bnm_path}' could not be read: {exc}")
    return assets


def _import_secondary_kdi_passes(
        secondary_assets: list[tuple[str, dict]],
        temp_dir: str,
) -> str:
    """Stack a character's secondary KDI passes onto the main layer.

    Takes assets already fetched from the gargoyle rather than a live session:
    drivers are built after the session block has closed, so anything read
    lazily here would find the gargoyle gone.

    Each is imported additively, so a pass that re-drives a channel the main
    layer already owns has that channel skipped rather than clobbering it. A
    failure here only shortens the report -- it must never fail the import,
    since the skeleton and the main KDI layer are already in place.
    """
    armature = bpy.context.active_object
    preserve_ue_axis_order = bool(
        armature
        and armature.type == "ARMATURE"
        and armature.get(AXIS_ORDER_PROPERTY) == AXIS_ORDER_UNREAL
    )
    coordinate_profile = (
        COORDINATE_PROFILE_REFERENCE
        if preserve_ue_axis_order
        else COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
    )
    if armature and armature.type == "ARMATURE":
        coordinate_profile = armature.get(KDI_COORDINATE_PROFILE_PROPERTY, coordinate_profile)
    axis_order = coordinate_profile_axis_order(coordinate_profile)
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
            result = bpy.ops.import_scene.sqex_kinedriver_json(
                filepath=path,
                replace_previous_generated=False,
                additive=True,
                translation_axis_order=axis_order,
                scale_axis_order=axis_order,
                coordinate_profile=coordinate_profile,
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
    return _restrict_skeleton_to_referenced_bones(
        skeleton_asset, referenced_bones
    )


class FF7R_REBIRTH_OT_import_skeleton_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_skeleton_game_packages"
    bl_label = "Skeleton from Rebirth Packages"
    bl_description = strings.REBIRTH_SKELETON_DESCRIPTION
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Package Skeleton",
        description=strings.REBIRTH_KDI_VIRTUAL_PATH,
        search=_search_virtual_skeletons,
        search_options={'SORT'},
    )
    armature_name: bpy.props.StringProperty(
        name="Armature Name",
        description=strings.REBIRTH_SKELETON_ARMATURE_NAME,
        default="",
    )
    scale_factor: bpy.props.FloatProperty(name="Scale", default=0.01, min=0.0001, max=100.0)
    connect_bones: bpy.props.BoolProperty(
        name="Connect bones to parent",
        description=(
            strings.REBIRTH_SKELETAL_MESH_CONNECT_BONES
        ),
        default=False,
    )
    attachment_sockets: bpy.props.EnumProperty(
        name="Attachment Sockets",
        description=strings.REBIRTH_SKELETAL_MESH_ATTACHMENT_SOCKETS,
        items=ATTACHMENT_SOCKETS_ITEMS,
        default=ATTACHMENT_SOCKETS_EMPTIES,
    )
    setup_naive_ik: bpy.props.BoolProperty(
        name="Create limb IK controls",
        description=(
            strings.REBIRTH_SKELETAL_MESH_SETUP_NAIVE_IK
        ),
        default=False,
    )
    create_limbal_bone: bpy.props.BoolProperty(
        name="Create C_Limbal eye controller",
        description=(
            strings.REBIRTH_SKELETON_CREATE_LIMBAL_BONE
        ),
        default=False,
    )
    generate_mouth_controls: bpy.props.BoolProperty(
        name="Generate Mouth Controls (experimental)",
        description=(
            strings.REBIRTH_SKELETAL_MESH_GENERATE_MOUTH_CONTROLS
        ),
        default=False,
    )
    import_secondary_kdi: bpy.props.BoolProperty(
        name="Also import secondary KDI passes",
        description=(
            strings.REBIRTH_SKELETON_IMPORT_SECONDARY_KDI
        ),
        default=True,
    )
    import_kdi: bpy.props.BoolProperty(
        name="Import associated KDI",
        description=(
            strings.REBIRTH_SKELETON_IMPORT_KDI
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
            strings.REBIRTH_SKELETON_KDI_VIRTUAL_PATH_OVERRIDE
        ),
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    referenced_bone_names_json: bpy.props.StringProperty(
        name="Mesh ReferenceSkeleton Bones",
        description=strings.REBIRTH_SKELETON_REFERENCED_BONE_NAMES_JSON,
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    create_variant_bone_collections: bpy.props.BoolProperty(
        name="Create variant bone collections",
        description=(
            strings.REBIRTH_SKELETAL_MESH_CREATE_VARIANT_BONE_COLLECTIONS
        ),
        default=True,
    )
    import_mesh_referenced_bones_only: bpy.props.BoolProperty(
        name="Only import bones used by meshes in this folder",
        description=(
            strings.REBIRTH_SKELETON_IMPORT_MESH_REFERENCED_BONES_ONLY
        ),
        default=False,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward",
        description=strings.REBIRTH_SKELETON_FACE_Y_FORWARD,
        items=FACE_FORWARD_ITEMS,
        default=FACE_FORWARD_UNREAL,
    )
    preserve_ue_axis_order: bpy.props.BoolProperty(
        name="Keep original UE axis ordering",
        description=strings.REBIRTH_SKELETON_PRESERVE_UE_AXIS_ORDER,
        default=False,
    )

    _persisted_props = (
        "scale_factor",
        "connect_bones",
        "attachment_sockets",
        "setup_naive_ik",
        "create_limbal_bone",
        "generate_mouth_controls",
        "create_variant_bone_collections",
        "import_mesh_referenced_bones_only",
        "face_y_forward",
        "preserve_ue_axis_order",
    )

    def invoke(self, context, _event):
        prefs = _preferences(context)
        if prefs is None:
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        self._load_last_import_settings(context)
        try:
            paths = refresh_skeleton_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        except Exception as exc:
            report(self, {'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not paths:
            report(self, {'WARNING'}, "No _Skeleton assets were found in the mounted game packages.")
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
        layout.prop(self, "generate_mouth_controls")
        layout.prop(self, "create_variant_bone_collections")
        layout.prop(self, "import_mesh_referenced_bones_only")
        layout.prop(self, "face_y_forward")
        layout.prop(self, "preserve_ue_axis_order")

    def execute(self, context):
        prefs = _preferences(context)
        virtual_path = self.virtual_path.strip().replace("\\", "/")
        if not _VIRTUAL_SKELETONS:
            refresh_skeleton_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            )
        if virtual_path not in _VIRTUAL_SKELETONS:
            report(self, {'ERROR'}, "Choose a Skeleton path from the package search results.")
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
                        bpy.path.abspath(prefs.oodle_dll),
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
                    bpy.path.abspath(prefs.oodle_dll),
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
                        # built after this block, by which point the gargoyle
                        # session has already been torn down.
                        for secondary_path in secondary_kdi_paths:
                            try:
                                secondary_kdi_assets.append(
                                    (secondary_path, session.kdi_asset(secondary_path))
                                )
                            except Exception as exc:
                                print(f"  Warning: secondary KDI '{secondary_path}' could not be fetched: {exc}")
                    referenced_bone_names = set()
                    if self.referenced_bone_names_json.strip():
                        try:
                            decoded_bone_names = json.loads(
                                self.referenced_bone_names_json
                            )
                        except (TypeError, ValueError) as exc:
                            raise RuntimeError(
                                "The SkeletalMesh ReferenceSkeleton bone list is invalid."
                            ) from exc
                        if not isinstance(decoded_bone_names, list):
                            raise RuntimeError(
                                "The SkeletalMesh ReferenceSkeleton bone list is invalid."
                            )
                        referenced_bone_names = {
                            name for name in decoded_bone_names
                            if isinstance(name, str) and name
                        }
                    family_search_path = _character_family_search_path(virtual_path)
                    needs_variant_usage = (
                        (
                            self.create_variant_bone_collections
                            and not self.import_mesh_referenced_bones_only
                        )
                        or (
                            self.import_mesh_referenced_bones_only
                            and not referenced_bone_names
                        )
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
                    if referenced_bone_names:
                        skeleton_asset, referenced_count, retained_count = (
                            _restrict_skeleton_to_referenced_bones(
                                skeleton_asset, referenced_bone_names
                            )
                        )
                    else:
                        if not variant_bone_usage:
                            raise RuntimeError(
                                "Mesh bone usage is unavailable; cannot make a reduced skeleton."
                            )
                        skeleton_asset, referenced_count, retained_count = (
                            _restrict_skeleton_to_folder_mesh_bones(
                                skeleton_asset, variant_bone_usage, virtual_path
                            )
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
                    _bones_from_gargoyle(skeleton_asset),
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
                    preserve_ue_axis_order=self.preserve_ue_axis_order,
                )
                armature_obj[SKELETON_ASSET_PATH_PROPERTY] = virtual_path
                armature_obj[KDI_COORDINATE_PROFILE_PROPERTY] = (
                    COORDINATE_PROFILE_SOURCE_AXES
                    if self.preserve_ue_axis_order
                    else COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                )

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
                        kdi_result = bpy.ops.import_scene.sqex_kinedriver_json(
                            filepath=kdi_path,
                            replace_previous_generated=True,
                            translation_axis_order=(
                                "XYZ" if self.preserve_ue_axis_order else "YZX"
                            ),
                            scale_axis_order=(
                                "XYZ" if self.preserve_ue_axis_order else "YZX"
                            ),
                            coordinate_profile=(
                                COORDINATE_PROFILE_SOURCE_AXES
                                if self.preserve_ue_axis_order
                                else COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                            ),
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
                # Build after all KDI passes, and isolate an unsupported facial
                # profile from the otherwise successful skeleton/mesh import.
                mouth_note = ""
                if self.generate_mouth_controls:
                    try:
                        mouth_count = generate_mouth_rig(context, armature_obj)
                        mouth_note = f"; added jaw control for {mouth_count} mouth bones"
                        if armature_obj.get("sqex_lip_rig"):
                            mouth_note += " and 8 smooth lip handles"
                    except Exception as exc:
                        mouth_note = "; mouth controls skipped"
                        report(self, {'WARNING'}, f"Mouth controls skipped: {exc}")
        except Exception as exc:
            report(self, {'ERROR'}, f"Package Skeleton import failed: {exc}")
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        report(self, {'INFO'}, f"Imported skeleton as '{armature_obj.name}'{reduced_bone_note}{collection_note}{kdi_note}{mouth_note}")
        return {'FINISHED'}


CLASSES = (
    FF7R_PG_mesh_search_entry,
    FF7R_UL_mesh_search_results,
    FF7R_PG_cutscene_search_entry,
    FF7R_UL_cutscene_search_results,
    FF7R_REBIRTH_OT_import_static_mesh_game_packages,
    FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages,
    FF7R_REBIRTH_OT_import_cutscene_game_packages,
    FF7R_REBIRTH_OT_import_nearby_mec_terrain,
    FF7R_REBIRTH_OT_import_mec_game_packages,
    FF7R_REBIRTH_OT_import_kdi_game_packages,
    FF7R_REBIRTH_OT_import_skeleton_game_packages,
)


def register_runtime_properties() -> None:
    """The shared package browser owns the runtime browser property."""


def unregister_runtime_properties() -> None:
    """Remove the legacy property when reloading over an older add-on build."""
    if hasattr(bpy.types.WindowManager, "ff7r_package_browser"):
        del bpy.types.WindowManager.ff7r_package_browser
