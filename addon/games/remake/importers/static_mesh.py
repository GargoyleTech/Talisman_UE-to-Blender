"""Import conventional UE4.18 StaticMesh packages from Remake Intergrade."""

from __future__ import annotations

import json
import os
import re
import tempfile

import bpy

from ....core.blender.reporting import FF7R_LoggedOperator
from ....core.blender.skeletons import _bones_from_bridge, build_armature_from_bones
from ....formats.kdi.drivers import (
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
)
from ..profile import PROFILE
from .. import materials
from ...rebirth.importers import packages as shared_packages
from ...conventional_map import make_umap_importer
from ... import package_browser


DEFAULT_STATIC_MESH_PATH = (
    "End/Content/GameContents/Effect/Character/Player/PC0000_Cloud/Model/"
    "FX_PC0000_Cylinder_01_M.uasset"
)
DEFAULT_SKELETAL_MESH_PATH = ""

_VIRTUAL_STATIC_MESHES: list[str] = []
_VIRTUAL_SKELETAL_MESHES: list[str] = []
_MESH_CACHE_KEY: tuple[str, str, str] | None = None
_MESH_CACHE_SOURCE = ""
_VIRTUAL_KDIS: list[str] = []
_KDI_CACHE_KEY: tuple[str, str, str] | None = None
_KDI_ASSET_PATTERN = re.compile(r"_KDI(_[A-Za-z0-9_]+)?\.uasset$", re.IGNORECASE)
_STATIC_MESH_BROWSER = package_browser.make_state(
    "Remake StaticMesh assets", initial_directory="End/Content", file_icon="MESH_DATA"
)
_SKELETAL_MESH_BROWSER = package_browser.make_state(
    "Remake SkeletalMesh assets", initial_directory="End/Content", file_icon="ARMATURE_DATA"
)


def _preferences(context):
    addon_name = (__package__ or "").split(".", 1)[0]
    addon = context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


def _configured_paths(context):
    preferences = _preferences(context)
    if preferences is None:
        raise RuntimeError("FF7R add-on preferences are unavailable.")
    paths = PROFILE.paths_from_preferences(preferences, bpy.path.abspath)
    if not paths.install_root or not os.path.isdir(paths.install_root):
        raise FileNotFoundError("Set a valid FINAL FANTASY VII REMAKE INTERGRADE install folder.")
    if not paths.usmap_path or not os.path.isfile(paths.usmap_path):
        raise FileNotFoundError(
            "Set a valid Remake mapping file. Remake is UE 4.18, but its cooked "
            "packages use unversioned properties and still require mappings."
        )
    if paths.oodle_dll and not os.path.isfile(paths.oodle_dll):
        raise FileNotFoundError("The configured Remake Oodle DLL does not exist.")
    return paths


def refresh_static_mesh_index(context, *, force=False) -> list[str]:
    """Build and cache Remake's actual conventional mesh package lists."""
    global _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES, _MESH_CACHE_KEY, _MESH_CACHE_SOURCE
    paths = _configured_paths(context)
    cache_key = shared_packages._package_config_key(
        paths.install_root, paths.oodle_dll, paths.usmap_path
    )
    if force or cache_key != _MESH_CACHE_KEY:
        package_signature = shared_packages._mesh_package_signature(
            paths.install_root, profile=PROFILE
        )
        cache_path = shared_packages._mesh_disk_cache_path(cache_key)
        disk_cache = None if force else shared_packages._load_mesh_disk_cache(
            cache_path, cache_key, package_signature
        )
        if disk_cache is not None:
            _VIRTUAL_STATIC_MESHES, _VIRTUAL_SKELETAL_MESHES = disk_cache
            _MESH_CACHE_SOURCE = "disk cache"
        else:
            result = shared_packages._run_bridge_asset_request(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                {"action": "mesh_index", "pathFilter": "/Model/"},
                profile=PROFILE,
            )
            mesh_index = result.get("meshIndex") or {}
            _VIRTUAL_STATIC_MESHES = sorted(
                mesh_index.get("staticMeshes") or [],
                key=shared_packages._natural_path_key,
            )
            _VIRTUAL_SKELETAL_MESHES = sorted(
                mesh_index.get("skeletalMeshes") or [],
                key=shared_packages._natural_path_key,
            )
            failure_count = int(mesh_index.get("failures") or 0)
            if failure_count:
                print(f"Remake mesh index skipped {failure_count:,} unreadable package(s).")
            shared_packages._save_mesh_disk_cache(
                cache_path,
                cache_key,
                package_signature,
                _VIRTUAL_STATIC_MESHES,
                _VIRTUAL_SKELETAL_MESHES,
            )
            _MESH_CACHE_SOURCE = "fresh package scan"
        _MESH_CACHE_KEY = cache_key
    return _VIRTUAL_STATIC_MESHES


