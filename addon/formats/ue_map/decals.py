"""Flat UV previews of decal materials at the authored component transform."""

import json
import re

import bpy

from ...core.blender.import_cache import find_datablock, remember_datablock
from .lights import apply_component_visibility, float_or_default


def reference_path(reference):
    if isinstance(reference, dict):
        reference = reference.get("ObjectPath") or reference.get("ObjectName") or ""
    path = str(reference or "")
    if "'" in path:
        path = path.split("'", 2)[1]
    return "" if path.casefold() == "none" else path


def _material(path, session):
    if not path:
        return None
    source = getattr(session, "cache_namespace", "loaded-images")
    texture_source = getattr(session, "texture_namespace", source)
    key = (source, texture_source, path.casefold())
    material = find_datablock("materials", "decal-plane-material", key,
        lambda m: (m.get("ue_source_id"), m.get("ue_texture_namespace"), m.get("ue_decal_material", "").casefold()), session)
    if material is not None:
        return material
    if session is None or not hasattr(session, "material_instance"):
        return next((m for m in bpy.data.materials if m.get("ue_virtual_path", "").casefold() == path.casefold()), None)
    from ..unreal_mesh.materials import build_material
    request_path = path
    profile = getattr(session, "profile", None)
    if profile is not None and not profile.gargoyle_profile.startswith("generic:"):
        from ..unreal_package.paths import _game_asset_path_to_virtual_uasset
        request_path = _game_asset_path_to_virtual_uasset(path, profile=profile) or path
        # The title material action returns raw parameter properties. The
        # shared inventory follows effective textures through parent materials.
        inventory = session.request({"action": "generic_material", "assetPath": request_path, "objectPath": path}).get("material") or {}
    else:
        inventory = session.material_instance(request_path)
    base = build_material(path.rsplit("/", 1)[-1].split(".")[0], path, inventory, session)
    # Keep the ordinary surface material and user PBR mappings intact.
    material = base.copy()
    material.name = base.name + "_DecalPlane"
    material["ue_decal_material"] = path
    # The ordinary material cache must never return this approximated decal
    # surface when a mesh requests the original UE material.
    if "ue_virtual_path" in material:
        del material["ue_virtual_path"]
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    textures = [n for n in nodes if n.type == "TEX_IMAGE" and n.image is not None]
    if not shader.inputs["Base Color"].is_linked:
        def score(node):
            name = (node.label + " " + node.get("ue_texture_path", "")).casefold()
            if re.search(r"normal|rough|metal|mask|opacity|occlusion|height|_orm|_n(?:\W|$)", name):
                return -1
            return 1 if re.search(r"albedo|base.?colou?r|diffuse|decal.?colou?r|colou?r|_bc(?:\W|$)|_d(?:\W|$)", name) else 0
        candidates = [n for n in textures if score(n) > 0 or (len(textures) == 1 and score(n) >= 0)]
        if candidates:
            texture = max(candidates, key=score)
            links.new(texture.outputs["Color"], shader.inputs["Base Color"])
            if not shader.inputs["Alpha"].is_linked:
                links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
            material["ue_decal_texture_inference"] = texture.get("ue_texture_path", "")
    if shader.inputs["Base Color"].is_linked and not shader.inputs["Alpha"].is_linked:
        color_source = shader.inputs["Base Color"].links[0].from_node
        if color_source.type == "TEX_IMAGE":
            links.new(color_source.outputs["Alpha"], shader.inputs["Alpha"])
    if not shader.inputs["Normal"].is_linked:
        normal = next((n for n in textures if re.search(r"normal|_n(?:\W|$)", n.label + " " + n.get("ue_texture_path", ""), re.I)), None)
        if normal is not None:
            from ...core.blender.material_nodes import make_normal_map
            mapped = make_normal_map(material.node_tree, links, normal.outputs["Color"], (-160, -220), directx=False)
            links.new(mapped.outputs["Normal"], shader.inputs["Normal"])
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "HASHED"
    material.use_backface_culling = False
    material["ue_decal_texture_status"] = "Textured" if shader.inputs["Base Color"].is_linked else (
        "Textured (normal only)" if shader.inputs["Normal"].is_linked else "No identifiable color texture; inspect retained texture inventory")
    remember_datablock("materials", material, session)
    return material


def create_decal_object(name, props, collection, location_scale=0.01, material_session=None):
    size = props.get("DecalSize") or {}
    # UE's box spans +/- DecalSize in the component's Y/Z plane. X is depth.
    width = abs(float_or_default(size.get("Y"), 256.0) * location_scale)
    height = abs(float_or_default(size.get("Z"), 256.0) * location_scale)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, width, -height), (0, -width, -height),
                      (0, -width, height), (0, width, height)], [], [(0, 3, 2, 1)])
    uv = mesh.uv_layers.new(name="UVMap")
    # DeferredDecal.usf uses local (Z,Y) for (U,V), followed by the same
    # image-space V flip used by imported meshes.
    coords = [(0, 1), (0, 0), (1, 0), (1, 1)]
    for loop in mesh.loops:
        uv.data[loop.index].uv = coords[loop.vertex_index]
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["ue_decal_plane"] = True
    obj["ue_decal_projection"] = "Flat plane at component origin"
    obj["ue_decal_size"] = [float_or_default(size.get(k), default) for k, default in zip("XYZ", (128.0, 256.0, 256.0))]
    path = reference_path(props.get("DecalMaterial"))
    obj["ue_decal_material"] = path
    try:
        material = _material(path, material_session)
        if material is not None:
            mesh.materials.append(material)
            obj["ue_decal_texture_status"] = material.get("ue_decal_texture_status", "Existing material")
        else:
            obj["ue_decal_texture_status"] = "Material unavailable"
    except Exception as exc:
        obj["ue_decal_texture_status"] = "Material unavailable: " + str(exc)
        print(f"[Talisman Decal] {name}: {exc}")
    obj["ue_decal_settings"] = json.dumps({k:props[k] for k in ("DecalColor", "SortOrder", "FadeScreenSize") if k in props})
    apply_component_visibility(obj, props)
    return obj
