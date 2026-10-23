"""Build a default surface and link discovered textures only when mapped."""

import json
import re

import bpy

from ...core.blender.import_cache import find_datablock, remember_datablock

from ...core.blender.material_nodes import scalar_channel_socket as _scalar_channel_socket, make_bsdf, make_normal_map


def _parameter_key(value):
    return str(value or "").strip().casefold()


def _merge_texture_labels(node, labels, *, rename=True):
    """Keep every parameter alias when inventory entries share a texture."""
    names = list(dict.fromkeys(json.loads(node.get("ue_parameter_names", "[]")) + labels))
    node["ue_parameter_names"] = json.dumps(names, ensure_ascii=False)
    label = ", ".join(names) or node["ue_texture_path"].rsplit("/", 1)[-1].split(".")[0]
    if rename:
        node.name = label
    node.label = ("Volume slice atlas: " if node.get("ue_texture_layout") == "VOLUME_ATLAS" else "") + label


def _deduplicate_inventory_nodes(material):
    """Repair cached inventories without rebuilding their shader connections."""
    tree = material.node_tree
    if tree is None:
        return
    nodes_by_texture = {}
    replacements = {}
    for node in tree.nodes:
        if node.type != "TEX_IMAGE" or not node.get("ue_texture_path") or "ue_parameter_names" not in node:
            continue
        # Separate sampling/UV setups can be intentional edits to an imported
        # material. Only consolidate equivalent inventory nodes with no UV links.
        if any(socket.is_linked for socket in node.inputs):
            continue
        texture = ("image", node.image.as_pointer()) if node.image is not None else (
            "path", node["ue_texture_path"].casefold())
        sampling = (node.interpolation, node.projection, node.projection_blend, node.extension, node.mute,
                    tuple(node.inputs["Vector"].default_value),
                    tuple(node.texture_mapping.translation), tuple(node.texture_mapping.rotation),
                    tuple(node.texture_mapping.scale), node.texture_mapping.vector_type)
        frames = tuple(getattr(node.image_user, name, None) for name in (
            "frame_duration", "frame_start", "frame_offset", "use_cyclic", "use_auto_refresh",
            "multilayer_layer", "multilayer_pass", "multilayer_view", "tile"))
        key = (texture, sampling, frames)
        existing = nodes_by_texture.get(key)
        if existing is None:
            nodes_by_texture[key] = node
        else:
            _merge_texture_labels(existing, json.loads(node["ue_parameter_names"]), rename=False)
            replacements[node.as_pointer()] = existing
    if not replacements:
        return
    # Scan links once, rather than walking every socket's links for large inventories.
    for link in list(tree.links):
        existing = replacements.get(link.from_node.as_pointer())
        if existing is not None:
            tree.links.new(existing.outputs[link.from_socket.name], link.to_socket)
    for node in list(tree.nodes):
        if node.as_pointer() in replacements:
            tree.nodes.remove(node)


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
    links = material.node_tree.links
    principled = make_bsdf(material.node_tree, links, output)
    principled.name = principled.label = "Profile PBR"
    principled.location = (120, 0)

    if not mapping:
        return
    selected = {}
    for slot in ("albedo", "normal", "metalness", "roughness", "alpha", "emission"):
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

    albedo = selected.get("albedo")
    if albedo is not None:
        links.new(albedo[0].outputs["Color"], principled.inputs["Base Color"])

    emission = selected.get("emission")
    if emission is not None:
        links.new(emission[0].outputs["Color"], principled.inputs["Emission Color"])
        principled.inputs["Emission Strength"].default_value = 1.0

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
    material = find_datablock("materials", "generic-material", (source_id, texture_namespace, material_path.casefold()),
                             lambda item: (item.get("ue_source_id"),
                                           item.get("ue_texture_namespace", item.get("ue_source_id")),
                                           item.get("ue_virtual_path", "").casefold()), image_loader)
    if material is None:
        material = bpy.data.materials.new(material_name)
    if material.get("ue_texture_inventory_complete"):
        from ...core.blender.material_nodes import refresh_material_textures
        refresh_material_textures(material, image_loader)
        _deduplicate_inventory_nodes(material)
        return material
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    material["ue_source_id"] = source_id
    material["ue_texture_namespace"] = texture_namespace
    material["ue_virtual_path"] = material_path
    material["ue_material_type"] = material_data.get("type") or ""
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    warnings = list(material_data.get("warnings") or [])
    parameter_nodes = {}
    nodes_by_path = {}
    nodes_by_image = {}
    texture_count = 0
    for warning in warnings:
        print(f"[Unreal material WARNING] {material_path}: {warning}")
    for texture in material_data.get("textures") or []:
        path = texture.get("path") or ""
        if not path:
            continue
        labels = texture.get("labels") or []
        key = path.casefold()
        node = nodes_by_path.get(key)
        image = None
        if node is None:
            image = image_loader(path)
            if image is not None:
                node = nodes_by_image.get(image.as_pointer())
        if node is not None:
            nodes_by_path[key] = node
            _merge_texture_labels(node, labels)
            for label in labels:
                parameter_nodes.setdefault(_parameter_key(label), node)
            continue
        node = nodes.new("ShaderNodeTexImage")
        node.location = ((texture_count % 4) * 280 - 1120, -(texture_count // 4) * 340)
        texture_count += 1
        node.width = 240
        node["ue_texture_path"] = path
        nodes_by_path[key] = node
        node.image = image
        if image is not None:
            nodes_by_image[image.as_pointer()] = node
        _merge_texture_labels(node, labels)
        for label in labels:
            parameter_nodes.setdefault(_parameter_key(label), node)
        info = getattr(image_loader, "texture_info", {}).get(path.casefold(), {})
        if node.image is None:
            node["ue_texture_unavailable"] = True
            reason = info.get("reason")
            if reason:
                node["ue_texture_unavailable_reason"] = reason
                node["ue_texture_type"] = info.get("textureType", "")
                warnings.append(f"{path}: {reason}")
            else:
                warnings.append(f"Could not decode texture: {path}")
        elif node.image.get("ue_texture_layout") == "VOLUME_ATLAS":
            node["ue_texture_layout"] = "VOLUME_ATLAS"
            node.label = "Volume slice atlas: " + node.label
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
    remember_datablock("materials", material, image_loader)
    return material
