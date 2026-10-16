"""Import conventional UE4.18 StaticMesh packages from Remake Intergrade."""

from __future__ import annotations

from ....language import tooltips

import json
import os
import re
import tempfile

import bpy

from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....core.package_utils import addon_package_name
from ....formats.kdi.drivers import (
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
)
from ..profile import PROFILE
from .. import materials
from ....formats import unreal_package as shared_packages
from ...rebirth.importers import packages as ff7_rigging
from ...conventional_map import make_umap_importer
from ... import conventional_mesh as shared_mesh
from ....ui.mesh_importer import (
    SKELETAL_OPTION_NAMES,
)


_SUPPORTED_SKELETAL_OPTIONS = SKELETAL_OPTION_NAMES - {
    "create_limbal_bone",
    "generate_mouth_controls",
}


DEFAULT_STATIC_MESH_PATH = (
    "End/Content/GameContents/Effect/Character/Player/PC0000_Cloud/Model/"
    "FX_PC0000_Cylinder_01_M.uasset"
)
DEFAULT_SKELETAL_MESH_PATH = ""

_VIRTUAL_KDIS: list[str] = []
_KDI_CACHE_KEY = None
_KDI_ASSET_PATTERN = re.compile(r"_KDI(_[A-Za-z0-9_]+)?\.uasset$", re.IGNORECASE)


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
        raise FileNotFoundError(
            "Set a valid FINAL FANTASY VII REMAKE INTERGRADE install folder."
        )
    if not paths.usmap_path or not os.path.isfile(paths.usmap_path):
        raise FileNotFoundError(
            "Set a valid Remake mapping file. Remake is UE 4.18, but its cooked "
            "packages use unversioned properties and still require mappings."
        )
    if paths.oodle_dll and not os.path.isfile(paths.oodle_dll):
        raise FileNotFoundError("The configured shared Oodle DLL does not exist.")
    return paths


def refresh_kdi_index(context, *, force=False) -> list[str]:
    """Return Remake's package KineDriver assets without mixing game profiles."""
    global _VIRTUAL_KDIS, _KDI_CACHE_KEY
    paths = _configured_paths(context)
    cache_key = shared_packages._package_config_key(
        paths.install_root, paths.oodle_dll, paths.usmap_path
    )
    if force or cache_key != _KDI_CACHE_KEY:
        result = shared_packages._run_gargoyle(
            paths.install_root,
            paths.oodle_dll,
            paths.usmap_path,
            path_filter="_KDI",
            profile=PROFILE,
        )
        _VIRTUAL_KDIS = sorted(
            (
                path
                for path in result.get("files", [])
                if path.lower().endswith(".uasset")
                and _KDI_ASSET_PATTERN.search(os.path.basename(path)) is not None
                and "/autogencollision/" not in path.replace("\\", "/").casefold()
            ),
            key=shared_packages._natural_path_key,
        )
        _KDI_CACHE_KEY = cache_key
    return _VIRTUAL_KDIS


def _search_virtual_kdis(_self, _context, edit_text):
    return shared_packages._search_virtual_paths(
        _VIRTUAL_KDIS,
        edit_text,
        sort_key=shared_packages._natural_path_key,
    )


def _prepare_mesh_batch(context, operator, session, stack):
    available_kdis = []
    if operator.build_skeleton and operator.import_kdi:
        try:
            available_kdis = refresh_kdi_index(context)
        except Exception as exc:
            print(f"  Warning: Remake KDI index could not be loaded: {exc}")
    return {
        "available_kdis": available_kdis,
        "temp_dir": stack.enter_context(
            tempfile.TemporaryDirectory(prefix="ff7r_remake_mesh_")
        ),
    }


