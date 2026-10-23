"""Generic package-map placement with neutral, shared mesh sources."""

import json
from pathlib import PurePosixPath

import bpy

from ...core.blender.skeletons import _bones_from_gargoyle, build_armature_from_bones
from ...formats.ue_map import map_import
from .. import unreal_package as meshes
from . import materials
from .session import tag_armature


def _reference_path(reference):
    if not isinstance(reference, dict):
        return ""
    path = reference.get("ObjectPath") or map_import.extract_static_mesh_name(reference.get("ObjectName", "")) or ""
    return path if path.casefold() != "none" else ""


class MapAssets:
    """Cache source datablocks for an entire selected-map batch."""

    def __init__(self, context, session, scale_factor, *, offset_opposite_faces=False):
        self.context = context
        self.session = session
        self.scale_factor = scale_factor
        self.offset_opposite_faces = offset_opposite_faces
        self.material_builder = getattr(session, "material_builder", materials.build_material)
        self.static_cache = {}
        self.skeletal_cache = {}
        self.override_sources = {}

    def _mesh_object(self, payload, path, *, datablock=False):
        builder = meshes.import_static_mesh_datablock if datablock else meshes.import_static_mesh_asset
        result = builder(
            self.context, payload, path, scale_factor=self.scale_factor,
            offset_opposite_faces=self.offset_opposite_faces,
            material_session=self.session, material_builder=self.material_builder, game_features=False,
            _select_object=False,
        )
        mesh = result if datablock else result.data
        mesh["ue_virtual_path"] = path
        mesh["ue_source_id"] = self.session.cache_namespace
        for index, material in enumerate(mesh.materials):
            if self.material_builder is materials.build_material and not material.get("ue_texture_inventory_complete"):
                mesh.materials[index] = materials.build_material(
                    material.name, material.get("ue_virtual_path", ""), {}, self.session,
                )
        return result

    def _mesh(self, payload, path):
        return self._mesh_object(payload, path, datablock=True)

    def static(self, path):
        key = path.casefold()
        if key not in self.static_cache:
            self.static_cache[key] = self._mesh(self.session.static_mesh(path), path)
        return self.static_cache[key]

    def skeletal(self, path):
        key = path.casefold()
        if key in self.skeletal_cache:
            return self.skeletal_cache[key]
        payload = self.session.skeletal_mesh(path, report_errors=False)
        skeleton = payload.get("inlineSkeleton") or {}
        if not skeleton.get("bones") and payload.get("skeletonPath"):
            skeleton = self.session.skeleton_asset(payload["skeletonPath"])
        bones = _bones_from_gargoyle(skeleton)
        if not bones:
            raise ValueError(f"No reference skeleton available for {path}")
        armature = build_armature_from_bones(
            self.context, payload.get("name") or "UnrealArmature", bones, [],
            scale_factor=self.scale_factor, preserve_ue_axis_order=True, game_features=False,
        )
        mesh_obj = None
        try:
            tag_armature(armature, self.session, payload, path, self.scale_factor)
            armature_data = armature.data
            mesh_obj = self._mesh_object(payload, path)
            weighted_vertices, influence_count = meshes.bind_skeletal_mesh_object(
                mesh_obj, payload, game_features=False,
            )
            shared_weights = meshes.SharedSkinWeights.capture(
                mesh_obj, payload, weighted_vertices, influence_count,
            )
            mesh = mesh_obj.data
        except Exception:
            if mesh_obj is not None:
                mesh = mesh_obj.data
                bpy.data.objects.remove(mesh_obj, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if data.users == 0:
                bpy.data.armatures.remove(data)
            raise
        bpy.data.objects.remove(armature, do_unlink=True)
        bpy.data.objects.remove(mesh_obj, do_unlink=True)
        asset = map_import.SkeletalMeshDatablocks(mesh, armature_data, payload, path, shared_weights)
        self.skeletal_cache[key] = asset
        return asset

    def _apply_overrides(self, obj, paths):
        for slot, path in zip(obj.material_slots, paths):
            if not path:
                continue
            material = self.material_builder(
                path.rsplit("/", 1)[-1].split(".")[0], path,
                self.session.material_instance(path), self.session,
            )
            slot.link = "OBJECT"
            slot.material = material

    def initialize_component(self, obj, entry):
        obj["ue_source_id"] = self.session.cache_namespace
        if obj.type == "MESH" and obj.data.get("ue_geometry_source"):
            obj["ue_geometry_source"] = obj.data["ue_geometry_source"]
        obj["ue_component_name"] = str(entry.get("Name") or "")
        outer = entry.get("Outer") or {}
        actor_path = outer.get("ObjectPath", "") if isinstance(outer, dict) else str(outer)
        if actor_path:
            obj["ue_actor_path"] = actor_path
            obj["ue_component_path"] = actor_path + "." + obj["ue_component_name"]
        from .visibility import apply_default_visibility
        apply_default_visibility(obj, getattr(self.session, "hidden_object_patterns", ()),
                                 actor_path.rsplit(".", 1)[-1])
        overrides = tuple(_reference_path(ref) for ref in (entry.get("Properties") or {}).get("OverrideMaterials") or [])
        if not any(overrides):
            return
        if obj.get("sqex_foliage_instance_count"):
            modifier = next((mod for mod in obj.modifiers if mod.type == "NODES"), None)
            if modifier is None:
                return
            source_node = next(node for node in modifier.node_group.nodes if node.type == "OBJECT_INFO")
            source = source_node.inputs["Object"].default_value
            key = (source.data.as_pointer(), overrides)
            variant = self.override_sources.get(key)
            if variant is None:
                variant = source.copy()
                variant.name = source.name + "_Override"
                source.users_collection[0].objects.link(variant)
                variant.hide_set(True)
                self._apply_overrides(variant, overrides)
                self.override_sources[key] = variant
            group = modifier.node_group.copy()
            next(node for node in group.nodes if node.type == "OBJECT_INFO").inputs["Object"].default_value = variant
            modifier.node_group = group
        else:
            target = next((child for child in obj.children if child.type == "MESH"), None) if obj.type == "ARMATURE" else obj
            if target is not None and target.type == "MESH":
                self._apply_overrides(target, overrides)


def import_map(context, session, assets, virtual_path, *, import_models=True, import_lights=True,
               import_light_probes=False, exposure=0.0, attenuation_radius_mult=1.0, always_cast_shadows=False,
               import_point_lights=True, import_spot_lights=True, import_rect_lights=True, import_directional_lights=True, actor_payload=None,
               bake_light_parameters=False, import_splines=True,
               import_landscapes=True, landscape_lod=1, max_landscape_vertices=2_000_000, landscape_layer_preview=False):
    payload = session.umap_actors(virtual_path) if actor_payload is None else actor_payload
    entries = payload.get("actors") or []
    collection = bpy.data.collections.new(PurePosixPath(virtual_path).stem)
    context.scene.collection.children.link(collection)
    collection["ue_source_id"] = session.cache_namespace
    collection["ue_map_path"] = virtual_path
    created, missing = map_import.import_map_entries(
        entries, virtual_path, exposure_mult=2.0 ** exposure, attenuation_radius_mult=attenuation_radius_mult,
        location_scale=assets.scale_factor, always_cast_shadows=always_cast_shadows,
        static_mesh_resolver=assets.static if import_models else None,
        skeletal_mesh_resolver=assets.skeletal if import_models else None,
        import_models=import_models, import_lights=import_lights, import_reflection_probes=import_light_probes,
        import_point_lights=import_point_lights, import_spot_lights=import_spot_lights,
        import_rect_lights=import_rect_lights,
        import_directional_lights=import_directional_lights,
        import_splines=import_splines,
        import_landscapes=import_landscapes, landscape_lod=landscape_lod,
        max_landscape_vertices=max_landscape_vertices, landscape_layer_preview=landscape_layer_preview,
        bake_light_parameters=bake_light_parameters,
        target_collection=collection, game_features=False, component_initializer=assets.initialize_component,
        parent_to_root=False,
        light_texture_loader=session, light_profile="UE4",
    )
    root = next((obj for obj in collection.objects if obj.get("sqex_map_import_root")), None)
    root = root or map_import.ensure_map_import_root(collection, virtual_path)
    map_import.parent_map_objects_to_root(root, [
        obj for obj in collection.all_objects if obj != root and not obj.get("sqex_foliage_source")
    ])
    root["ue_source_id"] = session.cache_namespace
    root["ue_map_path"] = virtual_path
    root["ue_missing_assets"] = json.dumps(sorted(missing), ensure_ascii=False)
    for obj in collection.all_objects:
        obj["ue_source_id"] = session.cache_namespace
    return created, missing
