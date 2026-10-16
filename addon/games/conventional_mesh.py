"""Conventional Unreal mesh workflows with small per-title adapters."""

from __future__ import annotations

from ..language import tooltips

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import os

import bpy

from ..core.blender.reporting import SQEX_LoggedOperator, report
from ..core.blender.skeletons import _bones_from_gargoyle, build_armature_from_bones
from ..core.package_utils import addon_package_name
from ..core.profiles import GameProfile
from ..formats import unreal_package as shared_packages
from ..formats.unreal_package.indexing import MeshAssetIndex, AnimationAssetIndex
from ..formats.unreal_package.importer import (
    MeshBrowserState, PackageMeshSource, make_package_mesh_importer,
)
from . import package_browser


@dataclass
class MeshImporterDefinition:
    """Per-game presentation and runtime state for shared mesh importers."""

    profile: GameProfile
    game_name: str
    default_virtual_path: str
    default_skeletal_mesh_path: str
    initial_directory: str
    virtual_static_meshes: list[str]
    virtual_skeletal_meshes: list[str]
    virtual_kdis: list[str]
    virtual_animations: list[str]
    browser: dict[str, Any]
    skeletal_browser: dict[str, Any]
    kdi_browser: dict[str, Any]
    animation_browser: dict[str, Any]
    mesh_cache_key: tuple[str, ...] | None = None
    mesh_cache_source: str = ""
    kdi_cache_key: tuple[str, ...] | None = None
    animation_cache_key: tuple[str, ...] | None = None

    material_builder: Callable | None = None
    configured_paths: Callable | None = None
    supported_skeletal_options: frozenset[str] = frozenset()
    mesh_path_filter: str = ""
    prepare_batch: Callable | None = None
    post_skeleton: Callable | None = None
    mesh_index: MeshAssetIndex = field(default_factory=MeshAssetIndex)
    animation_index: AnimationAssetIndex = field(default_factory=AnimationAssetIndex)


def make_definition(
    profile: GameProfile,
    *,
    game_name: str,
    default_virtual_path: str = "",
    default_skeletal_mesh_path: str = "",
    initial_directory: str,
    **options,
) -> MeshImporterDefinition:
    """Create isolated picker/cache state while keeping the import logic shared."""
    return MeshImporterDefinition(
        **options,
        profile=profile,
        game_name=game_name,
        default_virtual_path=default_virtual_path,
        default_skeletal_mesh_path=default_skeletal_mesh_path,
        initial_directory=initial_directory,
        virtual_static_meshes=[],
        virtual_skeletal_meshes=[],
        virtual_kdis=[],
        virtual_animations=[],
        browser=package_browser.make_state(
            f"{game_name} StaticMesh assets",
            initial_directory=initial_directory,
            file_icon="MESH_DATA",
        ),
        skeletal_browser=package_browser.make_state(
            f"{game_name} SkeletalMesh assets",
            initial_directory=initial_directory,
            file_icon="ARMATURE_DATA",
        ),
        kdi_browser=package_browser.make_state(
            f"{game_name} KineDriver assets",
            initial_directory=initial_directory,
            file_icon="CONSTRAINT_BONE",
        ),
        animation_browser=package_browser.make_state(
            f"{game_name} AnimSequence assets",
            initial_directory=initial_directory,
            file_icon="ACTION",
        ),
    )


def _configured_paths(context, definition):
    if definition.configured_paths is not None:
        return definition.configured_paths(context)
    addon = context.preferences.addons.get(addon_package_name(__package__))
    if addon is None:
        raise RuntimeError("The add-on preferences are unavailable.")
    paths = definition.profile.paths_from_preferences(
        addon.preferences, bpy.path.abspath
    )
    if not paths.install_root or not os.path.isdir(paths.install_root):
        raise FileNotFoundError(f"Set a valid {definition.game_name} install folder.")
    if definition.profile.aes_key_property and not paths.aes_key:
        raise ValueError(
            f"Set the {definition.game_name} AES key in the add-on preferences."
        )
    if definition.profile.requires_usmap and (
        not paths.usmap_path or not os.path.isfile(paths.usmap_path)
    ):
        raise FileNotFoundError(f"Set a valid {definition.game_name} mapping file.")
    if paths.oodle_dll and not os.path.isfile(paths.oodle_dll):
        raise FileNotFoundError("The configured shared Oodle DLL does not exist.")
    return paths


def refresh_mesh_indices(context, definition, *, force=False):
    paths = _configured_paths(context, definition)
    static, skeletal = definition.mesh_index.refresh(
        paths,
        definition.profile,
        path_filter=definition.mesh_path_filter,
        force=force,
    )
    definition.virtual_static_meshes, definition.virtual_skeletal_meshes = (
        static,
        skeletal,
    )
    definition.mesh_cache_key = definition.mesh_index.cache_key
    definition.mesh_cache_source = definition.mesh_index.source
    return static, skeletal