def _post_skeleton(
    context,
    operator,
    definition,
    session,
    skeletal_mesh,
    virtual_path,
    armature_obj,
    skeleton_path,
    source_skeleton,
    batch,
):
    available_kdis, temp_dir = batch["available_kdis"], batch["temp_dir"]
    kdi_count = 0
    variant_bone_usage = None
    family_search_path = (
        ff7_rigging._character_family_search_path(skeleton_path)
        if skeleton_path
        else None
    )
    if (
        operator.create_variant_bone_collections
        and not operator.import_mesh_referenced_bones_only
        and family_search_path
    ):
        try:
            variant_bone_usage = session.skeleton_bone_usage(
                skeleton_path, family_search_path
            )
        except Exception as exc:
            print(f"  Warning: variant bone usage could not be read: {exc}")

    if variant_bone_usage:
        shared_packages._create_variant_bone_collections(
            armature_obj, variant_bone_usage
        )

    mesh_kdi_paths = ff7_rigging._skeletal_mesh_kdi_paths(skeletal_mesh)
    kdi_virtual_path = (
        mesh_kdi_paths[0]
        if operator.import_kdi and mesh_kdi_paths
        else (
            ff7_rigging._kdi_path_for_skeleton(skeleton_path)
            if skeleton_path and operator.import_kdi
            else None
        )
    )
    if kdi_virtual_path in available_kdis:
        try:
            kdi_asset = session.kdi_asset(kdi_virtual_path)
            secondary_assets = []
            for secondary_path in ff7_rigging._secondary_kdi_paths_for_main(
                kdi_virtual_path, available_kdis
            ):
                try:
                    secondary_assets.append(
                        (secondary_path, session.kdi_asset(secondary_path))
                    )
                except Exception as exc:
                    print(
                        f"  Warning: secondary KDI '{secondary_path}' "
                        f"could not be fetched: {exc}"
                    )
            if kdi_asset and kdi_asset.get("Properties"):
                for selected in context.selected_objects:
                    selected.select_set(False)
                armature_obj.select_set(True)
                context.view_layer.objects.active = armature_obj
                kdi_path = os.path.join(
                    temp_dir,
                    os.path.basename(kdi_virtual_path) + ".json",
                )
                with open(kdi_path, "w", encoding="utf-8") as stream:
                    json.dump(
                        [kdi_asset],
                        stream,
                        ensure_ascii=False,
                        indent=2,
                    )
                kdi_axis_order = "XZY" if operator.preserve_ue_axis_order else "YZX"
                kdi_coordinate_profile = (
                    shared_packages.COORDINATE_PROFILE_REFERENCE
                    if operator.preserve_ue_axis_order
                    else COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                )
                result = bpy.ops.import_scene.sqex_kinedriver_json(
                    filepath=kdi_path,
                    replace_previous_generated=True,
                    translation_axis_order=kdi_axis_order,
                    scale_axis_order=kdi_axis_order,
                    coordinate_profile=kdi_coordinate_profile,
                )
                if result == {"FINISHED"}:
                    kdi_count += 1
                    if secondary_assets:
                        ff7_rigging._import_secondary_kdi_passes(
                            secondary_assets, temp_dir
                        )
        except Exception as exc:
            print(
                f"  Warning: associated Remake KDI "
                f"'{kdi_virtual_path}' could not be imported: {exc}"
            )

    return kdi_count


