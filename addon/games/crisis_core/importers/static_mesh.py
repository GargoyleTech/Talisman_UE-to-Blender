"""Import conventional UE4.27 StaticMesh packages from Crisis Core Reunion."""

from __future__ import annotations

import os

import bpy

from ....core.blender.reporting import FF7R_LoggedOperator
from ....core.blender.skeletons import _bones_from_bridge, build_armature_from_bones
from ..profile import PROFILE
from .. import materials
from ...rebirth.importers import packages as shared_packages
from ...conventional_map import make_umap_importer
from ... import package_browser


DEFAULT_STATIC_MESH_PATH = (
    "CCFF7R/Content/Fair/Map/00_Common/Prop/00_Prop/House/Mesh/"
    "S_en_ban2_02_MP_HouseA.uasset"
)
DEFAULT_SKELETAL_MESH_PATH = ""

_VIRTUAL_STATIC_MESHES: list[str] = []
_VIRTUAL_SKELETAL_MESHES: list[str] = []
_MESH_CACHE_KEY: tuple[str, str, str] | None = None
_MESH_CACHE_SOURCE = ""
_STATIC_MESH_BROWSER = package_browser.make_state(
    "Crisis Core StaticMesh assets",
    initial_directory="CCFF7R/Content",
    file_icon="MESH_DATA",
)
_SKELETAL_MESH_BROWSER = package_browser.make_state(
    "Crisis Core SkeletalMesh assets",
    initial_directory="CCFF7R/Content",
    file_icon="ARMATURE_DATA",
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
        raise FileNotFoundError("Set a valid CRISIS CORE REUNION install folder.")
    if not paths.usmap_path or not os.path.isfile(paths.usmap_path):
        raise FileNotFoundError("Set a valid Crisis Core mapping file.")
    if paths.oodle_dll and not os.path.isfile(paths.oodle_dll):
        raise FileNotFoundError("The configured Crisis Core Oodle DLL does not exist.")
    return paths


def refresh_static_mesh_index(context, *, force=False) -> list[str]:
    """Build and cache Crisis Core's actual conventional mesh package lists."""
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
                {"action": "mesh_index"},
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
                print(
                    f"Crisis Core mesh index skipped {failure_count:,} "
                    "unreadable package(s)."
                )
            shared_packages._save_mesh_disk_cache(
                cache_path,
                cache_key,
                package_signature,
                _VIRTUAL_STATIC_MESHES,
                _VIRTUAL_SKELETAL_MESHES,
            )
            _MESH_CACHE_SOURCE = "fresh asset registry"
        _MESH_CACHE_KEY = cache_key
    return _VIRTUAL_STATIC_MESHES


def refresh_skeletal_mesh_index(context, *, force=False) -> list[str]:
    """Return Crisis Core's indexed USkeletalMesh package paths."""
    refresh_static_mesh_index(context, force=force)
    return _VIRTUAL_SKELETAL_MESHES


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


class FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_crisis_core_static_mesh_game_packages"
    bl_label = "Static Mesh from Crisis Core Packages"
    bl_description = "Import a conventional UE4.27 StaticMesh from Crisis Core Reunion packages"
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Static Mesh Path",
        description="Type any part of an indexed Crisis Core StaticMesh package path",
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
            self.report({"ERROR"}, f"Crisis Core StaticMesh index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            self.report({"WARNING"}, "No Crisis Core StaticMesh assets were found.")
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
                f"{len(_VIRTUAL_STATIC_MESHES):,} Crisis Core StaticMesh assets indexed "
                f"({_MESH_CACHE_SOURCE or 'memory'})"
            ),
            icon="PACKAGE",
        )
        layout.label(text="Builds Albedo, Normal, DetailNormal, RMA/RMAE and Emissive material slots.")

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
                        face_y_forward=shared_packages._face_y_forward_enabled(
                            self.face_y_forward
                        ),
                    )
                    vertex_count += len(obj.data.vertices)
                    triangle_count += len(obj.data.polygons)
                    material_count += len(obj.data.materials)
        except Exception as exc:
            self.report({"ERROR"}, f"Crisis Core StaticMesh import failed: {exc}")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        self.report(
            {"INFO"},
            f"Imported {len(virtual_paths):,} Crisis Core StaticMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{material_count:,} material slots",
        )
        return {"FINISHED"}


