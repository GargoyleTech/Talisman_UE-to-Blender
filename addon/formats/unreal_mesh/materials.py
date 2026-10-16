"""Keep discovered Unreal textures as unlinked, labelled image nodes."""

import json
import re

import bpy

from ...core.blender.material_nodes import scalar_channel_socket as _scalar_channel_socket, make_bsdf, make_normal_map


def _parameter_key(value):
    return str(value or "").strip().casefold()


def _parameter_candidates(value):
    """Normalize a legacy name or an ordered list with optional channels."""
    values = value if isinstance(value, (list, tuple)) else (value,)
    candidates = []
    for candidate in values:
        if isinstance(candidate, dict):
            name = str(candidate.get("parameter") or "").strip()
            channel = str(candidate.get("channel") or "").upper()
        else:
            name = str(candidate or "").strip()
            channel = ""
        parameter = _parameter_key(name)
        if parameter:
            candidates.append((name, parameter, channel))
    return candidates


def _match_parameter_node(parameter_nodes, parameter):
    """Match normalized names, treating only '*' as a wildcard.

    Inventory order breaks ties when a pattern matches multiple parameters.
    """
    if "*" not in parameter:
        return parameter_nodes.get(parameter)
    pattern = re.compile(".*".join(re.escape(part) for part in parameter.split("*")), re.DOTALL)
    return next((node for name, node in parameter_nodes.items() if pattern.fullmatch(name)), None)


def _apply_pbr_mapping(material, nodes, output, parameter_nodes, mapping, warnings):
    """Build a conventional Principled graph from explicitly mapped parameters."""
    if not mapping:
        return
    selected = {}
    for slot in ("albedo", "normal", "metalness", "roughness", "alpha"):
        candidates = _parameter_candidates(mapping.get(slot))
        if not candidates:
            continue
        selected_candidate = next(
            (
                (node, channel)
                for _name, parameter, channel in candidates
                if (node := _match_parameter_node(parameter_nodes, parameter)) is not None
            ),
            None,
        )
        if selected_candidate is None:
            names = ", ".join(f"'{name}'" for name, _parameter, _channel in candidates)
            warnings.append(
                f"Profile PBR mapping could not find any texture parameter for {slot}: {names}."
            )
        else:
            selected[slot] = selected_candidate
    if not selected:
        return

    links = material.node_tree.links
    principled = make_bsdf(material.node_tree, links, output)
    principled.name = principled.label = "Profile PBR"
    principled.location = (120, 0)

    albedo = selected.get("albedo")
    if albedo is not None:
        links.new(albedo[0].outputs["Color"], principled.inputs["Base Color"])

    normal = selected.get("normal")
    if normal is not None:
        normal_map = make_normal_map(material.node_tree, links, normal[0].outputs["Color"], (-160, -220), directx=False)
        normal_map.name = normal_map.label = "Profile Normal Map"
        normal_map.location = (-160, -220)
        links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])

    for slot, input_name in (("metalness", "Metallic"), ("roughness", "Roughness"), ("alpha", "Alpha")):
        selected_scalar = selected.get(slot)
        if selected_scalar is None:
            continue
        texture_node, channel = selected_scalar
        socket = _scalar_channel_socket(
            nodes,
            links,
            texture_node,
            channel or mapping.get(f"{slot}_channel", "A" if slot == "alpha" else "R"),
        )
        if socket is not None:
            links.new(socket, principled.inputs[input_name])

    if "alpha" in selected and hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    material["ue_pbr_mapping"] = json.dumps(mapping, ensure_ascii=False, sort_keys=True)


def build_material(material_name, material_path, material_data, image_loader):
    source_id = image_loader.cache_namespace
    texture_namespace = getattr(image_loader, "texture_namespace", source_id)
    material = next((
        item for item in bpy.data.materials
        if item.get("ue_source_id") == source_id
        and item.get("ue_texture_namespace", source_id) == texture_namespace
        and item.get("sqex_virtual_path", "").casefold() == material_path.casefold()
    ), None)
    if material is None:
        material = bpy.data.materials.new(material_name)
    if material.get("ue_texture_inventory_complete"):
        from ...core.blender.material_nodes import refresh_material_textures
        return refresh_material_textures(material, image_loader)
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    material["ue_source_id"] = source_id
    material["ue_texture_namespace"] = texture_namespace
    material["sqex_virtual_path"] = material_path
    material["ue_material_type"] = material_data.get("type") or ""
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    warnings = list(material_data.get("warnings") or [])
    parameter_nodes = {}
    for warning in warnings:
        print(f"[Unreal material WARNING] {material_path}: {warning}")
    for index, texture in enumerate(material_data.get("textures") or []):
        path = texture.get("path") or ""
        if not path:
            continue
        labels = texture.get("labels") or []
        node = nodes.new("ShaderNodeTexImage")
        node.name = node.label = ", ".join(labels) or path.rsplit("/", 1)[-1].split(".")[0]
        node.location = ((index % 4) * 280 - 1120, -(index // 4) * 340)
        node.width = 240
        node["ue_texture_path"] = path
        node["ue_parameter_names"] = json.dumps(labels, ensure_ascii=False)
        for label in labels:
            parameter_nodes.setdefault(_parameter_key(label), node)
        node.image = image_loader(path)
        if node.image is None:
            node["ue_texture_unavailable"] = True
            warnings.append(f"Could not decode texture: {path}")
    _apply_pbr_mapping(
        material,
        nodes,
        output,
        parameter_nodes,
        getattr(image_loader, "pbr_mapping", None),
        warnings,
    )
    material["ue_texture_warnings"] = json.dumps(warnings, ensure_ascii=False)
    material["ue_texture_inventory_complete"] = True
    return material
