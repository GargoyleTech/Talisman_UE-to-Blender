"""Basic Principled-material reconstruction for Remake material instances."""

from __future__ import annotations

import re
from typing import Any, Callable

import bpy


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


def _image_node(nodes, image_loader: Callable[[str], bpy.types.Image | None], path: str | None,
                *, label: str, location: tuple[float, float], colour_space: str):
    if not path or (image := image_loader(path)) is None:
        return None
    try:
        image.colorspace_settings.name = colour_space
    except (AttributeError, TypeError, ValueError):
        pass
    node = nodes.new("ShaderNodeTexImage")
    node.name = node.label = label
    node.location = location
    node.image = image
    return node


def _normal_node(nodes, links, image, *, location: tuple[float, float]):
    if image is None:
        return None
    normal = nodes.new("ShaderNodeNormalMap")
    normal.name = normal.label = "Normal (DirectX)"
    normal.location = location
    if bpy.app.version >= (5, 2, 0) and hasattr(normal, "convention"):
        normal.convention = "DIRECTX"
        links.new(image.outputs["Color"], normal.inputs["Color"])
        return normal

    # Earlier Blender Normal Map nodes assume OpenGL normals. Convert UE's
    # DirectX green channel once, before its normal-map decoder.
    separate = nodes.new("ShaderNodeSeparateColor")
    separate.name = separate.label = "Normal DirectX channels"
    separate.location = (location[0] - 430, location[1])
    invert_green = nodes.new("ShaderNodeMath")
    invert_green.operation = "SUBTRACT"
    invert_green.name = invert_green.label = "Invert DirectX green"
    invert_green.location = (location[0] - 230, location[1] - 100)
    invert_green.inputs[0].default_value = 1.0
    combine = nodes.new("ShaderNodeCombineColor")
    combine.name = combine.label = "Normal OpenGL colour"
    combine.location = (location[0] - 25, location[1])
    links.new(image.outputs["Color"], separate.inputs["Color"])
    links.new(separate.outputs["Red"], combine.inputs["Red"])
    links.new(separate.outputs["Green"], invert_green.inputs[1])
    links.new(invert_green.outputs[0], combine.inputs["Green"])
    links.new(separate.outputs["Blue"], combine.inputs["Blue"])
    links.new(combine.outputs["Color"], normal.inputs["Color"])
    return normal


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
    cache_key = material_path.casefold()
    cached = _MATERIAL_CACHE.get(cache_key)
    if cached is not None:
        try:
            if cached.name in bpy.data.materials:
                return cached
        except ReferenceError:
            # Blender invalidates RNA wrappers when File > New removes their
            # datablocks, while this module-level cache outlives that file.
            pass
        _MATERIAL_CACHE.pop(cache_key, None)

    textures = _texture_parameters(material_data)
    material = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    material["ff7r_virtual_path"] = material_path
    material["ff7r_remake_material"] = True
    for role, path in textures.items():
        material[f"ff7r_remake_texture_{role}"] = path

    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (650, 0)
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

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