def refresh_skeletal_mesh_index(context, *, force=False) -> list[str]:
    """Return Remake's indexed USkeletalMesh package paths."""
    refresh_static_mesh_index(context, force=force)
    return _VIRTUAL_SKELETAL_MESHES


def refresh_kdi_index(context, *, force=False) -> list[str]:
    """Return Remake's package KineDriver assets without mixing game profiles."""
    global _VIRTUAL_KDIS, _KDI_CACHE_KEY
    paths = _configured_paths(context)
    cache_key = shared_packages._package_config_key(
        paths.install_root, paths.oodle_dll, paths.usmap_path
    )
    if force or cache_key != _KDI_CACHE_KEY:
        result = shared_packages._run_bridge(
            paths.install_root,
            paths.oodle_dll,
            paths.usmap_path,
            path_filter="_KDI",
            profile=PROFILE,
        )
        _VIRTUAL_KDIS = sorted(
            (
                path for path in result.get("files", [])
                if path.lower().endswith(".uasset")
                and _KDI_ASSET_PATTERN.search(os.path.basename(path)) is not None
                and "/autogencollision/" not in path.replace("\\", "/").casefold()
            ),
            key=shared_packages._natural_path_key,
        )
        _KDI_CACHE_KEY = cache_key
    return _VIRTUAL_KDIS


def _search_virtual_static_meshes(_self, _context, edit_text):
    return shared_packages._search_virtual_paths(
        _VIRTUAL_STATIC_MESHES,
        edit_text,
        sort_key=shared_packages._natural_path_key,
    )


def _search_virtual_skeletal_meshes(_self, _context, edit_text):
    return shared_packages._search_virtual_paths(
        _VIRTUAL_SKELETAL_MESHES,
        edit_text,
        sort_key=shared_packages._natural_path_key,
    )


def _search_virtual_kdis(_self, _context, edit_text):
    return shared_packages._search_virtual_paths(
        _VIRTUAL_KDIS,
        edit_text,
        sort_key=shared_packages._natural_path_key,
    )


