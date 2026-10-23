"""Basic Principled-material reconstruction for Remake material instances."""

from __future__ import annotations

import re
from typing import Any, Callable

import bpy

from ...core.blender.material_nodes import image_node as _image_node, image_normal_map, make_bsdf, material_for_texture_source, refresh_material_textures
from ...core.blender.material_nodes import apply_world_grid_material, is_world_grid_material
from ..rebirth.materials.rmi_surface import _renderer_constant_texture as _rebirth_renderer_constant_texture


def _renderer_constant_texture(path):
    constant = _rebirth_renderer_constant_texture(path)
    if constant is not None:
        return constant
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].split(".", 1)[0]
    # Remake also has linear RGBA constants with no format suffix. Restrict
    # this interpretation to the renderer's constant-texture directory.
    if "/renderer/texture/" in normalized.casefold() and re.fullmatch(r"[0-9a-fA-F]{8}", name):
        return _rebirth_renderer_constant_texture(name + "_HDR")
    return None


def _texture_node(nodes, image_loader, path, *, label, location, colour_space):
    constant = _renderer_constant_texture(path) if path else None
    if constant is None:
        return _image_node(nodes, image_loader, path, label=label, location=location,
                           colour_space=colour_space)
    scalar = _texture_name(path).endswith("_bc4")
    node = nodes.new("ShaderNodeValue" if scalar else "ShaderNodeRGB")
    node.name = label
    node.label = f"{label} [UE {'scalar' if scalar else 'color'} constant]"
    node.location = location
    node.outputs[0].default_value = constant[0] if scalar else constant
    return node


def _texture_source_key(node):
    if node.type == "VALUE":
        return ("scalar", node.outputs[0].default_value)
    if node.type == "RGB":
        return ("constant", tuple(node.outputs["Color"].default_value))
    return ("image", node.image.as_pointer()) if node.image else ("path", node.get("ue_texture_path"))


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


def _texture_parameter_entries(material_data: dict[str, Any]) -> list[tuple[str, str]]:
    properties = {
        str(item.get("name")): _unwrap(item.get("value"))
        for item in material_data.get("properties") or []
        if isinstance(item, dict) and item.get("name")
    }
    textures: dict[str, tuple[str, str]] = {}
    for entry in properties.get("TextureParameterValues") or []:
        entry = _unwrap(entry)
        path = _first(_first(entry, "ParameterValue", "Value"), "ObjectPath", "Path")
        if path:
            name = _parameter_name(entry)
            # Parent values precede instance overrides. Keep separate layers
            # for the inventory even when the shader uses only one role.
            textures.pop(name.casefold(), None)
            textures[name.casefold()] = (name, str(path))
    return list(textures.values())


def _texture_parameters(material_data: dict[str, Any]) -> dict[str, str]:
    return {_role(name): path for name, path in _texture_parameter_entries(material_data)}


def _texture_name(path: str) -> str:
    # Match bare names as well as Unreal object paths, including '.0' exports.
    return str(path).strip("'").rsplit("'", 1)[-1].replace("\\", "/").rsplit("/", 1)[-1].split(".", 1)[0].casefold()


def _apply_texture_uv_maps(material, material_data):
    properties = {
        str(item.get("name")): _unwrap(item.get("value"))
        for item in material_data.get("properties") or []
        if isinstance(item, dict) and item.get("name")
    }
    channels = {}
    for entry in properties.get("TextureStreamingData") or []:
        name = _first(entry, "TextureName")
        channel = _first(entry, "UVChannelIndex")
        if name and isinstance(channel, int) and not isinstance(channel, bool) and channel >= 0:
            channels[_texture_name(name)] = channel
    nodes, links = material.node_tree.nodes, material.node_tree.links
    uv_nodes = {}
    for node in list(nodes):
        if node.type != "TEX_IMAGE":
            continue
        path = node.get("ue_texture_path") or (node.image.name if node.image else "")
        channel = channels.get(_texture_name(path))
        if channel is None:
            continue
        uv = uv_nodes.get(channel)
        if uv is None:
            uv = nodes.new("ShaderNodeUVMap")
            # Conventional Remake mesh imports name UV layers Coordinate0, ...
            uv.uv_map = f"Coordinate{channel}"
            uv.name = uv.label = f"UV Channel {channel}"
            uv.location = (-1600, 420 - len(uv_nodes) * 220)
            uv_nodes[channel] = uv
        links.new(uv.outputs["UV"], node.inputs["Vector"])
        node["ue_uv_channel_index"] = channel
    # SamplingScale describes texture streaming density, not UV tiling.


