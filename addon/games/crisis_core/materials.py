"""Practical Blender material reconstruction for Crisis Core Reunion packages.

This deliberately covers the named texture parameters used by the common
character and environment materials rather than trying to reinterpret Rebirth's
separate RMI_Surface shader family.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import bpy

from ...core.blender.material_nodes import (
    image_node as _image_node, image_normal_map as _normal_map, make_bsdf,
    material_for_texture_source, refresh_material_textures,
)


_MATERIAL_CACHE: dict[str, bpy.types.Material] = {}


def _unwrap(value: Any) -> Any:
    while isinstance(value, dict) and set(value) == {"StructType"}:
        value = value["StructType"]
    return value


def _first(mapping: Any, *keys: str) -> Any:
    mapping = _unwrap(mapping)
    if not isinstance(mapping, dict):
        return None
    folded = {str(key).casefold(): value for key, value in mapping.items()}
    for key in keys:
        value = folded.get(key.casefold())
        if value is not None:
            return value
    return None


def _parameter_name(entry: Any) -> str:
    info = _unwrap(_first(entry, "ParameterInfo", "Parameter"))
    return str(_first(info, "Name") or "")


def _object_path(value: Any) -> str:
    value = _unwrap(value)
    return str(_first(value, "ObjectPath", "Path") or "")


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _is_rmae(texture_path: str | None) -> bool:
    """RMAE's fourth channel is the documented emissive mask."""
    if not texture_path:
        return False
    stem = texture_path.split(":", 1)[0].rsplit("/", 1)[-1].split(".", 1)[0]
    return stem.casefold().endswith("_rmae")


def _colour(value: Any) -> tuple[float, float, float, float] | None:
    value = _unwrap(value)
    if isinstance(value, (tuple, list)) and 3 <= len(value) <= 4:
        channels = list(value) + [1.0]
    elif isinstance(value, dict):
        channels = [
            _first(value, "R", "X"),
            _first(value, "G", "Y"),
            _first(value, "B", "Z"),
            _first(value, "A", "W"),
        ]
        if any(channel is None for channel in channels[:3]):
            nested = _first(value, "Color", "Value")
            if nested is not value:
                return _colour(nested)
        if channels[3] is None:
            channels[3] = 1.0
    else:
        return None
    try:
        return tuple(float(channel) for channel in channels[:4])
    except (TypeError, ValueError):
        return None


def _parameter_values(material_data: dict[str, Any]):
    properties = {
        str(item.get("name")): _unwrap(item.get("value"))
        for item in material_data.get("properties") or []
        if isinstance(item, dict) and item.get("name")
    }
    textures: dict[str, str] = {}
    vectors: dict[str, tuple[float, float, float, float]] = {}
    scalars: dict[str, float] = {}
    for entry in properties.get("TextureParameterValues") or []:
        entry = _unwrap(entry)
        name = _normalise(_parameter_name(entry))
        path = _object_path(_first(entry, "ParameterValue", "Value"))
        if name and path:
            textures[name] = path
    for entry in properties.get("VectorParameterValues") or []:
        entry = _unwrap(entry)
        name = _normalise(_parameter_name(entry))
        value = _colour(_first(entry, "ParameterValue", "Value"))
        if name and value is not None:
            vectors[name] = value
    for entry in properties.get("ScalarParameterValues") or []:
        entry = _unwrap(entry)
        name = _normalise(_parameter_name(entry))
        try:
            value = float(_unwrap(_first(entry, "ParameterValue", "Value")))
        except (TypeError, ValueError):
            continue
        if name:
            scalars[name] = value
    return textures, vectors, scalars


