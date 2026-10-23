"""Small Blender node/image primitives; shader policy belongs to each title."""

import math

import bpy

from .import_cache import find_datablock, get_import_cache, remember_datablock


def is_world_grid_material(path):
    normalized = str(path).replace("\\", "/").strip("/").split(".", 1)[0].casefold()
    return normalized == "engine/content/enginematerials/worldgridmaterial"


def apply_world_grid_material(material, path):
    """Replace Unreal's default grid material with a plain black diffuse."""
    if not is_world_grid_material(path):
        return False
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    links.new(diffuse.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (0.0, 0.0, 0.0, 1.0)
    return True


def set_color_space(image, color_space):
    try:
        if image.colorspace_settings.name != color_space:
            image.colorspace_settings.name = color_space
    except (AttributeError, TypeError, ValueError):
        print(
            f"  Warning: Blender has no '{color_space}' color space for '{image.name}'."
        )


def set_channel_packed_alpha(image):
    try:
        image.alpha_mode = "CHANNEL_PACKED"
    except (AttributeError, TypeError, ValueError):
        print(f"  Warning: Blender cannot mark '{image.name}' as channel packed.")


def image_node(nodes, image_loader, path, *, label, location, colour_space):
    if not path or (image := image_loader(path)) is None:
        return None
    set_color_space(image, colour_space)
    node = nodes.new("ShaderNodeTexImage")
    node.name = node.label = label
    node.location = location
    node.image = image
    return node


def limit_image_resolution(image, max_resolution):
    """Enforce the cap when an asset has no sufficiently small stored mip."""
    width, height = image.size
    if max_resolution > 0 and max(width, height) > max_resolution:
        ratio = max_resolution / max(width, height)
        image.scale(max(1, int(width * ratio)), max(1, int(height * ratio)))


def image_meets_texture_request(image, max_resolution=0, mip_offset=0):
    """Avoid extracting another payload when the shared image is already sufficient."""
    width = int(image.get("ue_texture_source_width", 0))
    height = int(image.get("ue_texture_source_height", 0))
    if min(width, height) <= 0:
        return False
    width, height = max(1, width >> -mip_offset), max(1, height >> -mip_offset)
    if max_resolution and max(width, height) > max_resolution:
        ratio = max_resolution / max(width, height)
        width, height = max(1, int(width * ratio)), max(1, int(height * ratio))
    return image.size[0] >= width and image.size[1] >= height


def material_for_texture_source(name, path, loader):
    """Reuse materials within the same game source, independently of quality."""
    namespace = getattr(loader, "texture_namespace", "")
    material = find_datablock("materials", "texture-source", (namespace, path.casefold()),
                             lambda item: (item.get("ue_texture_namespace", item.get("ue_source_id", "")),
                                           item.get("ue_virtual_path", "").casefold()), loader)
    if material is None:
        material = bpy.data.materials.get(name)
        if material is not None and (material.get("ue_texture_namespace", material.get("ue_source_id", "")) != namespace
                                    or material.get("ue_virtual_path", "").casefold() != path.casefold()):
            material = None
    if material is None:
        material = bpy.data.materials.new(name)
    material["ue_texture_namespace"] = namespace
    material["ue_virtual_path"] = path
    remember_datablock("materials", material, loader)
    return material


def refresh_material_textures(material, loader):
    """Cached shaders still need to request textures so later imports can upgrade them."""
    if material.node_tree is None:
        return material
    # Manual callbacks refresh on every call. Mounted/loose import loaders
    # memoize only within the current batch and texture-quality request;
    # a later session can still upgrade shared images.
    cache = get_import_cache(loader) if hasattr(loader, "texture_namespace") else None
    stamp = (material.as_pointer(), getattr(loader, "texture_namespace", ""),
             getattr(loader, "max_texture_resolution", 0), getattr(loader, "texture_mip_offset", 0),
             getattr(loader, "import_textures", True), len(material.node_tree.nodes))
    if cache is not None and cache.refreshed_materials.get(stamp) == material:
        return material
    for node in material.node_tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        image = node.image
        path = (image.get("ue_virtual_path") if image is not None else None) or node.get("ue_texture_path")
        if path:
            loaded = loader(path)
            if loaded is not None:
                if color_space := node.get("sqex_rmi_color_space"):
                    set_color_space(loaded, color_space)
                if node.image is None and "sqex_rmi_fallback_previous_mute" in node:
                    node.mute = bool(node["sqex_rmi_fallback_previous_mute"])
                    del node["sqex_rmi_fallback_previous_mute"]
                node.image = loaded
    if cache is not None:
        cache.refreshed_materials[stamp] = material
    return material


def load_packed_image(path, name, *, metadata=None, color_space=None, max_resolution=0, existing=None):
    """Validate and pack a disposable extracted image, cleaning up on failure."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        if min(image.size) <= 0:
            raise RuntimeError("Blender could not decode the extracted texture.")
        metadata = dict(metadata or {})
        metadata.setdefault("ue_texture_source_width", image.size[0])
        metadata.setdefault("ue_texture_source_height", image.size[1])
        if color_space:
            set_color_space(image, color_space)
        limit_image_resolution(image, max_resolution)
        if existing is not None:
            if all(old >= new for old, new in zip(existing.size, image.size)):
                bpy.data.images.remove(image)
                return existing
            # Keep the ID: every linked material, including earlier map imports,
            # must see the upgrade. Validate the replacement before touching it.
            previous_color_space = existing.colorspace_settings.name
            # Release the validation image before mutating the persistent one.
            bpy.data.images.remove(image)
            image = existing
            if existing.packed_file:
                existing.unpack(method="REMOVE")
            existing.filepath = str(path)
            existing.source = "FILE"
            existing.reload()
            # A color-space change can reload the original file buffer. Apply
            # it before resizing so packing preserves the capped dimensions.
            set_color_space(existing, previous_color_space)
            limit_image_resolution(existing, max_resolution)
        if existing is None:
            image.name = name
        for key, value in (metadata or {}).items():
            image[key] = value
        source_width = image.get("ue_texture_source_width", image.size[0])
        source_height = image.get("ue_texture_source_height", image.size[1])
        image["ue_texture_width"], image["ue_texture_height"] = tuple(image.size)
        image["ue_texture_mip_level"] = max(0.0, math.log2(max(source_width, source_height) / max(image.size)))
        image.pack()
        return image
    except Exception:
        if image != existing and image.users == 0:
            bpy.data.images.remove(image)
        raise


def make_bsdf(tree, links, output, label="", ior=1.3):
    node = tree.nodes.new("ShaderNodeBsdfPrincipled")
    node.label = label
    node.inputs["IOR"].default_value = ior
    links.new(node.outputs["BSDF"], output.inputs["Surface"])
    return node


def make_y_invert_curves(tree, location):
    """Invert only green for DirectX normal maps on older Blender versions."""
    node = tree.nodes.new("ShaderNodeRGBCurve")
    node.label = "DX Normal Y-flip"
    node.location = location
    green = node.mapping.curves[1]
    green.points[0].location = (0.0, 1.0)
    green.points[1].location = (1.0, 0.0)
    node.mapping.update()
    return node


def set_normal_convention(node):
    try:
        node.convention = "DIRECTX"
    except AttributeError:
        pass


def make_normal_map(
    tree,
    links,
    color_out,
    location,
    *,
    directx=True,
    legacy_mode="CURVES",
    legacy_loc=None,
    legacy_curves_loc=None,
    label=None,
):
    """Decode normals with an explicit source convention and legacy layout."""
    nodes = tree.nodes
    normal = nodes.new("ShaderNodeNormalMap")
    normal.location = location
    if label:
        normal.name = normal.label = label
    native_directx = bpy.app.version >= (5, 2, 0) and hasattr(normal, "convention")
    if directx and native_directx:
        set_normal_convention(normal)
    elif directx:
        if legacy_loc is not None:
            normal.location = legacy_loc
            location = legacy_loc
        if legacy_mode == "CURVES":
            invert = make_y_invert_curves(
                tree, legacy_curves_loc or (location[0] - 300, location[1])
            )
            links.new(color_out, invert.inputs["Color"])
            color_out = invert.outputs["Color"]
        else:
            separate = nodes.new("ShaderNodeSeparateColor")
            separate.label = f"{label} DirectX channels"
            separate.location = (location[0] - 420, location[1])
            invert = nodes.new("ShaderNodeMath")
            invert.operation = "SUBTRACT"
            invert.label = f"{label} invert DirectX green"
            invert.location = (location[0] - 200, location[1] - 110)
            invert.inputs[0].default_value = 1.0
            combine = nodes.new("ShaderNodeCombineColor")
            combine.label = f"{label} OpenGL colour"
            combine.location = (location[0] - 20, location[1])
            links.new(color_out, separate.inputs["Color"])
            links.new(separate.outputs["Red"], combine.inputs["Red"])
            links.new(separate.outputs["Green"], invert.inputs[1])
            links.new(invert.outputs[0], combine.inputs["Green"])
            links.new(separate.outputs["Blue"], combine.inputs["Blue"])
            color_out = combine.outputs["Color"]
    links.new(color_out, normal.inputs["Color"])
    return normal


def image_normal_map(nodes, links, image, *, label, location, uv_map=None):
    if image is None:
        return None
    normal = make_normal_map(
        nodes.id_data,
        links,
        image.outputs["Color"],
        location,
        legacy_mode="CHANNELS",
        label=label,
    )
    if uv_map:
        uv = nodes.new("ShaderNodeUVMap")
        uv.label = f"{label} UV2"
        uv.uv_map = uv_map
        uv.location = (location[0] - 220, location[1] - 180)
        links.new(uv.outputs["UV"], image.inputs["Vector"])
    return normal


def scalar_channel_socket(nodes, links, texture_node, channel):
    channel = str(channel or "R").upper()
    if channel == "A":
        return texture_node.outputs.get("Alpha")
    output_name = {"R": "Red", "G": "Green", "B": "Blue"}.get(channel, "Red")
    separate = nodes.new("ShaderNodeSeparateColor")
    separate.name = separate.label = f"{texture_node.label} {output_name}"
    separate.location = (texture_node.location.x + 280, texture_node.location.y - 100)
    links.new(texture_node.outputs["Color"], separate.inputs["Color"])
    return separate.outputs[output_name]