def refresh_static_mesh_index(context, definition, *, force=False):
    return refresh_mesh_indices(context, definition, force=force)[0]


def refresh_skeletal_mesh_index(context, definition, *, force=False):
    return refresh_mesh_indices(context, definition, force=force)[1]


def build_package_armature(
    context, operator, definition, session, payload, virtual_path
):
    """Resolve linked/inline bones and apply the selected import convention."""
    skeleton_path = (
        payload.get("skeletonPath")
        or shared_packages._game_asset_path_to_virtual_uasset(
            payload.get("linkedSkeletonPath") or "",
            profile=definition.profile,
        )
        or ""
    )
    skeleton = None
    if skeleton_path:
        try:
            skeleton = session.skeleton_asset(skeleton_path)
        except Exception as exc:
            print(
                f"{definition.game_name} linked Skeleton '{skeleton_path}' could not be loaded; using the mesh reference skeleton: {exc}"
            )
    source_skeleton = skeleton or payload.get("inlineSkeleton") or {}
    skeleton = source_skeleton
    if operator.import_mesh_referenced_bones_only:
        skeleton, _, _ = shared_packages._restrict_skeleton_to_referenced_bones(
            skeleton,
            set(payload.get("boneNames") or []),
        )
    bones = _bones_from_gargoyle(skeleton)
    if not bones:
        raise ValueError(
            f"'{virtual_path}' has no usable linked or inline Skeleton data."
        )
    supported = definition.supported_skeletal_options
    sockets = operator.attachment_sockets
    armature = build_armature_from_bones(
        context,
        skeleton.get("name") or Path(skeleton_path or virtual_path).stem,
        bones,
        (skeleton.get("sockets") or [])
        if sockets != shared_packages.ATTACHMENT_SOCKETS_NONE
        else [],
        scale_factor=operator.scale_factor,
        connect_bones=operator.connect_bones,
        create_socket_empties=sockets == shared_packages.ATTACHMENT_SOCKETS_EMPTIES,
        create_socket_bones=sockets == shared_packages.ATTACHMENT_SOCKETS_BONES,
        setup_naive_ik=operator.setup_naive_ik
        if "setup_naive_ik" in supported
        else False,
        face_y_forward=shared_packages._face_y_forward_enabled(operator.face_y_forward),
        preserve_ue_axis_order=operator.preserve_ue_axis_order,
    )
    armature[shared_packages.KDI_COORDINATE_PROFILE_PROPERTY] = (
        shared_packages.COORDINATE_PROFILE_REFERENCE
        if operator.preserve_ue_axis_order
        else shared_packages.COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
    )
    if skeleton_path:
        armature[shared_packages.SKELETON_ASSET_PATH_PROPERTY] = skeleton_path
    return armature, skeleton_path, source_skeleton


def make_static_mesh_importer(
    *,
    class_name: str,
    module_name: str,
    bl_idname: str,
    definition: MeshImporterDefinition,
) -> type[SQEX_LoggedOperator]:
    """Create a Blender operator with title-specific wording and shared behavior."""

    def browser_state(operator, context, *, refresh=False):
        if refresh:
            refresh_static_mesh_index(context, definition)
        return MeshBrowserState(definition.browser, definition.virtual_static_meshes,
                                key=definition.mesh_cache_key, source=definition.mesh_cache_source or "memory")

    def execute(self, context):
        try:
            paths = _configured_paths(context, definition)
            indexed_paths = refresh_static_mesh_index(context, definition)
            definition.browser["paths"] = list(indexed_paths)
            virtual_paths = package_browser.resolve_paths(
                context, definition.browser, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError(
                    "Select at least one StaticMesh in the package browser."
                )
            vertex_count = triangle_count = material_count = 0
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=definition.profile,
                aes_key=paths.aes_key,
            ) as session:
                for virtual_path in virtual_paths:
                    static_mesh = session.static_mesh(virtual_path)
                    obj = shared_packages.import_static_mesh_asset(
                        context,
                        static_mesh,
                        virtual_path,
                        scale_factor=self.scale_factor,
                        offset_opposite_faces=self.offset_opposite_faces,
                        face_y_forward=shared_packages._face_y_forward_enabled(
                            self.face_y_forward
                        ),
                        material_session=session,
                        material_builder=definition.material_builder,
                    )
                    vertex_count += len(obj.data.vertices)
                    triangle_count += len(obj.data.polygons)
                    material_count += len(obj.data.materials)
        except Exception as exc:
            report(
                self,
                {"ERROR"},
                f"{definition.game_name} StaticMesh import failed: {exc}",
            )
            return {"CANCELLED"}
        report(
            self,
            {"INFO"},
            f"Imported {len(virtual_paths):,} {definition.game_name} StaticMesh asset(s): "
            f"{vertex_count:,} vertices, {triangle_count:,} triangles, "
            f"{material_count:,} material slots",
        )
        return {"FINISHED"}

    return make_package_mesh_importer(
        class_name=class_name, module_name=module_name, bl_idname=bl_idname, mesh_kind="STATIC",
        default_virtual_path=definition.default_virtual_path,
        description=tooltips.SHARED_STATIC_MESH_IMPORT.format(
            definition_profile_engine_label=definition.profile.engine_label,
            definition_game_name=definition.game_name),
        source=PackageMeshSource(
            definition.game_name, browser_state, execute,
            material_summary="Imports mesh geometry, UVs, tangents, and material slots."),
    )


