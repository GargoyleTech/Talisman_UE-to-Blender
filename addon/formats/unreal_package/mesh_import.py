"""Build Blender geometry and skinning from decoded Unreal mesh payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import bpy
import numpy as np

from ...core.blender.import_cache import find_datablock, remember_datablock
from ...core.blender.mesh_geometry import populate_triangle_mesh
from ...core.blender.material_nodes import apply_world_grid_material, is_world_grid_material

from ..mec.parser import offset_opposite_face_geometry, scaled_opposite_face_offset
from .options import (
    OFFSET_FACES_BAKED,
    OFFSET_FACES_MODIFIER,
    _normalize_offset_faces_mode,
)
from .paths import _game_asset_path_to_virtual_uasset
from .session import PackageAssetSession


@dataclass(frozen=True)
class MeshImportHooks:
    """Optional title material and deformation behavior."""

    material_builder: Callable | None = None
    initialize_object: Callable | None = None
    configure_binding: Callable | None = None


@dataclass(frozen=True)
class SharedSkinWeights:
    """An initialized map mesh's deform data and its vertex-group index layout."""

    mesh: bpy.types.Mesh
    group_names: tuple[str, ...]
    bone_names: tuple[str, ...]
    vertex_count: int
    weighted_vertices: int
    influence_count: int

    @classmethod
    def capture(cls, obj, skeletal_mesh, weighted_vertices, influence_count):
        """Capture only after a successful source-object weight initialization."""
        return cls(
            obj.data,
            tuple(group.name for group in obj.vertex_groups),
            tuple(dict.fromkeys(name for name in (skeletal_mesh.get("boneNames") or []) if name)),
            len(obj.data.vertices),
            weighted_vertices,
            influence_count,
        )

    def bind_groups(self, obj):
        if obj.data != self.mesh or len(obj.data.vertices) != self.vertex_count:
            raise ValueError("Shared skin weights belong to a different mesh or vertex layout.")
        # New objects inherit the mesh's group layout on current Blender versions.
        # Also support versions where definitions must be recreated on each object;
        # deform indices must match every source group, including non-bone masks.
        existing = tuple(group.name for group in obj.vertex_groups)
        if existing != self.group_names[:len(existing)]:
            raise ValueError("Shared skin-weight vertex-group indices have changed.")
        for name in self.group_names[len(existing):]:
            obj.vertex_groups.new(name=name)


