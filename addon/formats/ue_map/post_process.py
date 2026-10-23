"""Preserve post-process camera regions and build reusable HDR LUT groups."""

import json
import bpy

from . import worlds


def _actor_name(entry):
    outer = entry.get("Outer") or {}
    if isinstance(outer, dict):
        path = outer.get("ObjectPath", "")
        return path.rsplit(".", 1)[-1] or entry.get("Name", "PostProcessCamera")
    return outer or entry.get("Name", "PostProcessCamera")


def _properties(target, properties):
    for key, value in properties.items():
        if isinstance(value, (str, int, float, bool)):
            target[key] = value
        else:
            target[key] = json.dumps(value, ensure_ascii=False)


def _matching_correction(camera, corrections):
    props = camera.get("Properties") or {}
    matching = [entry for entry in corrections if all(
        (entry.get("Properties") or {}).get(key) == props.get(key)
        for key in ("RelativeLocation", "RelativeScale3D", "Priority", "BlendType"))]
    if len(matching) == 1:
        return matching[0]
    # A single map-wide correction is unambiguous even without region data.
    return corrections[0] if len(corrections) == 1 else None


def create_lut_group(name, image=None, strength=1.0):
    """Trilinear color-cube sampling in normalized RGB domain; preserve alpha.

    This is the LUT stage only. Game exposure, tone mapping, and blending
    between post-process volumes are intentionally not inferred from metadata.
    """
    group = bpy.data.node_groups.new(name, "CompositorNodeTree")
    group.use_fake_user = True
    group.interface.new_socket(name="Image", in_out="INPUT", socket_type="NodeSocketColor")
    mix_socket = group.interface.new_socket(name="LUT Strength", in_out="INPUT", socket_type="NodeSocketFloat")
    mix_socket.default_value = strength
    mix_socket.min_value, mix_socket.max_value = 0.0, 1.0
    group.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = group.nodes, group.links
    source = nodes.new("NodeGroupInput")
    source.location = (-1200, 400)
    output = nodes.new("NodeGroupOutput")
    output.location = (1800, 400)
    if image is None:
        links.new(source.outputs["Image"], output.inputs["Image"])
        group["ue_lut_status"] = "No LUT loaded; image passes through"
        return group
    size = int(image["ue_lut_size"])
    group["ue_lut_image"] = image.name
    group["ue_lut_size"] = size
    group["ue_lut_domain"] = "RGB [0,1]; exposure and game tone mapping are not applied"
    image_node = nodes.new("CompositorNodeImage")
    image_node.image = image
    image_node.label = "HDR color cube — blue slices"
    image_node.location = (-1200, 100)
    original = nodes.new("CompositorNodeSeparateColor")
    links.new(source.outputs["Image"], original.inputs[0])
    original.location = (-1200, -200)
    serial = 0

    def math(operation, a, b=0.0, clamp=False):
        nonlocal serial
        node = nodes.new("ShaderNodeMath" if bpy.app.version >= (5, 0, 0) else "CompositorNodeMath")
        node.operation = operation
        node.use_clamp = clamp
        node.location = (-900 + (serial % 9) * 220, -400 - (serial // 9) * 180)
        serial += 1
        for socket, value in zip(node.inputs, (a, b)):
            if isinstance(value, (int, float)):
                socket.default_value = value
            else:
                links.new(value, socket)
        return node.outputs[0]

    red, green, blue = [math("MULTIPLY", original.outputs[channel], 1.0, True)
                        for channel in ("Red", "Green", "Blue")]
    x = math("MULTIPLY", red, size - 1)
    y = math("MULTIPLY", green, size - 1)
    z = math("MULTIPLY", blue, size - 1)
    lower = math("FLOOR", z)
    upper = math("MINIMUM", math("ADD", lower, 1), size - 1)
    fraction = math("SUBTRACT", z, lower)
    legacy = bpy.app.version < (5, 0, 0)
    if legacy:
        # Older Map UV nodes only offer nearest or anisotropic filtering.
        # Sample all eight corners explicitly to avoid derivative filtering
        # smearing neighboring color-cube slices together.
        x0, y0 = math("FLOOR", x), math("FLOOR", y)
        x1 = math("MINIMUM", math("ADD", x0, 1), size - 1)
        y1 = math("MINIMUM", math("ADD", y0, 1), size - 1)
        fx, fy = math("SUBTRACT", x, x0), math("SUBTRACT", y, y0)
        coordinates = [(layer, row, column) for layer in (lower, upper)
                       for row in (y0, y1) for column in (x0, x1)]
    else:
        coordinates = [(layer, y, x) for layer in (lower, upper)]
    samples = []
    for index, (layer, row, column) in enumerate(coordinates):
        u = math("DIVIDE", math("ADD", math("ADD", math("MULTIPLY", layer, size), column), 0.5), size * size)
        v = math("DIVIDE", math("ADD", row, 0.5), size)
        uv = nodes.new("ShaderNodeCombineXYZ" if bpy.app.version >= (5, 0, 0) else "CompositorNodeCombineXYZ")
        links.new(u, uv.inputs["X"])
        links.new(v, uv.inputs["Y"])
        uv.inputs["Z"].default_value = 1.0
        uv.location = (300, 200 - index * 250)
        sample = nodes.new("CompositorNodeMapUV")
        sample.label = f"Color-cube sample {index + 1}"
        sample.location = (550, 200 - index * 250)
        if sample.inputs.get("Interpolation"):
            sample.inputs["Interpolation"].default_value = "Bilinear"
        elif hasattr(sample, "filter_type"):
            sample.filter_type = "NEAREST"
        links.new(image_node.outputs["Image"], sample.inputs["Image"])
        links.new(uv.outputs[0], sample.inputs["UV"])
        separate = nodes.new("CompositorNodeSeparateColor")
        separate.location = (800, 200 - index * 250)
        links.new(sample.outputs[0], separate.inputs[0])
        samples.append(separate)
    result = nodes.new("CompositorNodeCombineColor")
    result.location = (1500, 400)
    factor = math("MULTIPLY", source.outputs["LUT Strength"], 1.0, True)
    def interpolate(lo, hi, factor):
        return math("ADD", lo, math("MULTIPLY", math("SUBTRACT", hi, lo), factor))
    for channel in ("Red", "Green", "Blue"):
        values = [node.outputs[channel] for node in samples]
        if legacy:
            values = [interpolate(values[i], values[i + 1], fx) for i in range(0, 8, 2)]
            values = [interpolate(values[i], values[i + 1], fy) for i in range(0, 4, 2)]
        interpolated = interpolate(*values, fraction)
        blended = math("ADD", original.outputs[channel], math("MULTIPLY",
                       math("SUBTRACT", interpolated, original.outputs[channel]), factor))
        links.new(blended, result.inputs[channel])
    links.new(original.outputs["Alpha"], result.inputs["Alpha"])
    links.new(result.outputs[0], output.inputs["Image"])
    group["ue_lut_status"] = "Loaded; trilinear HDR LUT"
    return group


def import_camera_regions(data, source_name, location_scale, rotation_from_relative, lut_loader=None):
    cameras = [entry for entry in data if entry.get("Type") == "PostProcessCameraComponent"]
    if not cameras:
        return 0
    corrections = [entry for entry in data if entry.get("Type") == "PostProcessColorCorrectionComponent"]
    collection = worlds.ensure_typed_import_collection(
        worlds.ensure_parent_collection_for_file(source_name), "_PostProcess")
    for camera in cameras:
        props = camera.get("Properties") or {}
        obj = bpy.data.objects.new(_actor_name(camera), None)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = location_scale
        obj.location = worlds.location_from_relative(props.get("RelativeLocation", {}), location_scale)
        obj.rotation_euler = rotation_from_relative(props.get("RelativeRotation", {}))
        obj.scale = worlds.scale_from_relative(props.get("RelativeScale3D", {}))
        obj["source_type"] = "PostProcessCameraComponent"
        obj["sqex_source_map"] = source_name
        obj["ue_component_properties"] = json.dumps(props, ensure_ascii=False)
        _properties(obj, props)
        collection.objects.link(obj)
        correction = _matching_correction(camera, corrections)
        correction_props = (correction or {}).get("Properties") or {}
        lut_path = (correction_props.get("ColorCorrectionLUTHDR") or {}).get("ObjectPath", "")
        image = None
        error = ""
        if lut_path and lut_loader:
            try:
                image = lut_loader(lut_path)
            except Exception as exc:
                error = str(exc)
                print(f"[Post-process] Could not load LUT '{lut_path}': {exc}")
        strength = correction_props.get("ColorCorrectionLUTIntensity", 1.0)
        group = create_lut_group(obj.name + " Color Correction", image, float(strength))
        group["sqex_source_map"] = source_name
        group["ue_camera_properties"] = obj["ue_component_properties"]
        group["ue_correction_properties"] = json.dumps(correction_props, ensure_ascii=False)
        group["ue_lut_path"] = lut_path
        if error:
            group["ue_lut_error"] = error
        obj["ue_compositor_group"] = group.name
        obj["ue_lut_path"] = lut_path
    return len(cameras)
