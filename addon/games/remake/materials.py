"""Basic Principled-material reconstruction for Remake material instances."""

from __future__ import annotations

import re
from typing import Any, Callable

import bpy

from ...core.blender.material_nodes import image_node as _image_node, image_normal_map, make_bsdf, material_for_texture_source, refresh_material_textures


def _normal_node(nodes, links, image, *, location):
    return image_normal_map(nodes, links, image, label="Normal (DirectX)", location=location)


_MATERIAL_CACHE: dict[str, bpy.types.Material] = {}


def _unwrap(value: Any) -> Any:
    while isinstance(value, dict) and set(value) == {"StructType"}:
        value = value["StructType"]
    return value


def _first(mapping: Any, *keys: str) -> Any:
    mapping = _unwrap(mapping)
    if not isinstance(mapping, dict):
        return None
    values = {str(key).casefold(): value for key, value in mapping.items()}
    return next((values[key.casefold()] for key in keys if key.casefold() in values), None)


def _parameter_name(entry: Any) -> str:
    # Remake stores the name directly as ParameterName.  Keep ParameterInfo as
    # a fallback because inherited instances can be represented either way by
    # different compatible mapping files.
    direct = _first(entry, "ParameterName")
    if direct is not None:
        return str(direct)
    return str(_first(_first(entry, "ParameterInfo", "Parameter"), "Name") or "")


def _role(parameter_name: str) -> str:
    """Drop Remake's layer/index prefix (for example ``0:3:Normal``)."""
    return re.sub(r"[^a-z0-9]", "", parameter_name.rsplit(":", 1)[-1].casefold())


def _texture_parameters(material_data: dict[str, Any]) -> dict[str, str]:
    properties = {
        str(item.get("name")): _unwrap(item.get("value"))
        for item in material_data.get("properties") or []
        if isinstance(item, dict) and item.get("name")
    }
    textures: dict[str, str] = {}
    for entry in properties.get("TextureParameterValues") or []:
        entry = _unwrap(entry)
        path = _first(_first(entry, "ParameterValue", "Value"), "ObjectPath", "Path")
        if path:
            textures[_role(_parameter_name(entry))] = str(path)
    return textures


def build_material(
        material_name: str,
        material_path: str,
        material_data: dict[str, Any],
        image_loader: Callable[[str], bpy.types.Image | None],
) -> bpy.types.Material:
    """Build Remake's currently documented texture-parameter subset.

    Metallic/Roughness/Variant is read as R=metallic, G=roughness; the Variant
    channel is deliberately preserved in the packed image but not interpreted.
    """
    cache_key = material_path.casefold() + "::" + getattr(image_loader, "texture_namespace", "")
    cached = _MATERIAL_CACHE.get(cache_key)
    if cached is not None:
        try:
            if cached.name in bpy.data.materials:
                return refresh_material_textures(cached, image_loader)
        except ReferenceError:
            # Blender invalidates RNA wrappers when File > New removes their
            # datablocks, while this module-level cache outlives that file.
            pass
        _MATERIAL_CACHE.pop(cache_key, None)

    textures = _texture_parameters(material_data)
    material = material_for_texture_source(material_name, material_path, image_loader)
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    material["sqex_virtual_path"] = material_path
    material["ff7r_remake_material"] = True
    for role, path in textures.items():
        material[f"ff7r_remake_texture_{role}"] = path

    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    principled = make_bsdf(material.node_tree, links, output)
    principled.location = (650, 0)

    albedo = _image_node(nodes, image_loader, textures.get("color"), label="Albedo",
                         location=(-900, 420), colour_space="sRGB")
    mr = _image_node(nodes, image_loader, textures.get("metallicroughnessvariant"),
                     label="Metallic / Roughness / Variant", location=(-900, 100),
                     colour_space="Non-Color")
    normal_image = _image_node(nodes, image_loader, textures.get("normal"), label="Normal",
                               location=(-900, -180), colour_space="Non-Color")
    emissive = _image_node(nodes, image_loader, textures.get("ldremissive"), label="LDR Emissive",
                           location=(-900, -480), colour_space="sRGB")
    ao = _image_node(nodes, image_loader, textures.get("occlusion"), label="Ambient Occlusion",
                     location=(-900, -720), colour_space="Non-Color")
    coverage = _image_node(nodes, image_loader, textures.get("coverage"), label="Coverage (Alpha)",
                           location=(-900, -940), colour_space="Non-Color")

    if mr is not None:
        channels = nodes.new("ShaderNodeSeparateColor")
        channels.name = channels.label = "MRV channels (R=metallic, G=roughness, B=variant)"
        channels.location = (-550, 100)
        links.new(mr.outputs["Color"], channels.inputs["Color"])
        links.new(channels.outputs["Red"], principled.inputs["Metallic"])
        links.new(channels.outputs["Green"], principled.inputs["Roughness"])

    if albedo is not None and ao is not None:
        multiply = nodes.new("ShaderNodeMixRGB")
        multiply.blend_type = "MULTIPLY"
        multiply.inputs["Fac"].default_value = 1.0
        multiply.name = multiply.label = "Albedo × Ambient Occlusion"
        multiply.location = (-260, 420)
        links.new(albedo.outputs["Color"], multiply.inputs[1])
        links.new(ao.outputs["Color"], multiply.inputs[2])
        links.new(multiply.outputs["Color"], principled.inputs["Base Color"])
    elif albedo is not None:
        links.new(albedo.outputs["Color"], principled.inputs["Base Color"])

    if (normal := _normal_node(nodes, links, normal_image, location=(-300, -180))) is not None:
        links.new(normal.outputs["Normal"], principled.inputs["Normal"])
    if emissive is not None:
        links.new(emissive.outputs["Color"], principled.inputs["Emission Color"])
    if coverage is not None:
        # Remake's Coverage parameter is an opacity mask, not a conventional
        # colour map.  It is a scalar texture, so feed its greyscale colour
        # output directly into Principled Alpha.
        links.new(coverage.outputs["Color"], principled.inputs["Alpha"])
        try:
            material.surface_render_method = "DITHERED"
        except (AttributeError, TypeError, ValueError):
            # Blender 4.1 and earlier use the now-removed blend_method API.
            try:
                material.blend_method = "BLEND"
            except (AttributeError, TypeError, ValueError):
                pass

    _MATERIAL_CACHE[cache_key] = material
    return material