DEFINITION = shared_mesh.make_definition(
    PROFILE,
    game_name="Remake",
    initial_directory="End/Content",
    default_virtual_path=DEFAULT_STATIC_MESH_PATH,
    default_skeletal_mesh_path=DEFAULT_SKELETAL_MESH_PATH,
    configured_paths=_configured_paths,
    material_builder=materials.build_material,
    supported_skeletal_options=frozenset(_SUPPORTED_SKELETAL_OPTIONS),
    mesh_path_filter="/Model/",
    prepare_batch=_prepare_mesh_batch,
    post_skeleton=_post_skeleton,
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


FF7R_REMAKE_OT_import_static_mesh_game_packages = shared_mesh.make_static_mesh_importer(
    class_name="FF7R_REMAKE_OT_import_static_mesh_game_packages",
    module_name=__name__,
    bl_idname="import_scene.ff7r_remake_static_mesh_game_packages",
    definition=DEFINITION,
)
FF7R_REMAKE_OT_import_skeletal_mesh_game_packages = (
    shared_mesh.make_skeletal_mesh_importer(
        class_name="FF7R_REMAKE_OT_import_skeletal_mesh_game_packages",
        module_name=__name__,
        bl_idname="import_scene.ff7r_remake_skeletal_mesh_game_packages",
        definition=DEFINITION,
    )
)


class FF7R_REMAKE_OT_import_kdi_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_remake_kdi_game_packages"
    bl_label = "KineDriver from Remake Packages"
    bl_description = (
        tooltips.REMAKE_KDI_DESCRIPTION
    )
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Package KDI",
        description=tooltips.REMAKE_KDI_VIRTUAL_PATH,
        search=_search_virtual_kdis,
        search_options={"SORT"},
    )
    replace_previous_generated: bpy.props.BoolProperty(
        name="Replace previous generated KDI layer",
        default=True,
    )

    _persisted_props = ("replace_previous_generated",)

    def invoke(self, context, _event):
        armature = context.active_object
        if not armature or armature.type != "ARMATURE":
            report(
                self,
                {"ERROR"},
                "Select the imported Remake armature and make it active",
            )
            return {"CANCELLED"}
        try:
            paths = refresh_kdi_index(context)
        except Exception as exc:
            report(self, {"ERROR"}, f"Remake KDI index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            report(
                self,
                {"WARNING"},
                "No Remake _KDI assets were found in the mounted packages.",
            )
            return {"CANCELLED"}
        self._load_last_import_settings(context)
        return context.window_manager.invoke_props_dialog(self, width=850)

    def draw(self, _context):
        layout = self.layout
        layout.label(
            text=f"{len(_VIRTUAL_KDIS):,} Remake KDI assets indexed", icon="PACKAGE"
        )
        layout.prop(self, "virtual_path", icon="VIEWZOOM")
        layout.prop(self, "replace_previous_generated")
        layout.separator()
        layout.label(
            text="Uses Remake's legacy graph and the selected armature's KDI axes."
        )

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != "ARMATURE":
            report(
                self,
                {"ERROR"},
                "Select the imported Remake armature and make it active",
            )
            return {"CANCELLED"}
        try:
            paths = _configured_paths(context)
            virtual_path = self.virtual_path.strip().replace("\\", "/").lstrip("/")
            if virtual_path not in refresh_kdi_index(context):
                raise ValueError(
                    "Choose a KDI asset from the Remake package search results."
                )
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=PROFILE,
            ) as session:
                kdi_asset = session.kdi_asset(virtual_path)
            with tempfile.TemporaryDirectory(prefix="ff7r_remake_kdi_") as temp_dir:
                kdi_path = os.path.join(
                    temp_dir, os.path.basename(virtual_path) + ".json"
                )
                with open(kdi_path, "w", encoding="utf-8") as stream:
                    json.dump([kdi_asset], stream, ensure_ascii=False, indent=2)
                coordinate_profile = armature.get(
                    shared_packages.KDI_COORDINATE_PROFILE_PROPERTY,
                    # Armatures imported by the first Remake KDI implementation
                    # do not have the marker, but were still made by the rolled
                    # package-skeleton builder. Re-importing KDI therefore fixes
                    # existing scenes without requiring a fresh mesh import.
                    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
                )
                axis_order = (
                    "YZX"
                    if coordinate_profile == COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                    else "XZY"
                )
                result = bpy.ops.import_scene.sqex_kinedriver_json(
                    filepath=kdi_path,
                    replace_previous_generated=self.replace_previous_generated,
                    translation_axis_order=axis_order,
                    scale_axis_order=axis_order,
                    coordinate_profile=coordinate_profile,
                )
        except Exception as exc:
            report(self, {"ERROR"}, f"Remake KDI import failed: {exc}")
            return {"CANCELLED"}
        if result != {"FINISHED"}:
            report(
                self, {"ERROR"}, "The Remake KDI driver generator could not complete."
            )
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        report(self, {"INFO"}, f"Imported Remake KDI drivers from {virtual_path}")
        return {"FINISHED"}


FF7R_REMAKE_OT_import_umap_game_packages = make_umap_importer(
    class_name="FF7R_REMAKE_OT_import_umap_game_packages",
    bl_idname="import_scene.ff7r_remake_umap_game_packages",
    game_label="Remake",
    profile=PROFILE,
    configured_paths=_configured_paths,
    material_builder=materials.build_material,
    initial_directory="End/Content/GameContents/Level",
)


CLASSES = (
    FF7R_REMAKE_OT_import_static_mesh_game_packages,
    FF7R_REMAKE_OT_import_skeletal_mesh_game_packages,
    FF7R_REMAKE_OT_import_kdi_game_packages,
    FF7R_REMAKE_OT_import_umap_game_packages,
)