class FF7R_REMAKE_OT_import_static_mesh_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_remake_static_mesh_game_packages"
    bl_label = "Static Mesh from Remake Packages"
    bl_description = "Import a conventional UE4.18 StaticMesh from Remake Intergrade packages"
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Static Mesh Path",
        description="Type any part of an indexed Remake StaticMesh package path",
        default=DEFAULT_STATIC_MESH_PATH,
        search=_search_virtual_static_meshes,
        search_options={"SORT"},
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
        items=shared_packages.OFFSET_FACES_ITEMS,
        default=shared_packages.OFFSET_FACES_NONE,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward",
        description="Choose the imported mesh's forward axis",
        items=shared_packages.FACE_FORWARD_ITEMS,
        default=shared_packages.FACE_FORWARD_UNREAL,
    )

    _persisted_props = ("scale_factor", "offset_opposite_faces", "face_y_forward")

    def invoke(self, context, _event):
        try:
            paths = refresh_static_mesh_index(context)
        except Exception as exc:
            self.report({"ERROR"}, f"Remake StaticMesh index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            self.report({"WARNING"}, "No Remake StaticMesh assets were found under /Model/.")
            return {"CANCELLED"}
        self._load_last_import_settings(context)
        package_browser.activate(context, _STATIC_MESH_BROWSER, paths)
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, _STATIC_MESH_BROWSER)
        layout.prop(self, "scale_factor")
        layout.prop(self, "offset_opposite_faces")
        layout.prop(self, "face_y_forward")
        layout.label(
            text=(
                f"{len(_VIRTUAL_STATIC_MESHES):,} Remake StaticMesh assets indexed "
                f"({_MESH_CACHE_SOURCE or 'memory'})"
            ),
            icon="PACKAGE",
        )
        layout.label(text="Builds basic Remake materials from the available texture parameters.")

    def execute(self, context):
        try:
            paths = _configured_paths(context)
            indexed_paths = refresh_static_mesh_index(context)
            _STATIC_MESH_BROWSER["paths"] = list(indexed_paths)
            virtual_paths = package_browser.resolve_paths(
                context, _STATIC_MESH_BROWSER, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError("Select at least one StaticMesh in the package browser.")
            vertex_count = triangle_count = material_count = 0
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=PROFILE,
            ) as session:
                for virtual_path in virtual_paths:
                    static_mesh = session.static_mesh(virtual_path)
                    obj = shared_packages.import_static_mesh_asset(
                        context,
                        static_mesh,
                        virtual_path,
                        scale_factor=self.scale_factor,
                        offset_opposite_faces=self.offset_opposite_faces,
                        material_session=session,
                        material_builder=materials.build_material,
                        face_y_forward=shared_packages._face_y_forward_enabled(self.face_y_forward),
                    )
                    vertex_count += len(obj.data.vertices)
                    triangle_count += len(obj.data.polygons)
                    material_count += len(obj.data.materials)
        except Exception as exc:
            self.report({"ERROR"}, f"Remake StaticMesh import failed: {exc}")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        self.report(
            {"INFO"},
            f"Imported {len(virtual_paths):,} Remake StaticMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{material_count:,} material slots",
        )
        return {"FINISHED"}


