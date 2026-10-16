"""Build Blender geometry and skinning from decoded Unreal mesh payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import bpy
import numpy as np

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


def _static_mesh_material(name: str, virtual_path: str, namespace: str = ""):
    """Reuse an imported package material placeholder when possible."""
    if virtual_path:
        path_key = virtual_path.casefold()
        for material in bpy.data.materials:
            if material.get("ue_source_id", "") != namespace:
                continue
            if material.get("sqex_virtual_path", "").casefold() == path_key:
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
        material["sqex_virtual_path"] = virtual_path
    if namespace:
        material["ue_source_id"] = namespace
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
):
    """Build one Blender mesh from the gargoyle's selected conventional static-mesh LOD."""
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
    vertices = np.asarray(
        [
            (
                float(value[0]) * scale_factor,
                -float(value[1]) * scale_factor,
                float(value[2]) * scale_factor,
            )
            for value in positions
        ],
        dtype=np.float32,
    )
    faces = np.asarray(indices, dtype=np.int32).reshape(-1, 3)
    converted_normals = np.asarray(
        [(float(value[0]), -float(value[1]), float(value[2])) for value in normals],
        dtype=np.float32,
    )
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
                raise ValueError(
                    "The package bridge returned a mismatched color stream."
                )
            color_layer = mesh.color_attributes.new(
                name="Color", type="BYTE_COLOR", domain="POINT"
            )
            for vertex_index, color in enumerate(colors):
                color_layer.data[vertex_index].color = tuple(
                    float(component) / 255.0 for component in color
                )

        if tangents:
            if len(tangents) != len(positions):
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
            converted_tangents = np.asarray(
                [
                    (float(tangent[0]), -float(tangent[1]), float(tangent[2]))
                    for tangent in tangents
                ],
                dtype=np.float32,
            )
            if face_y_forward:
                converted_tangents = _apply_face_y_forward(converted_tangents)
            for vertex_index, tangent in enumerate(tangents):
                tangent_layer.data[vertex_index].vector = tuple(
                    converted_tangents[vertex_index]
                )
                # Mirroring Unreal Y changes the tangent-frame handedness; the
                # optional +90 degree Z rotation on top is a pure rotation and
                # does not affect this sign.
                tangent_sign_layer.data[vertex_index].value = -float(tangent[3])

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
        for material_index, section in enumerate(material_specs):
            section = section or {}
            material_name = section.get("materialName") or f"Material_{material_index}"
            material_path = section.get("materialPath") or ""
            mesh.materials.append(
                _static_mesh_material(
                    material_name,
                    material_path,
                    getattr(material_session, "texture_namespace", getattr(material_session, "cache_namespace", "")),
                )
            )
        for section in sections:
            material_index = int(section.get("materialIndex", 0))
            first_face = int(section.get("firstIndex", 0)) // 3
            face_count = int(section.get("triangleCount", 0))
            if not 0 <= material_index < len(mesh.materials):
                continue
            for face_index in range(
                first_face, min(first_face + face_count, len(mesh.polygons))
            ):
                mesh.polygons[face_index].material_index = material_index

        obj = bpy.data.objects.new(mesh_name, mesh)
        context.collection.objects.link(obj)
        obj["sqex_virtual_path"] = virtual_path
        obj["ff7r_source_type"] = static_mesh.get("sourceType", "")
        obj["ff7r_render_data"] = static_mesh.get("renderData", "")
        obj["ff7r_static_mesh_lod"] = int(static_mesh.get("lodIndex", 0))
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        if material_session is not None and (
            material_builder or (hooks and hooks.material_builder)
        ):
            material_builder = material_builder or hooks.material_builder
            for material_index, section in enumerate(material_specs):
                section = section or {}
                material_path = section.get("materialPath") or ""
                material_asset = (
                    material_session.material_asset_path(material_path)
                    if hasattr(material_session, "material_asset_path")
                    else _game_asset_path_to_virtual_uasset(
                        material_path, profile=material_session.profile
                    )
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
                    print(
                        f"  Warning: package material '{material_path}' could not be built: {exc}"
                    )
        if game_features and hooks and hooks.initialize_object:
            hooks.initialize_object(obj)
        if offset_mode == OFFSET_FACES_MODIFIER:
            # Use the same implementation as Object > Retrilogy tools >
            # Find Opposite Faces so the generated vertex group, material mask,
            # and Alpha Displace modifier stay identical.
            from ...core.blender.z_fighting import MESH_OT_find_opposite_faces

            if MESH_OT_find_opposite_faces.process_object(obj):
                mesh["ff7r_opposite_face_offset_mode"] = OFFSET_FACES_MODIFIER
        return obj
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


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
        name: obj.vertex_groups.new(name=name) for name in bone_names if name
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
        matching_bones = sum(name in armature_obj.data.bones for name in vertex_groups)
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
