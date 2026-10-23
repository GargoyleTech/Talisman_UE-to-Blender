"""Editable approximations of Unreal TextRender components using Blender's font."""

import bpy

from .lights import apply_component_visibility, float_or_default


def text_value(value) -> str:
    """Accept the bridge's resolved FText and common FModel text-history shapes."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, dict):
        for key in ("LocalizedString", "CultureInvariantString", "SourceString", "Text", "TextHistory", "History"):
            if value.get(key) is not None:
                result = text_value(value[key])
                if result:
                    return result
    return ""


def _alignment(value, choices, default):
    # Accept both qualified enum names and older numeric property dumps.
    if isinstance(value, (int, float)):
        return choices[int(value)] if 0 <= int(value) < len(choices) else default
    name = str(value or "").split("::")[-1].split("_")[-1].upper()
    return {"LEFT": "LEFT", "CENTER": "CENTER", "RIGHT": "RIGHT",
            "TEXTTOP": "TOP_BASELINE", "TEXTCENTER": "CENTER", "TEXTBOTTOM": "BOTTOM_BASELINE",
            "QUADTOP": "TOP"}.get(name, default)


def create_text_object(name, props, collection, location_scale=0.01):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = text_value(props.get("Text", "Text"))
    curve.size = max(0.000001, float_or_default(props.get("WorldSize"), 30.0) * location_scale)
    curve.align_x = _alignment(props.get("HorizontalAlignment"), ("LEFT", "CENTER", "RIGHT"), "LEFT")
    curve.align_y = _alignment(props.get("VerticalAlignment"), ("TOP_BASELINE", "CENTER", "BOTTOM_BASELINE", "TOP"), "TOP_BASELINE")
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    color = props.get("TextRenderColor") or {}
    rgba = tuple(max(0.0, min(1.0, float_or_default(color.get(key), 255.0) / 255.0)) for key in "RGBA")
    material_name = "UE Text " + " ".join(f"{value:.4f}" for value in rgba)
    material = bpy.data.materials.get(material_name)
    if material is None:
        material = bpy.data.materials.new(material_name)
        material.diffuse_color = rgba
        if bpy.app.version < (5, 0, 0):
            material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        emission = tree.nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = rgba
        emission.inputs["Strength"].default_value = 1.0
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(emission.outputs[0], output.inputs["Surface"])
    curve.materials.append(material)
    obj.color = rgba
    for key in ("Font", "TextMaterial"):
        reference = props.get(key)
        if reference:
            obj["ue_" + key.lower()] = str(reference.get("ObjectPath") or reference.get("ObjectName") or "") if isinstance(reference, dict) else str(reference)
    for key in ("HorizSpacingAdjust", "VertSpacingAdjust"):
        if key in props:
            obj["ue_" + key] = float_or_default(props[key])
    apply_component_visibility(obj, props)
    return obj