def _static_mesh_material(name: str, virtual_path: str, namespace: str = "", cache_owner=None):
    """Reuse an imported package material placeholder when possible."""
    if virtual_path:
        path_key = virtual_path.casefold()
        material = find_datablock("materials", "package-source", (namespace, path_key),
                                  lambda item: (item.get("ue_source_id", ""),
                                                item.get("ue_virtual_path", "").casefold()), cache_owner)
        if material is not None:
            apply_world_grid_material(material, virtual_path)
            return material
    material = None if namespace else bpy.data.materials.get(name)
    if material is not None and material.get("ue_source_id", "") != namespace:
        material = None
    if material is None:
        material = bpy.data.materials.new(name=name)
        # Non-RMI packages keep Blender's simple placeholder material.  Give
        # its default Principled node the same dielectric IOR as every other
        # generated material instead of inheriting Blender's 1.5 default.
        if material.node_tree is not None:
            bsdf = next(
                (
                    node
                    for node in material.node_tree.nodes
                    if node.bl_idname == "ShaderNodeBsdfPrincipled"
                ),
                None,
            )
            if bsdf is not None and bsdf.inputs.get("IOR") is not None:
                bsdf.inputs["IOR"].default_value = 1.3
    if virtual_path:
        material["ue_virtual_path"] = virtual_path
    if namespace:
        material["ue_source_id"] = namespace
    apply_world_grid_material(material, virtual_path)
    remember_datablock("materials", material, cache_owner)
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
    game_features: bool = True,
    hooks: MeshImportHooks | None = None,
    _source_only: bool = False,
    _select_object: bool = True,
):
    """Build conventional or native geometry using typed arrays and bulk RNA writes."""
    offset_mode = _normalize_offset_faces_mode(offset_opposite_faces)
    positions = np.asarray(static_mesh.get("positions", []), dtype=np.float32)
    normals = np.asarray(static_mesh.get("normals", []), dtype=np.float32)
    tangents = np.asarray(static_mesh.get("tangents") if static_mesh.get("tangents") is not None else [], dtype=np.float32)
    uv_channels = static_mesh.get("uvChannels") or []
    colors = static_mesh.get("colors")
    indices = np.asarray(static_mesh.get("indices", []), dtype=np.int32)
    sections = static_mesh.get("sections") or []
    if positions.ndim != 2 or positions.shape[1] != 3 or not positions.size or indices.ndim != 1 or not indices.size or indices.size % 3:
        raise ValueError("The package bridge returned incomplete static-mesh geometry.")
    if normals.shape != positions.shape:
        raise ValueError("The package bridge returned a mismatched normal stream.")
    if any(len(channel) != len(positions) for channel in uv_channels):
        raise ValueError("The package bridge returned a mismatched UV stream.")
    if indices.min() < 0 or indices.max() >= len(positions):
        raise ValueError("The package bridge returned an out-of-range mesh index.")
    vertex_count = len(positions)

    mesh_name = static_mesh.get("name") or Path(virtual_path).stem
    vertices = positions.copy()
    vertices *= scale_factor
    vertices[:, 1] *= -1
    faces = indices.reshape(-1, 3)
    converted_normals = normals.copy()
    converted_normals[:, 1] *= -1
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
        populate_triangle_mesh(mesh, vertices, indices, smooth=True)
        del vertices
        if offset_mode == OFFSET_FACES_BAKED:
            # Store this on the datablock because UMAP actors reuse it after the
            # temporary source object has been removed.
            mesh["ff7r_opposite_face_offset_vertices"] = offset_count
        if hasattr(mesh, "normals_split_custom_set_from_vertices"):
            # RNA parses native Python floats faster than NumPy scalars. Bound
            # the temporary list so very large native meshes retain low peaks.
            mesh.normals_split_custom_set_from_vertices(
                converted_normals.tolist() if vertex_count <= 1_000_000 else converted_normals
            )
        del converted_normals

        for channel_index, channel in enumerate(uv_channels):
            # Preserve the names used by Rebirth material parameters, e.g.
            # TextureCoordinate0 / Coordinate0 in the cooked material data.
            layer_name = f"Coordinate{channel_index}"
            uv_layer = mesh.uv_layers.new(name=layer_name)
            values = np.asarray(channel, dtype=np.float32)
            if values.shape != (vertex_count, 2):
                raise ValueError("The package bridge returned an invalid UV stream.")
            loop_uv = values[indices]
            loop_uv[:, 1] = 1.0 - loop_uv[:, 1]
            uv_layer.data.foreach_set("uv", loop_uv.ravel())
            del loop_uv

        if colors is not None:
            colors = np.array(colors, dtype=np.float32, copy=True)
            if colors.shape != (vertex_count, 4):
                raise ValueError(
                    "The package bridge returned a mismatched color stream."
                )
            color_layer = mesh.color_attributes.new(
                name="Color", type="BYTE_COLOR", domain="POINT"
            )
            colors *= 1.0 / 255.0
            color_layer.data.foreach_set("color", colors.ravel())
            del colors

        if tangents.size:
            if tangents.shape != (vertex_count, 4):
                raise ValueError(
                    "The package bridge returned a mismatched tangent stream."
                )
            tangent_layer = mesh.attributes.new(
                name="ff7r_tangent", type="FLOAT_VECTOR", domain="POINT"
            )
            tangent_sign_layer = mesh.attributes.new(
                name="ff7r_tangent_sign", type="FLOAT", domain="POINT"
            )
            # Adding an attribute can reallocate Blender's CustomData array and
            # invalidate an earlier RNA data view. Reacquire both before writes.
            tangent_layer = mesh.attributes["ff7r_tangent"]
            tangent_sign_layer = mesh.attributes["ff7r_tangent_sign"]
            converted_tangents = tangents[:, :3].copy()
            converted_tangents[:, 1] *= -1
            if face_y_forward:
                converted_tangents = _apply_face_y_forward(converted_tangents)
            tangent_layer.data.foreach_set("vector", converted_tangents.ravel())
            # Mirroring Unreal Y changes the tangent-frame handedness.
            tangent_sign_layer.data.foreach_set("value", -tangents[:, 3].copy())
            del converted_tangents

        material_count = (
            max(
                (int(section.get("materialIndex", -1)) for section in sections),
                default=-1,
            )
            + 1
        )
        material_specs = [None] * material_count
        for section in sections:
            material_index = int(section.get("materialIndex", -1))
            if 0 <= material_index < material_count:
                material_specs[material_index] = section
        material_builder = material_builder or (hooks and hooks.material_builder)
        for material_index, section in enumerate(material_specs):
            section = section or {}
            material_name = section.get("materialName") or f"Material_{material_index}"
            material_path = section.get("materialPath") or ""
            material = None
            # Build the actual shader before allocating a fallback with the
            # same name. Otherwise Blender suffixes every generated material
            # with .001 and leaves an unused placeholder behind.
            if material_session is not None and material_builder and not is_world_grid_material(material_path):
                material_asset = (
                    material_session.material_asset_path(material_path)
                    if hasattr(material_session, "material_asset_path")
                    else _game_asset_path_to_virtual_uasset(
                        material_path, profile=material_session.profile
                    )
                )
                if material_asset:
                    try:
                        material_data = material_session.material_instance(material_asset)
                        material = material_builder(
                            material_name, material_path, material_data, material_session,
                        )
                    except Exception as exc:
                        # Surface material failures must never discard imported mesh data.
                        print(
                            f"  Warning: package material '{material_path}' could not be built: {exc}"
                        )
            if material is None:
                material = _static_mesh_material(
                    material_name,
                    material_path,
                    getattr(material_session, "texture_namespace", getattr(material_session, "cache_namespace", "")),
                    material_session,
                )
            mesh.materials.append(material)
        material_indices = np.zeros(len(faces), dtype=np.int32)
        for section in sections:
            material_index = int(section.get("materialIndex", 0))
            first_face = int(section.get("firstIndex", 0)) // 3
            face_count = int(section.get("triangleCount", 0))
            if not 0 <= material_index < len(mesh.materials):
                continue
            material_indices[max(0, first_face):min(first_face + face_count, len(faces))] = material_index
        mesh.polygons.foreach_set("material_index", material_indices)
        del material_indices

        # Map placements reuse the datablock after removing this source object.
        mesh["ue_geometry_source"] = static_mesh.get("geometrySource", "CONVENTIONAL")
        if material_session is not None and hasattr(material_session, "geometry_namespace"):
            mesh["ue_geometry_id"] = material_session.geometry_namespace
        if static_mesh.get("nanite"):
            mesh["ue_nanite"] = static_mesh["nanite"]
        if static_mesh.get("naniteFallbackReason"):
            mesh["ue_nanite_fallback_reason"] = static_mesh["naniteFallbackReason"]

        initialize_object = game_features and hooks and hooks.initialize_object
        if _source_only and not initialize_object and offset_mode != OFFSET_FACES_MODIFIER:
            return mesh
        obj = bpy.data.objects.new(mesh_name, mesh)
        if not _source_only:
            context.collection.objects.link(obj)
        obj["ue_virtual_path"] = virtual_path
        obj["ff7r_source_type"] = static_mesh.get("sourceType", "")
        obj["ff7r_render_data"] = static_mesh.get("renderData", "")
        obj["ff7r_static_mesh_lod"] = int(static_mesh.get("lodIndex", 0))
        obj["ue_geometry_source"] = mesh["ue_geometry_source"]
        if _select_object and not _source_only:
            for selected in context.selected_objects:
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
        if initialize_object:
            hooks.initialize_object(obj)
        if offset_mode == OFFSET_FACES_MODIFIER:
            # Use the same implementation as Object > Retrilogy tools >
            # Find Opposite Faces so the generated vertex group, material mask,
            # and Alpha Displace modifier stay identical.
            from ...core.blender.z_fighting import MESH_OT_find_opposite_faces

            if MESH_OT_find_opposite_faces.process_object(obj):
                mesh["ff7r_opposite_face_offset_mode"] = OFFSET_FACES_MODIFIER
        if _source_only:
            bpy.data.objects.remove(obj, do_unlink=True)
            return mesh
        return obj
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


