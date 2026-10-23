"""Baseline UE4 materials shared by Kingdom Hearts 0.2 and III.

The Kingdom Hearts MaterialInstanceConstants use ordinary named texture
parameters rather than Rebirth's RMI_Surface graph.  This first conversion
therefore intentionally stays small and dependable: every effective texture
parameter is loaded and preserved as a labeled Image Texture node, while the
standard albedo and normal parameters are connected to a Principled BSDF.
Additional KH shader features can be layered onto this stable texture map
without re-reading package data.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import bpy

from ...core.blender.material_nodes import (
    set_color_space as _set_color_space,
    set_channel_packed_alpha as _set_channel_packed_alpha,
    make_normal_map, make_bsdf, material_for_texture_source, refresh_material_textures,
)


_MATERIAL_CACHE: dict[str, bpy.types.Material] = {}
_MATERIAL_VERSION = 1
_ALBEDO_PARAMETER_NAMES = (
    "basecolortexture",
    "basecolortex",
    "basecolor",
    # Sora's form-change clothing material uses this as its diffuse/albedo map.
    "formchangetex0",
    "albedotexture",
    "albedo",
    "diffusetexture",
    "diffuse",
    "colortexture",
    "basetexture",
)
_NORMAL_PARAMETER_NAMES = (
    "normaltexture",
    "normaltex",
    "normalmaptexture",
    "normalmap",
    "normal",
)


def _unwrap_struct(value: Any) -> Any:
    """Remove CUE4Parse's synthetic StructType wrapper from a value."""
    while isinstance(value, dict) and set(value) == {"StructType"}:
        value = value["StructType"]
    return value


def _field(value: Any, *names: str) -> Any:
    value = _unwrap_struct(value)
    if not isinstance(value, dict):
        return None
    folded = {str(key).casefold(): item for key, item in value.items()}
    for name in names:
        item = folded.get(name.casefold())
        if item is not None:
            return item
    return None


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _properties(material_data: dict[str, Any]) -> dict[str, Any]:
    """Turn the gargoyle's tagged property list into a case-preserving lookup."""
    result: dict[str, Any] = {}
    for entry in material_data.get("properties") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name:
            result[name] = _unwrap_struct(entry.get("value"))
    return result


def _parameter_name(entry: Any) -> str:
    entry = _unwrap_struct(entry)
    name = _field(entry, "ParameterName")
    if name is None:
        name = _field(_field(entry, "ParameterInfo", "Parameter"), "Name")
    return str(name or "")


def _texture_parameters(material_data: dict[str, Any]) -> list[tuple[str, str]]:
    """Return MaterialInstance texture parameters with child overrides applied.

    The gargoyle preserves the parent-to-child parameter order.  Keeping the last
    value for a name gives the MaterialInstance's own override priority while
    retaining every effective referenced texture for inspection in Blender.
    """
    effective: dict[str, tuple[str, str]] = {}
    for entry in _properties(material_data).get("TextureParameterValues") or []:
        entry = _unwrap_struct(entry)
        parameter_name = _parameter_name(entry)
        value = _unwrap_struct(_field(entry, "ParameterValue", "Value"))
        object_path = _field(value, "ObjectPath", "Path")
        if not parameter_name or not isinstance(object_path, str) or not object_path:
            continue
        effective[_normalise(parameter_name)] = (parameter_name, object_path)
    return list(effective.values())


def _texture_color_space(parameter_name: str) -> str:
    normalized = _normalise(parameter_name)
    if any(token in normalized for token in ("basecolor", "albedo", "diffuse", "emissive")):
        return "sRGB"
    return "Non-Color"


def _find_role_node(
    texture_nodes: dict[str, bpy.types.Node],
    preferred_names: tuple[str, ...],
    fallback_token: str,
) -> bpy.types.Node | None:
    for name in preferred_names:
        node = texture_nodes.get(name)
        if node is not None:
            return node
    return next(
        (node for name, node in texture_nodes.items()
         if fallback_token in name and "mask" not in name),
        None,
    )