def _preserve_unused_textures(nodes, entries, source_nodes, image_loader):
    """Keep one orphan per unused image, preferring any connected node."""
    connected_images = {
        _texture_source_key(node)
        for node in nodes if node.type in {"TEX_IMAGE", "RGB", "VALUE"}
        and any(socket.is_linked for socket in node.outputs)
    }
    seen_images = set(connected_images)
    seen_paths = set()
    orphan_count = 0
    for path, node in source_nodes:
        if node is None:
            continue
        node["ue_texture_path"] = path
        seen_paths.add(path.casefold())
        if any(socket.is_linked for socket in node.outputs):
            continue
        image_key = _texture_source_key(node)
        if image_key in seen_images:
            nodes.remove(node)
        else:
            seen_images.add(image_key)
            orphan_count += 1
    for name, path in entries:
        if path.casefold() in seen_paths:
            continue
        seen_paths.add(path.casefold())
        constant = _renderer_constant_texture(path)
        if constant is not None:
            # RGB socket storage uses float32; compare with existing nodes in
            # that same representation so duplicate constants are suppressed.
            node = _texture_node(nodes, image_loader, path, label=name,
                                 location=(-1250, -1440 - orphan_count * 300), colour_space="Non-Color")
            image_key = _texture_source_key(node)
            if image_key in seen_images:
                nodes.remove(node)
                continue
            seen_images.add(image_key)
            node["ue_texture_path"] = path
            orphan_count += 1
            continue
        image = image_loader(path)
        if image is not None:
            image_key = ("image", image.as_pointer())
            if image_key in seen_images:
                continue
            seen_images.add(image_key)
        node = nodes.new("ShaderNodeTexImage")
        node.name = node.label = name or path.rsplit("/", 1)[-1]
        node.location = (-1250, -1440 - orphan_count * 300)
        node["ue_texture_path"] = path
        node.image = image
        if image is None:
            node["ue_texture_unavailable"] = True
        orphan_count += 1