def build_material(
        material_name: str,
        material_path: str,
        material_data: dict[str, Any],
        image_loader: Callable[[str], bpy.types.Image | None],
) -> bpy.types.Material:
    """Build the documented Crisis Core texture parameter subset in Blender."""
    cache_key = material_path.casefold() + "::" + getattr(image_loader, "texture_namespace", "")
    cached = _MATERIAL_CACHE.get(cache_key)
    if cached is not None and cached.name in bpy.data.materials:
        return refresh_material_textures(cached, image_loader)

    textures, vectors, scalars = _parameter_values(material_data)
    material = material_for_texture_source(material_name, material_path, image_loader)
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    material["sqex_virtual_path"] = material_path
    material["ff7r_crisis_core_material"] = True
    material["ff7r_texture_albedo"] = textures.get("texturealbedo", "")
    material["ff7r_texture_normal"] = textures.get("texturenormal", "")
    material["ff7r_texture_detail_normal"] = textures.get("detailnormal", "")
    material["ff7r_texture_rma"] = textures.get("texturerma", "")
    material["ff7r_texture_emissive"] = textures.get("textureemissive", "")

    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    bsdf = make_bsdf(tree, links, output)
    bsdf.location = (650, 0)

    albedo = _image_node(nodes, image_loader, textures.get("texturealbedo"),
                         label="TextureAlbedo", location=(-900, 420), colour_space="sRGB")

    base_normal_image = _image_node(
        nodes, image_loader, textures.get("texturenormal"), label="TextureNormal",
        location=(-900, 120), colour_space="Non-Color",
    )
    detail_normal_image = _image_node(
        nodes, image_loader, textures.get("detailnormal"), label="DetailNormal",
        location=(-900, -160), colour_space="Non-Color",
    )
    base_normal = _normal_map(nodes, links, base_normal_image,
                              label="TextureNormal Map", location=(-550, 120))
    detail_normal = _normal_map(nodes, links, detail_normal_image,
                                label="DetailNormal Map", location=(-550, -160),
                                uv_map="Coordinate1")
    if base_normal is not None and detail_normal is not None:
        add = nodes.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        add.label = "Base + Detail Normal"
        add.location = (-250, 40)
        subtract_neutral = nodes.new("ShaderNodeVectorMath")
        subtract_neutral.operation = "SUBTRACT"
        subtract_neutral.label = "Subtract neutral detail normal"
        subtract_neutral.location = (-60, 40)
        subtract_neutral.inputs[1].default_value = (0.0, 0.0, 1.0)
        normalize = nodes.new("ShaderNodeVectorMath")
        normalize.operation = "NORMALIZE"
        normalize.label = "Combined Normal"
        normalize.location = (170, 40)
        links.new(base_normal.outputs["Normal"], add.inputs[0])
        links.new(detail_normal.outputs["Normal"], add.inputs[1])
        links.new(add.outputs["Vector"], subtract_neutral.inputs[0])
        links.new(subtract_neutral.outputs["Vector"], normalize.inputs[0])
        links.new(normalize.outputs["Vector"], bsdf.inputs["Normal"])
    elif base_normal is not None:
        links.new(base_normal.outputs["Normal"], bsdf.inputs["Normal"])
    elif detail_normal is not None:
        links.new(detail_normal.outputs["Normal"], bsdf.inputs["Normal"])

    rma_path = textures.get("texturerma")
    rma = _image_node(nodes, image_loader, rma_path, label="TextureRMA",
                      location=(-900, -470), colour_space="Non-Color")
    rma_channels = None
    if rma is not None:
        rma_channels = nodes.new("ShaderNodeSeparateColor")
        rma_channels.label = "RMA channels (R=roughness, G=metallic, B=AO)"
        rma_channels.location = (-550, -470)
        links.new(rma.outputs["Color"], rma_channels.inputs["Color"])
        links.new(rma_channels.outputs["Red"], bsdf.inputs["Roughness"])
        links.new(rma_channels.outputs["Green"], bsdf.inputs["Metallic"])

    # Principled has no dedicated ambient-occlusion socket.  Match the usual
    # practical representation by multiplying the material's base colour by
    # the documented blue AO channel of TextureRMA.
    if albedo is not None and rma_channels is not None:
        ao_base_colour = nodes.new("ShaderNodeMixRGB")
        ao_base_colour.blend_type = "MULTIPLY"
        ao_base_colour.inputs["Fac"].default_value = 1.0
        ao_base_colour.label = "TextureAlbedo × RMA ambient occlusion"
        ao_base_colour.location = (-260, 420)
        links.new(albedo.outputs["Color"], ao_base_colour.inputs[1])
        links.new(rma_channels.outputs["Blue"], ao_base_colour.inputs[2])
        links.new(ao_base_colour.outputs["Color"], bsdf.inputs["Base Color"])
    elif albedo is not None:
        links.new(albedo.outputs["Color"], bsdf.inputs["Base Color"])
    elif rma_channels is not None:
        links.new(rma_channels.outputs["Blue"], bsdf.inputs["Base Color"])

    # The fourth TextureAlbedo channel is material opacity, not an emissive
    # mask. Dithered transparency gives the Principled alpha a usable material
    # render path in current Blender without treating a cutout as emission.
    if albedo is not None:
        links.new(albedo.outputs["Alpha"], bsdf.inputs["Alpha"])
        try:
            material.surface_render_method = "DITHERED"
        except (AttributeError, TypeError, ValueError):
            pass

    emissive = _image_node(nodes, image_loader, textures.get("textureemissive"),
                           label="TextureEmissive", location=(-900, -760), colour_space="sRGB")
    emissive_colour = vectors.get("emissivecolor", (1.0, 1.0, 1.0, 1.0))
    colour = nodes.new("ShaderNodeRGB")
    colour.label = "EmissiveColor"
    colour.location = (-550, -700)
    colour.outputs["Color"].default_value = emissive_colour
    if emissive is not None:
        multiply_colour = nodes.new("ShaderNodeMixRGB")
        multiply_colour.blend_type = "MULTIPLY"
        multiply_colour.inputs["Fac"].default_value = 1.0
        multiply_colour.label = "TextureEmissive × EmissiveColor"
        multiply_colour.location = (-100, -700)
        links.new(emissive.outputs["Color"], multiply_colour.inputs[1])
        links.new(colour.outputs["Color"], multiply_colour.inputs[2])
        links.new(multiply_colour.outputs["Color"], bsdf.inputs["Emission Color"])
    elif "emissivecolor" in vectors:
        links.new(colour.outputs["Color"], bsdf.inputs["Emission Color"])

    emissive_intensity = float(scalars.get("emissiveint", 1.0))
    if rma is not None and _is_rmae(rma_path) and (
            emissive is not None or "emissivecolor" in vectors):
        multiply_strength = nodes.new("ShaderNodeMath")
        multiply_strength.operation = "MULTIPLY"
        multiply_strength.label = "RMAE alpha × EmissiveInt"
        multiply_strength.location = (260, -430)
        multiply_strength.inputs[1].default_value = emissive_intensity
        links.new(rma.outputs["Alpha"], multiply_strength.inputs[0])
        links.new(multiply_strength.outputs[0], bsdf.inputs["Emission Strength"])
    elif emissive is not None or "emissivecolor" in vectors:
        bsdf.inputs["Emission Strength"].default_value = emissive_intensity

    _MATERIAL_CACHE[cache_key] = material
    return material