def _existing_material(material_name, material_path, image_loader):
    return material_for_texture_source(material_name, material_path, image_loader)


def build_material(
    material_name: str,
    material_path: str,
    material_data: dict[str, Any],
    image_loader: Callable[[str], bpy.types.Image | None],
) -> bpy.types.Material:
    """Build one simple, inspectable Kingdom Hearts UE material.

    ``image_loader`` is the active PackageAssetSession, so it streams each
    referenced Texture2D from the game, packs it into the Blend, and de-dupes
    loads across all materials in the batch.
    """
    material = _existing_material(material_name, material_path, image_loader)
    if (
        material.get("sqex_kh_material_version") == _MATERIAL_VERSION
        and str(material.get("ue_virtual_path") or "").casefold() == material_path.casefold()
    ):
        return refresh_material_textures(material, image_loader)

    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (720, 0)
    output.label = "Kingdom Hearts material output"
    bsdf = make_bsdf(material.node_tree, links, output)
    bsdf.location = (440, 0)
    bsdf.label = "Kingdom Hearts baseline"

    texture_nodes: dict[str, bpy.types.Node] = {}
    parameter_names: list[str] = []
    for index, (parameter_name, texture_path) in enumerate(_texture_parameters(material_data)):
        parameter_names.append(parameter_name)
        image = image_loader(texture_path)
        if image is None:
            continue
        _set_color_space(image, _texture_color_space(parameter_name))
        _set_channel_packed_alpha(image)
        node = nodes.new("ShaderNodeTexImage")
        node.name = parameter_name
        node.label = parameter_name
        node.location = (-520, -index * 230)
        node.image = image
        node["sqex_texture_parameter"] = parameter_name
        node["sqex_texture_path"] = texture_path
        texture_nodes[_normalise(parameter_name)] = node

    albedo = _find_role_node(texture_nodes, _ALBEDO_PARAMETER_NAMES, "basecolor")
    if albedo is None:
        albedo = _find_role_node(texture_nodes, ("albedo",), "albedo")
    if albedo is None:
        albedo = _find_role_node(texture_nodes, ("diffuse",), "diffuse")
    if albedo is None:
        albedo = _find_role_node(texture_nodes, ("basetexture",), "basetexture")
    if albedo is not None:
        _set_color_space(albedo.image, "sRGB")
        albedo.label = f"Albedo — {albedo.get('sqex_texture_parameter', albedo.name)}"
        links.new(albedo.outputs["Color"], bsdf.inputs["Base Color"])
        material["sqex_albedo_parameter"] = albedo.get("sqex_texture_parameter", albedo.name)

    normal = _find_role_node(texture_nodes, _NORMAL_PARAMETER_NAMES, "normal")
    if normal is not None:
        _set_color_space(normal.image, "Non-Color")
        normal.label = f"Normal — {normal.get('sqex_texture_parameter', normal.name)}"
        # This is the exact DirectX-normal helper used by our established UE
        # material path: Blender 5.2+ sets Normal Map.convention=DIRECTX;
        # older Blender builds insert the RGB Curves green-channel inversion.
        normal_map = make_normal_map(
            material.node_tree, links, normal.outputs["Color"], (-80, -230)
        )
        normal_map.name = "Normal Map"
        normal_map.label = "DirectX Normal Map"
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        material["sqex_normal_parameter"] = normal.get("sqex_texture_parameter", normal.name)

    material["ue_virtual_path"] = material_path
    material["sqex_kh_material_version"] = _MATERIAL_VERSION
    material["sqex_texture_parameter_names"] = parameter_names
    material["sqex_texture_parameter_count"] = len(parameter_names)
    material["sqex_material_source"] = "Kingdom Hearts UE MaterialInstance"
    return material
