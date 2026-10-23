"""Blender backend for unsimulated Niagara mesh/material resources only."""

from dataclasses import dataclass
import json
from pathlib import PurePosixPath

import bpy

from ..unreal_package.mesh_import import import_static_mesh_datablock
from ..unreal_package.paths import _game_asset_path_to_virtual_uasset
from ..unreal_mesh.materials import build_material


@dataclass
class ResourceImportResult:
    collection: object = None
    objects: tuple = ()
    mesh_count: int = 0
    skipped_renderers: int = 0
    warnings: tuple = ()
    failures: tuple = ()


def import_mesh_resources(context, package, session, *, profile, scale_factor=0.01):
    """Create one object per mesh/material variant, sharing source geometry.

    This consumes a normalized package, not bridge JSON. A later Geometry Nodes
    backend can consume its renderer/emitter references without changing this
    source-resource loader. Particle transforms, bounds and spawning are never
    applied to these source meshes.
    """
    skipped = sum(r.source.type != "NiagaraMeshRendererProperties" for r in package.renderers)
    warnings = list(package.warnings)
    if not package.resources:
        return ResourceImportResult(skipped_renderers=skipped, warnings=tuple(warnings))
    collection = bpy.data.collections.new(PurePosixPath(package.asset_path).stem + " · Niagara meshes")
    context.collection.children.link(collection)
    meshes, materials, objects, failures = {}, {}, [], []
    try:
        for resource in package.resources:
            obj = None
            try:
                key = resource.mesh_path.casefold()
                if key not in meshes:
                    virtual_path = _game_asset_path_to_virtual_uasset(resource.mesh_path, profile=profile)
                    if not virtual_path:
                        raise ValueError(f"Unsupported mesh reference: {resource.mesh_path}")
                    mesh = import_static_mesh_datablock(
                        context, session.static_mesh(virtual_path), virtual_path,
                        scale_factor=scale_factor, material_session=session,
                        material_builder=build_material, game_features=False,
                    )
                    mesh["ue_virtual_path"] = virtual_path
                    mesh["ue_source_id"] = session.cache_namespace
                    meshes[key] = mesh
                mesh = meshes[key]
                # Object-linked overrides preserve a shared mesh's section
                # assignments and default materials across different renderers.
                while len(mesh.materials) < len(resource.material_paths):
                    mesh.materials.append(None)
                obj = bpy.data.objects.new(mesh.name, mesh)
                collection.objects.link(obj)
                for index, path in enumerate(resource.material_paths):
                    if not path:
                        continue
                    material_key = path.casefold()
                    if material_key not in materials:
                        material_name = path.rsplit("/", 1)[-1].split(".")[0]
                        materials[material_key] = build_material(
                            material_name, path, session.material_instance(path), session,
                        )
                    slot = obj.material_slots[index]
                    slot.link = 'OBJECT'
                    slot.material = materials[material_key]
                obj["ue_niagara_asset"] = package.asset_path
                obj["ue_niagara_mesh_path"] = resource.mesh_path
                obj["ue_niagara_material_overrides"] = json.dumps(resource.material_paths)
                obj["ue_niagara_sources"] = json.dumps([
                    {"emitter": ref.emitter_path, "renderer": ref.renderer_path,
                     "rendererExport": ref.renderer_export, "meshIndex": ref.mesh_index}
                    for ref in resource.references
                ])
                obj["ue_source_id"] = session.cache_namespace
                obj["ue_virtual_path"] = mesh["ue_virtual_path"]
                obj["ue_import_scale"] = scale_factor
                objects.append(obj)
            except Exception as exc:
                if obj is not None:
                    bpy.data.objects.remove(obj, do_unlink=True)
                failure = f"{resource.mesh_path}: {exc}"
                failures.append(failure)
                print(f"[Niagara resource WARNING] {failure}")
        for key, mesh in list(meshes.items()):
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
                del meshes[key]
        if not objects:
            bpy.data.collections.remove(collection)
            return ResourceImportResult(skipped_renderers=skipped, warnings=tuple(warnings), failures=tuple(failures))
        collection["ue_niagara_asset"] = package.asset_path
        collection["ue_source_id"] = session.cache_namespace
        collection["ue_niagara_import_mode"] = "MESH_RESOURCES_ONLY"
        collection["ue_niagara_manifest"] = json.dumps(package.manifest(), ensure_ascii=False)
        collection["ue_niagara_failures"] = json.dumps(failures)
        collection["ue_import_scale"] = scale_factor
        for selected in context.selected_objects:
            selected.select_set(False)
        for obj in objects:
            obj.select_set(True)
        context.view_layer.objects.active = objects[0]
        return ResourceImportResult(collection, tuple(objects), len({obj.data.as_pointer() for obj in objects}),
                                    skipped, tuple(warnings), tuple(failures))
    except Exception:
        for obj in objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in meshes.values():
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(collection)
        raise