def make_skeletal_mesh_importer(*, class_name, module_name, bl_idname, definition):
    def browser_state(operator, context, *, refresh=False):
        if refresh:
            refresh_skeletal_mesh_index(context, definition)
        return MeshBrowserState(definition.skeletal_browser, definition.virtual_skeletal_meshes,
                                key=definition.mesh_cache_key, source=definition.mesh_cache_source or "memory")

    def execute(self, context):
        armature = (
            context.active_object
            if self.bind_active_armature and not self.build_skeleton
            else None
        )
        if (
            self.bind_active_armature
            and not self.build_skeleton
            and (armature is None or armature.type != "ARMATURE")
        ):
            report(
                self,
                {"ERROR"},
                "Select the matching armature, or enable Build Skeleton from Package.",
            )
            return {"CANCELLED"}
        try:
            paths = _configured_paths(context, definition)
            definition.skeletal_browser["paths"] = list(
                refresh_skeletal_mesh_index(context, definition)
            )
            virtual_paths = package_browser.resolve_paths(
                context, definition.skeletal_browser, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError(
                    "Select at least one SkeletalMesh in the package browser."
                )
            vertices = triangles = weighted = influences = materials = bound = kdi = 0
            with ExitStack() as stack:
                session = stack.enter_context(
                    shared_packages.PackageAssetSession(
                        paths.install_root,
                        paths.oodle_dll,
                        paths.usmap_path,
                        profile=definition.profile,
                        aes_key=paths.aes_key,
                    )
                )
                batch = (
                    definition.prepare_batch(context, self, session, stack)
                    if definition.prepare_batch
                    else {}
                )
                for virtual_path in virtual_paths:
                    payload = session.skeletal_mesh(virtual_path)
                    target = armature
                    if self.build_skeleton:
                        target, skeleton_path, source_skeleton = build_package_armature(
                            context,
                            self,
                            definition,
                            session,
                            payload,
                            virtual_path,
                        )
                        if definition.post_skeleton:
                            kdi += (
                                definition.post_skeleton(
                                    context,
                                    self,
                                    definition,
                                    session,
                                    payload,
                                    virtual_path,
                                    target,
                                    skeleton_path,
                                    source_skeleton,
                                    batch,
                                )
                                or 0
                            )
                    obj, weight_count, influence_count = (
                        shared_packages.import_skeletal_mesh_asset(
                            context,
                            payload,
                            virtual_path,
                            armature_obj=target,
                            scale_factor=self.scale_factor,
                            offset_opposite_faces=self.offset_opposite_faces,
                            face_y_forward=shared_packages._face_y_forward_enabled(
                                self.face_y_forward
                            ),
                            material_session=session,
                            material_builder=definition.material_builder,
                        )
                    )
                    vertices += len(obj.data.vertices)
                    triangles += len(obj.data.polygons)
                    materials += len(obj.data.materials)
                    weighted += weight_count
                    influences += influence_count
                    bound += int(target is not None)
        except Exception as exc:
            report(
                self,
                {"ERROR"},
                f"{definition.game_name} SkeletalMesh import failed: {exc}",
            )
            return {"CANCELLED"}
        note = f", {kdi:,} KineDriver rig(s)" if "import_kdi" in definition.supported_skeletal_options and self.import_kdi else ""
        report(
            self,
            {"INFO"},
            f"Imported {len(virtual_paths):,} {definition.game_name} SkeletalMesh asset(s): "
            f"{vertices:,} vertices, {triangles:,} triangles, {weighted:,} weighted vertices, "
            f"{influences:,} influences, {materials:,} material slots, {bound:,} bound{note}",
        )
        return {"FINISHED"}

    return make_package_mesh_importer(
        class_name=class_name, module_name=module_name, bl_idname=bl_idname, mesh_kind="SKELETAL",
        default_virtual_path=definition.default_skeletal_mesh_path,
        description=tooltips.SHARED_SKELETAL_MESH_IMPORT.format(definition_game_name=definition.game_name),
        source=PackageMeshSource(
            definition.game_name, browser_state, execute,
            game_options=definition.supported_skeletal_options,
            material_summary="Creates an armature from the linked Skeleton and imports skin weights."),
    )