def build_material(
        material_name: str,
        material_path: str,
        material_data: dict[str, Any],
        image_loader: Callable[[str], bpy.types.Image | None],
) -> bpy.types.Material:
    """Connect known Remake texture roles and preserve unused images as nodes.

    Metallic/Roughness/Variant is read as R=metallic, G=roughness, with blue
    multiplying the emission color when an emission texture is present.
    """
    if is_world_grid_material(material_path):
        material = material_for_texture_source(material_name, material_path, image_loader)
        apply_world_grid_material(material, material_path)
        return material
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
    material["ue_virtual_path"] = material_path
    material["ff7r_remake_material"] = True
    for role, path in textures.items():
        material[f"ff7r_remake_texture_{role}"] = path

    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    principled = make_bsdf(material.node_tree, links, output)
    principled.location = (650, 0)

    albedo = _texture_node(nodes, image_loader, textures.get("color"), label="Albedo",
                         location=(-900, 420), colour_space="sRGB")
    mr = _texture_node(nodes, image_loader, textures.get("metallicroughnessvariant"),
                     label="Metallic / Roughness / Variant", location=(-900, 100),
                     colour_space="Non-Color")
    normal_image = _texture_node(nodes, image_loader, textures.get("normal"), label="Normal",
                               location=(-900, -180), colour_space="Non-Color")
    ldr_emissive = _texture_node(nodes, image_loader, textures.get("ldremissive"), label="LDR Emissive",
                           location=(-900, -480), colour_space="sRGB")
    emissive = _texture_node(nodes, image_loader, textures.get("emissive"), label="Emissive",
                            location=(-900, -1380), colour_space="sRGB")
    ao = _texture_node(nodes, image_loader, textures.get("occlusion"), label="Ambient Occlusion",
                     location=(-900, -720), colour_space="Non-Color")
    coverage = _texture_node(nodes, image_loader, textures.get("coverage"), label="Coverage (Alpha)",
                           location=(-900, -940), colour_space="Non-Color")
    opacity = _texture_node(nodes, image_loader, textures.get("opacity"), label="Opacity (Alpha)",
                          location=(-900, -1160), colour_space="Non-Color")

    if mr is not None:
        channels = nodes.new("ShaderNodeSeparateColor")
        channels.name = channels.label = "MRV channels (R=metallic, G=roughness, B=variant)"
        channels.location = (-550, 100)
        links.new(mr.outputs[0], channels.inputs["Color"])
        links.new(channels.outputs["Red"], principled.inputs["Metallic"])
        links.new(channels.outputs["Green"], principled.inputs["Roughness"])

    if albedo is not None and ao is not None:
        multiply = nodes.new("ShaderNodeMixRGB")
        multiply.blend_type = "MULTIPLY"
        multiply.inputs["Fac"].default_value = 1.0
        multiply.name = multiply.label = "Albedo × Ambient Occlusion"
        multiply.location = (-260, 420)
        links.new(albedo.outputs[0], multiply.inputs[1])
        links.new(ao.outputs[0], multiply.inputs[2])
        links.new(multiply.outputs["Color"], principled.inputs["Base Color"])
    elif albedo is not None:
        links.new(albedo.outputs[0], principled.inputs["Base Color"])

    if (normal := _normal_node(nodes, links, normal_image, location=(-300, -180))) is not None:
        links.new(normal.outputs["Normal"], principled.inputs["Normal"])
    emission_texture = emissive if emissive is not None else ldr_emissive
    principled.inputs["Emission Strength"].default_value = 0.0
    if emission_texture is not None:
        emission_color = emission_texture.outputs[0]
        if mr is not None:
            emission_mask = nodes.new("ShaderNodeMixRGB")
            emission_mask.name = emission_mask.label = "Emission × MRV Blue"
            emission_mask.blend_type = "MULTIPLY"
            emission_mask.inputs["Fac"].default_value = 1.0
            emission_mask.location = (50, -480)
            links.new(emission_color, emission_mask.inputs[1])
            links.new(channels.outputs["Blue"], emission_mask.inputs[2])
            emission_color = emission_mask.outputs["Color"]
        links.new(emission_color, principled.inputs["Emission Color"])
        principled.inputs["Emission Strength"].default_value = 1.0
        light_path = nodes.new("ShaderNodeLightPath")
        light_path.name = light_path.label = "Camera-only Emission"
        light_path.location = (350, -480)
        links.new(light_path.outputs["Is Camera Ray"], principled.inputs["Emission Strength"])
    alpha_texture = opacity if opacity is not None else coverage
    if alpha_texture is not None:
        # Opacity and Coverage are scalar masks. Prefer explicit Opacity when
        # both parameters exist, and feed the greyscale colour into Alpha.
        links.new(alpha_texture.outputs[0], principled.inputs["Alpha"])
        try:
            material.surface_render_method = "DITHERED"
        except (AttributeError, TypeError, ValueError):
            # Blender 4.1 and earlier expose transparency through blend_method.
            try:
                material.blend_method = "BLEND"
            except (AttributeError, TypeError, ValueError):
                pass

    _preserve_unused_textures(nodes, _texture_parameter_entries(material_data), [
        (textures.get(role), node) for role, node in (
            ("color", albedo), ("metallicroughnessvariant", mr), ("normal", normal_image),
            ("ldremissive", ldr_emissive), ("emissive", emissive), ("occlusion", ao),
            ("coverage", coverage), ("opacity", opacity),
        )
    ], image_loader)
    _apply_texture_uv_maps(material, material_data)
    _MATERIAL_CACHE[cache_key] = material
    return material