def import_static_mesh_datablock(context, static_mesh, virtual_path, **options):
    """Build a map source without linking/selecting a temporary scene object."""
    return import_static_mesh_asset(context, static_mesh, virtual_path, _source_only=True, **options)


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
    game_features: bool = True,
    hooks: MeshImportHooks | None = None,
    _select_object: bool = True,
):
    """Build a skinned package mesh using the shared geometry/material path."""
    obj = import_static_mesh_asset(
        context,
        skeletal_mesh,
        virtual_path,
        scale_factor=scale_factor,
        offset_opposite_faces=offset_opposite_faces,
        material_session=material_session,
        material_builder=material_builder,
        face_y_forward=face_y_forward,
        game_features=game_features,
        hooks=hooks,
        _select_object=_select_object,
    )
    try:
        weighted_vertices, influence_count = bind_skeletal_mesh_object(
            obj, skeletal_mesh, armature_obj, game_features=game_features, hooks=hooks
        )

        obj["sqex_skeletal_mesh_lod"] = int(skeletal_mesh.get("lodIndex", 0))
        obj["sqex_normal_format"] = skeletal_mesh.get("normalFormat") or ""
        obj["sqex_linked_skeleton_path"] = skeletal_mesh.get("skeletonPath") or ""
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
    game_features: bool = True,
    hooks: MeshImportHooks | None = None,
    shared_weights: SharedSkinWeights | None = None,
):
    """Initialize weights, or reuse a map source's weights and bind its new rig."""
    if shared_weights is not None:
        shared_weights.bind_groups(obj)
        bone_names = shared_weights.bone_names
        weighted_vertices = shared_weights.weighted_vertices
        influence_count = shared_weights.influence_count
    else:
        bone_names = skeletal_mesh.get("boneNames") or []
        weights = skeletal_mesh.get("weights") or []
        if len(weights) != len(obj.data.vertices):
            raise ValueError("The package bridge returned a mismatched skin-weight stream.")

        vertex_groups = {
            name: obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
            for name in bone_names if name
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
                group.add([vertex_index], weight, "REPLACE")
                has_weight = True
                influence_count += 1
            if has_weight:
                weighted_vertices += 1

    if armature_obj is not None:
        if armature_obj.type != "ARMATURE":
            raise ValueError("The selected binding object is not an armature.")
        matching_bones = sum(name in armature_obj.data.bones for name in set(bone_names) if name)
        if not matching_bones:
            raise ValueError(
                f"The selected armature has no bones matching '{obj.name}'."
            )
        modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
        modifier.object = armature_obj
        modifier.use_deform_preserve_volume = game_features
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

        limbal_drivers = (
            hooks.configure_binding(obj, armature_obj)
            if game_features and hooks and hooks.configure_binding
            else 0
        )
        if limbal_drivers:
            obj["ff7r_limbal_eye_drivers"] = limbal_drivers

    return weighted_vertices, influence_count
