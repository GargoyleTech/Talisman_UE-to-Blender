"""Shared source datablocks for package-backed map placements."""

from __future__ import annotations

from pathlib import Path

import bpy

from ...core.blender.skeletons import _bones_from_gargoyle, build_armature_from_bones
from ..ue_map import map_import
from .mesh_import import (
    MeshImportHooks,
    SharedSkinWeights,
    import_static_mesh_asset,
    import_static_mesh_datablock,
    import_skeletal_mesh_asset,
)
from .options import SKELETON_ASSET_PATH_PROPERTY
from .paths import _game_asset_path_to_virtual_uasset
from .session import PackageAssetSession
from .skeleton_data import mesh_bind_skeleton


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
        hooks: MeshImportHooks | None = None,
    ):
        self.context = context
        self.session = session
        self.scale_factor = scale_factor
        self.offset_opposite_faces = offset_opposite_faces
        self.build_materials = build_materials
        self.material_builder = material_builder
        self.hooks = hooks
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
        mesh = import_static_mesh_datablock(
            self.context,
            static_mesh,
            virtual_path,
            scale_factor=self.scale_factor,
            offset_opposite_faces=self.offset_opposite_faces,
            material_session=self.session if self.build_materials else None,
            material_builder=self.material_builder,
            hooks=self.hooks,
        )
        mesh["ue_virtual_path"] = virtual_path
        self._mesh_cache[cache_key] = mesh
        return mesh


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
        hooks: MeshImportHooks | None = None,
    ):
        self.context = context
        self.session = session
        self.scale_factor = scale_factor
        self.offset_opposite_faces = offset_opposite_faces
        self.build_materials = build_materials
        self.material_builder = material_builder
        self.hooks = hooks
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
        # Let the map importer classify that expected case without a gargoyle
        # stack trace, while standalone mesh imports retain full diagnostics.
        skeletal_mesh = self.session.skeletal_mesh(virtual_path, report_errors=False)
        skeleton_path = skeletal_mesh.get("skeletonPath")
        armature_obj = None
        try:
            # Meshes sharing a Skeleton can have different authored bind poses.
            skeleton_key = virtual_path.casefold()
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
                skeleton = mesh_bind_skeleton(skeletal_mesh, skeleton)
                if not skeleton.get("bones"):
                    raise ValueError(
                        "The associated Skeleton has no usable linked or inline bones."
                    )
                armature_obj = build_armature_from_bones(
                    self.context,
                    skeleton.get("name") or Path(skeleton_path or virtual_path).stem,
                    _bones_from_gargoyle(skeleton),
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

        mesh_obj, weighted_vertices, influence_count = import_skeletal_mesh_asset(
            self.context,
            skeletal_mesh,
            virtual_path,
            armature_obj=armature_obj,
            scale_factor=self.scale_factor,
            offset_opposite_faces=self.offset_opposite_faces,
            material_session=self.session if self.build_materials else None,
            material_builder=self.material_builder,
            hooks=self.hooks,
            _select_object=False,
        )

        mesh = mesh_obj.data
        shared_weights = SharedSkinWeights.capture(
            mesh_obj, skeletal_mesh, weighted_vertices, influence_count
        )
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
            shared_weights=shared_weights,
        )
        self._asset_cache[cache_key] = asset
        return asset
