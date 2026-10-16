"""Import conventional UE4.27 StaticMesh packages from Crisis Core Reunion."""

from __future__ import annotations

import os

import bpy

from ....core.package_utils import addon_package_name
from ..profile import PROFILE
from .. import materials
from ...conventional_map import make_umap_importer
from ... import conventional_mesh as shared_mesh


_SUPPORTED_SKELETAL_OPTIONS = {
    "preserve_ue_axis_order",
    "import_mesh_referenced_bones_only",
}


DEFAULT_STATIC_MESH_PATH = (
    "CCFF7R/Content/Fair/Map/00_Common/Prop/00_Prop/House/Mesh/"
    "S_en_ban2_02_MP_HouseA.uasset"
)
DEFAULT_SKELETAL_MESH_PATH = ""


def _preferences(context):
    addon_name = addon_package_name(__package__)
    addon = context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


def _configured_paths(context):
    preferences = _preferences(context)
    if preferences is None:
        raise RuntimeError("FF7R add-on preferences are unavailable.")
    paths = PROFILE.paths_from_preferences(preferences, bpy.path.abspath)
    if not paths.install_root or not os.path.isdir(paths.install_root):
        raise FileNotFoundError("Set a valid CRISIS CORE REUNION install folder.")
    if not paths.usmap_path or not os.path.isfile(paths.usmap_path):
        raise FileNotFoundError("Set a valid Crisis Core mapping file.")
    if paths.oodle_dll and not os.path.isfile(paths.oodle_dll):
        raise FileNotFoundError("The configured shared Oodle DLL does not exist.")
    return paths


DEFINITION = shared_mesh.make_definition(
    PROFILE,
    game_name="Crisis Core",
    initial_directory="CCFF7R/Content",
    default_virtual_path=DEFAULT_STATIC_MESH_PATH,
    default_skeletal_mesh_path=DEFAULT_SKELETAL_MESH_PATH,
    configured_paths=_configured_paths,
    material_builder=materials.build_material,
    supported_skeletal_options=frozenset(_SUPPORTED_SKELETAL_OPTIONS),
)
_STATIC_MESH_BROWSER = DEFINITION.browser
_SKELETAL_MESH_BROWSER = DEFINITION.skeletal_browser


_LEGACY_INDEX_FIELDS = {
    "_VIRTUAL_STATIC_MESHES": "virtual_static_meshes",
    "_VIRTUAL_SKELETAL_MESHES": "virtual_skeletal_meshes",
    "_MESH_CACHE_KEY": "mesh_cache_key",
    "_MESH_CACHE_SOURCE": "mesh_cache_source",
}
# importlib.reload retains attributes removed from older module source.
for _legacy_index_name in _LEGACY_INDEX_FIELDS:
    globals().pop(_legacy_index_name, None)


def __getattr__(name):
    if name in _LEGACY_INDEX_FIELDS:
        return getattr(DEFINITION, _LEGACY_INDEX_FIELDS[name])
    raise AttributeError(name)


def refresh_static_mesh_index(context, *, force=False):
    return shared_mesh.refresh_static_mesh_index(context, DEFINITION, force=force)


def refresh_skeletal_mesh_index(context, *, force=False):
    return shared_mesh.refresh_skeletal_mesh_index(context, DEFINITION, force=force)


FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages = (
    shared_mesh.make_static_mesh_importer(
        class_name="FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages",
        module_name=__name__,
        bl_idname="import_scene.ff7r_crisis_core_static_mesh_game_packages",
        definition=DEFINITION,
    )
)
FF7R_CRISIS_CORE_OT_import_skeletal_mesh_game_packages = (
    shared_mesh.make_skeletal_mesh_importer(
        class_name="FF7R_CRISIS_CORE_OT_import_skeletal_mesh_game_packages",
        module_name=__name__,
        bl_idname="import_scene.ff7r_crisis_core_skeletal_mesh_game_packages",
        definition=DEFINITION,
    )
)


FF7R_CRISIS_CORE_OT_import_umap_game_packages = make_umap_importer(
    class_name="FF7R_CRISIS_CORE_OT_import_umap_game_packages",
    bl_idname="import_scene.ff7r_crisis_core_umap_game_packages",
    game_label="Crisis Core",
    profile=PROFILE,
    configured_paths=_configured_paths,
    material_builder=materials.build_material,
)


CLASSES = (
    FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages,
    FF7R_CRISIS_CORE_OT_import_skeletal_mesh_game_packages,
    FF7R_CRISIS_CORE_OT_import_umap_game_packages,
)