class FF7R_REMAKE_OT_import_skeletal_mesh_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_remake_skeletal_mesh_game_packages"
    bl_label = "Skeletal Mesh from Remake Packages"
    bl_description = "Import a Remake SkeletalMesh and its linked Skeleton"
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Skeletal Mesh Path",
        description="Type any part of an indexed Remake SkeletalMesh package path",
        default=DEFAULT_SKELETAL_MESH_PATH,
        search=_search_virtual_skeletal_meshes,
        search_options={"SORT"},
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
        items=shared_packages.OFFSET_FACES_ITEMS,
        default=shared_packages.OFFSET_FACES_NONE,
    )
    bind_active_armature: bpy.props.BoolProperty(
        name="Bind Active Armature",
        description="Bind matching vertex groups to the active armature instead of creating one",
        default=True,
    )
    build_skeleton: bpy.props.BoolProperty(
        name="Build Skeleton from Package",
        description=(
            "Ignore Bind Active Armature and build a new armature from this mesh's "
            "associated Skeleton asset before importing"
        ),
        default=True,
    )
    attachment_sockets: bpy.props.EnumProperty(
        name="Attachment Sockets",
        description="Choose how attachment sockets are materialized on the generated armature",
        items=shared_packages.ATTACHMENT_SOCKETS_ITEMS,
        default=shared_packages.ATTACHMENT_SOCKETS_EMPTIES,
    )
    import_kdi: bpy.props.BoolProperty(
        name="Also import KDI",
        description=(
            "After building the skeleton, also import its KineDriver rig and "
            "any secondary passes"
        ),
        default=True,
    )
    setup_naive_ik: bpy.props.BoolProperty(
        name="Setup IK (naive)",
        description=(
            "Add simple IK constraints and hinge limits to matching hands, feet, "
            "forearms, and lower legs"
        ),
        default=False,
    )
    create_variant_bone_collections: bpy.props.BoolProperty(
        name="Create variant bone collections",
        description=(
            "For player skeletons, create a collection for each model variant's "
            "uniquely weighted bones"
        ),
        default=True,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward",
        description="Choose the imported mesh and armature's forward axis",
        items=shared_packages.FACE_FORWARD_ITEMS,
        default=shared_packages.FACE_FORWARD_UNREAL,
    )

    _persisted_props = (
        "scale_factor", "offset_opposite_faces", "bind_active_armature",
        "build_skeleton", "attachment_sockets", "import_kdi", "setup_naive_ik",
        "create_variant_bone_collections", "face_y_forward",
    )

    def invoke(self, context, _event):
        try:
            paths = refresh_skeletal_mesh_index(context)
        except Exception as exc:
            self.report({"ERROR"}, f"Remake SkeletalMesh index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            self.report({"WARNING"}, "No Remake SkeletalMesh assets were found under /Model/.")
            return {"CANCELLED"}
        self._load_last_import_settings(context)
        package_browser.activate(context, _SKELETAL_MESH_BROWSER, paths)
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
        variant_row = layout.row()
        variant_row.enabled = self.build_skeleton
        variant_row.prop(self, "create_variant_bone_collections")
        layout.prop(self, "face_y_forward")
        layout.label(
            text=(
                f"{len(_VIRTUAL_SKELETAL_MESHES):,} Remake SkeletalMesh assets indexed "
                f"({_MESH_CACHE_SOURCE or 'memory'})"
            ),
            icon="PACKAGE",
        )
        layout.label(text="Creates an armature from the linked Skeleton and imports skin weights.")

    def execute(self, context):
        binding_armature = (
            context.active_object
            if self.bind_active_armature and not self.build_skeleton
            else None
        )
        if self.bind_active_armature and not self.build_skeleton and (
            binding_armature is None or binding_armature.type != "ARMATURE"
        ):
            self.report(
                {"ERROR"},
                "Select the matching armature, or enable Build Skeleton from Package.",
            )
            return {"CANCELLED"}
        try:
            paths = _configured_paths(context)
            indexed_paths = refresh_skeletal_mesh_index(context)
            _SKELETAL_MESH_BROWSER["paths"] = list(indexed_paths)
            virtual_paths = package_browser.resolve_paths(
                context, _SKELETAL_MESH_BROWSER, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError("Select at least one SkeletalMesh in the package browser.")

            available_kdis: list[str] = []
            if self.build_skeleton and self.import_kdi:
                try:
                    available_kdis = refresh_kdi_index(context)
                except Exception as exc:
                    print(f"  Warning: Remake KDI index could not be loaded: {exc}")

            vertex_count = triangle_count = weighted_count = influence_total = 0
            material_count = bound_count = kdi_count = 0
            with tempfile.TemporaryDirectory(prefix="ff7r_remake_mesh_") as temp_dir:
                with shared_packages.PackageAssetSession(
                    paths.install_root,
                    paths.oodle_dll,
                    paths.usmap_path,
                    profile=PROFILE,
                ) as session:
                    for virtual_path in virtual_paths:
                        armature_obj = binding_armature
                        skeletal_mesh = session.skeletal_mesh(virtual_path)
                        if self.build_skeleton:
                            skeleton_path = skeletal_mesh.get("skeletonPath") or (
                                shared_packages._game_asset_path_to_virtual_uasset(
                                    skeletal_mesh.get("linkedSkeletonPath") or "",
                                    profile=PROFILE,
                                )
                            )
                            skeleton = None
                            if skeleton_path:
                                try:
                                    skeleton = session.skeleton_asset(skeleton_path)
                                except Exception as exc:
                                    print(
                                        f"Remake linked Skeleton '{skeleton_path}' could not be loaded; "
                                        f"using the SkeletalMesh reference skeleton: {exc}"
                                    )
                            skeleton = skeleton or skeletal_mesh.get("inlineSkeleton") or {}
                            bones = _bones_from_bridge(skeleton)
                            if not bones:
                                raise ValueError(
                                    f"'{virtual_path}' has no usable linked or inline Skeleton data."
                                )

                            variant_bone_usage = None
                            family_search_path = (
                                shared_packages._character_family_search_path(skeleton_path)
                                if skeleton_path else None
                            )
                            if self.create_variant_bone_collections and family_search_path:
                                try:
                                    variant_bone_usage = session.skeleton_bone_usage(
                                        skeleton_path, family_search_path
                                    )
                                except Exception as exc:
                                    print(f"  Warning: variant bone usage could not be read: {exc}")

                            socket_data = (
                                skeleton.get("sockets") or []
                                if self.attachment_sockets
                                != shared_packages.ATTACHMENT_SOCKETS_NONE
                                else []
                            )
                            armature_obj = build_armature_from_bones(
                                context,
                                skeleton.get("name") or os.path.splitext(
                                    os.path.basename(skeleton_path or virtual_path)
                                )[0],
                                bones,
                                socket_data,
                                scale_factor=self.scale_factor,
                                create_socket_empties=(
                                    self.attachment_sockets
                                    == shared_packages.ATTACHMENT_SOCKETS_EMPTIES
                                ),
                                create_socket_bones=(
                                    self.attachment_sockets
                                    == shared_packages.ATTACHMENT_SOCKETS_BONES
                                ),
                                setup_naive_ik=self.setup_naive_ik,
                                face_y_forward=shared_packages._face_y_forward_enabled(
                                    self.face_y_forward
                                ),
                            )
                            armature_obj[
                                shared_packages.KDI_COORDINATE_PROFILE_PROPERTY
                            ] = COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                            if skeleton_path:
                                armature_obj[
                                    shared_packages.SKELETON_ASSET_PATH_PROPERTY
                                ] = skeleton_path

                            if variant_bone_usage:
                                shared_packages._create_variant_bone_collections(
                                    armature_obj, variant_bone_usage
                                )

                            mesh_kdi_paths = shared_packages._skeletal_mesh_kdi_paths(
                                skeletal_mesh
                            )
                            kdi_virtual_path = (
                                mesh_kdi_paths[0]
                                if self.import_kdi and mesh_kdi_paths
                                else (
                                    shared_packages._kdi_path_for_skeleton(skeleton_path)
                                    if skeleton_path and self.import_kdi else None
                                )
                            )
                            if kdi_virtual_path in available_kdis:
                                try:
                                    kdi_asset = session.kdi_asset(kdi_virtual_path)
                                    secondary_assets = []
                                    for secondary_path in (
                                        shared_packages._secondary_kdi_paths_for_main(
                                            kdi_virtual_path, available_kdis
                                        )
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
                                                [kdi_asset], stream,
                                                ensure_ascii=False, indent=2,
                                            )
                                        result = bpy.ops.import_scene.ff7r_kinedriver_json(
                                            filepath=kdi_path,
                                            replace_previous_generated=True,
                                            translation_axis_order="YZX",
                                            scale_axis_order="YZX",
                                            coordinate_profile=(
                                                COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                                            ),
                                        )
                                        if result == {"FINISHED"}:
                                            kdi_count += 1
                                            if secondary_assets:
                                                shared_packages._import_secondary_kdi_passes(
                                                    secondary_assets, temp_dir
                                                )
                                except Exception as exc:
                                    print(
                                        f"  Warning: associated Remake KDI "
                                        f"'{kdi_virtual_path}' could not be imported: {exc}"
                                    )

                        obj, weighted_vertices, influence_count = (
                            shared_packages.import_skeletal_mesh_asset(
                                context,
                                skeletal_mesh,
                                virtual_path,
                                armature_obj=armature_obj,
                                scale_factor=self.scale_factor,
                                offset_opposite_faces=self.offset_opposite_faces,
                                material_session=session,
                                material_builder=materials.build_material,
                                face_y_forward=shared_packages._face_y_forward_enabled(
                                    self.face_y_forward
                                ),
                            )
                        )
                        vertex_count += len(obj.data.vertices)
                        triangle_count += len(obj.data.polygons)
                        weighted_count += weighted_vertices
                        influence_total += influence_count
                        material_count += len(obj.data.materials)
                        bound_count += int(armature_obj is not None)
        except Exception as exc:
            self.report({"ERROR"}, f"Remake SkeletalMesh import failed: {exc}")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        kdi_note = f", {kdi_count:,} KDI rig(s)" if self.import_kdi else ""
        self.report(
            {"INFO"},
            f"Imported {len(virtual_paths):,} Remake SkeletalMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{weighted_count:,} weighted vertices, {influence_total:,} influences, "
            f"{material_count:,} material slots, {bound_count:,} bound{kdi_note}",
        )
        return {"FINISHED"}


class FF7R_REMAKE_OT_import_kdi_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_remake_kdi_game_packages"
    bl_label = "KineDriver from Remake Packages"
    bl_description = (
        "Search mounted Remake packages for a _KDI asset and build its drivers "
        "on the active armature"
    )
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Package KDI",
        description="Type any part of a Remake KDI package path to search",
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
            self.report({"ERROR"}, "Select the imported Remake armature and make it active")
            return {"CANCELLED"}
        try:
            paths = refresh_kdi_index(context)
        except Exception as exc:
            self.report({"ERROR"}, f"Remake KDI index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            self.report({"WARNING"}, "No Remake _KDI assets were found in the mounted packages.")
            return {"CANCELLED"}
        self._load_last_import_settings(context)
        return context.window_manager.invoke_props_dialog(self, width=850)

    def draw(self, _context):
        layout = self.layout
        layout.label(text=f"{len(_VIRTUAL_KDIS):,} Remake KDI assets indexed", icon="PACKAGE")
        layout.prop(self, "virtual_path", icon="VIEWZOOM")
        layout.prop(self, "replace_previous_generated")
        layout.separator()
        layout.label(text="Uses Remake's legacy graph and the selected armature's KDI axes.")

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != "ARMATURE":
            self.report({"ERROR"}, "Select the imported Remake armature and make it active")
            return {"CANCELLED"}
        try:
            paths = _configured_paths(context)
            virtual_path = self.virtual_path.strip().replace("\\", "/").lstrip("/")
            if virtual_path not in refresh_kdi_index(context):
                raise ValueError("Choose a KDI asset from the Remake package search results.")
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=PROFILE,
            ) as session:
                kdi_asset = session.kdi_asset(virtual_path)
            with tempfile.TemporaryDirectory(prefix="ff7r_remake_kdi_") as temp_dir:
                kdi_path = os.path.join(temp_dir, os.path.basename(virtual_path) + ".json")
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
                    if coordinate_profile
                    == COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
                    else "XZY"
                )
                result = bpy.ops.import_scene.ff7r_kinedriver_json(
                    filepath=kdi_path,
                    replace_previous_generated=self.replace_previous_generated,
                    translation_axis_order=axis_order,
                    scale_axis_order=axis_order,
                    coordinate_profile=coordinate_profile,
                )
        except Exception as exc:
            self.report({"ERROR"}, f"Remake KDI import failed: {exc}")
            return {"CANCELLED"}
        if result != {"FINISHED"}:
            self.report({"ERROR"}, "The Remake KDI driver generator could not complete.")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        self.report({"INFO"}, f"Imported Remake KDI drivers from {virtual_path}")
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