class FF7R_CRISIS_CORE_OT_import_skeletal_mesh_game_packages(FF7R_LoggedOperator):
    bl_idname = "import_scene.ff7r_crisis_core_skeletal_mesh_game_packages"
    bl_label = "Skeletal Mesh from Crisis Core Packages"
    bl_description = "Import a Crisis Core SkeletalMesh and its linked Skeleton"
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Skeletal Mesh Path",
        description="Type any part of an indexed Crisis Core SkeletalMesh package path",
        default=DEFAULT_SKELETAL_MESH_PATH,
        search=_search_virtual_skeletal_meshes,
        search_options={"SORT"},
    )
    scale_factor: bpy.props.FloatProperty(
        name="Scale", description="Convert Unreal centimeters to Blender units",
        default=0.01, min=0.0001, max=100.0,
    )
    offset_opposite_faces: bpy.props.EnumProperty(
        name="Offset Faces", description="Choose how overlapping opposite-facing faces are handled",
        items=shared_packages.OFFSET_FACES_ITEMS, default=shared_packages.OFFSET_FACES_NONE,
    )
    bind_active_armature: bpy.props.BoolProperty(
        name="Bind Active Armature",
        description="Bind matching vertex groups to the active armature instead of creating one",
        default=True,
    )
    build_skeleton: bpy.props.BoolProperty(
        name="Build Linked Skeleton",
        description="Build a new armature from the SkeletalMesh's associated Skeleton asset",
        default=True,
    )
    face_y_forward: bpy.props.EnumProperty(
        name="Face Forward", description="Choose the imported mesh and armature's forward axis",
        items=shared_packages.FACE_FORWARD_ITEMS, default=shared_packages.FACE_FORWARD_UNREAL,
    )

    _persisted_props = (
        "scale_factor", "offset_opposite_faces", "bind_active_armature",
        "build_skeleton", "face_y_forward",
    )

    def invoke(self, context, _event):
        try:
            paths = refresh_skeletal_mesh_index(context)
        except Exception as exc:
            self.report({"ERROR"}, f"Crisis Core SkeletalMesh index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            self.report({"WARNING"}, "No Crisis Core SkeletalMesh assets were found.")
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
        layout.prop(self, "face_y_forward")
        layout.label(
            text=(f"{len(_VIRTUAL_SKELETAL_MESHES):,} Crisis Core SkeletalMesh assets indexed "
                  f"({_MESH_CACHE_SOURCE or 'memory'})"),
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
                "Select the matching armature, or enable Build Linked Skeleton.",
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
            vertex_count = triangle_count = weighted_count = influence_total = 0
            material_count = bound_count = 0
            with shared_packages.PackageAssetSession(
                paths.install_root, paths.oodle_dll, paths.usmap_path, profile=PROFILE
            ) as session:
                for virtual_path in virtual_paths:
                    armature_obj = binding_armature
                    skeletal_mesh = session.skeletal_mesh(virtual_path)
                    if self.build_skeleton:
                        skeleton_path = skeletal_mesh.get("skeletonPath")
                        skeleton = None
                        if skeleton_path:
                            try:
                                skeleton = session.skeleton_asset(skeleton_path)
                            except Exception as exc:
                                print(
                                    f"Crisis Core linked Skeleton '{skeleton_path}' could not be loaded; "
                                    f"using the SkeletalMesh reference skeleton: {exc}"
                                )
                        skeleton = skeleton or skeletal_mesh.get("inlineSkeleton") or {}
                        bones = _bones_from_bridge(skeleton)
                        if not bones:
                            raise ValueError(
                                f"'{virtual_path}' has no usable linked or inline Skeleton data."
                            )
                        armature_obj = build_armature_from_bones(
                            context,
                            skeleton.get("name") or os.path.splitext(
                                os.path.basename(skeleton_path or virtual_path)
                            )[0],
                            bones,
                            skeleton.get("sockets") or [],
                            scale_factor=self.scale_factor,
                            face_y_forward=shared_packages._face_y_forward_enabled(
                                self.face_y_forward
                            ),
                        )
                    obj, weighted_vertices, influence_count = (
                        shared_packages.import_skeletal_mesh_asset(
                            context, skeletal_mesh, virtual_path,
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
            self.report({"ERROR"}, f"Crisis Core SkeletalMesh import failed: {exc}")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        self.report(
            {"INFO"},
            f"Imported {len(virtual_paths):,} Crisis Core SkeletalMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{weighted_count:,} weighted vertices, {influence_total:,} influences, "
            f"{material_count:,} material slots, {bound_count:,} bound",
        )
        return {"FINISHED"}


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
