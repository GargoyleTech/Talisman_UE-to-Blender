"""Shared light parsing and creation helpers for Unreal map imports."""

from __future__ import annotations

import math

import bpy


UE_LIGHT_TYPES: dict[str, str] = {
    "SpotLight": "SPOT",
    "SpotLightComponent": "SPOT",
    "PointLight": "POINT",
    "PointLightComponent": "POINT",
}

VOLUMETRIC_SCATTERING_PROP = "VolumetricScatteringIntensity"
UE_ATTENUATION_RADIUS_PROP = "ue_attenuation_radius"
UE_ATTENUATION_RADIUS_UNITS_PROP = "ue_attenuation_radius_units"
UE_INVERSE_SQUARED_FALLOFF_PROP = "ue_use_inverse_squared_falloff"
UE_DISABLE_CUSTOM_ATTENUATION_PROP = "ue_disable_custom_attenuation"
UE_LIGHT_FALLOFF_EXPONENT_PROP = "ue_light_falloff_exponent"
UE_SOURCE_RADIUS_PROP = "ue_source_radius"
UE_LIGHT_EMISSION_NODE_LABEL = "UE4 Light Emission"
UE_LIGHT_ATTENUATION_GROUP_NAME = "UE4 Light Attenuation"
UE_LIGHT_ATTENUATION_GROUP_VERSION = 2

UE_LIGHT_OBJECT_PROPS = (
    UE_ATTENUATION_RADIUS_PROP,
    UE_ATTENUATION_RADIUS_UNITS_PROP,
    UE_INVERSE_SQUARED_FALLOFF_PROP,
    UE_DISABLE_CUSTOM_ATTENUATION_PROP,
    UE_LIGHT_FALLOFF_EXPONENT_PROP,
    UE_SOURCE_RADIUS_PROP,
)

DEFAULT_SOURCE_RADIUS_CM = 50.0
# UE's default SpotLightComponent outer full cone angle.  Exports omit it when
# it has this default value.
DEFAULT_SPOT_FULL_CONE_ANGLE_DEG = 90.0


def blender_light_type_from_name(name: str) -> str | None:
    """Return Blender light type from a UE object/template name."""
    for ue_name, bl_name in UE_LIGHT_TYPES.items():
        if ue_name in name:
            return bl_name
    return None


def float_or_default(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_or_default(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def get_light_temperature(props: dict) -> float | None:
    """Return whichever temperature key the export uses."""
    if "Temperature" in props:
        return float_or_default(props.get("Temperature"), 6500.0)
    if "ColorTemperature" in props:
        return float_or_default(props.get("ColorTemperature"), 6500.0)
    return None


def apply_default_light_options(
    light_data: bpy.types.Light,
    location_scale: float = 0.01,
) -> None:
    """Apply importer-wide Blender light defaults when the running version supports them."""
    if light_data is None:
        return
    if hasattr(light_data, "normalize"):
        light_data.normalize = False
    if hasattr(light_data, "shadow_soft_size"):
        light_data.shadow_soft_size = DEFAULT_SOURCE_RADIUS_CM * location_scale


def _new_math(nodes, operation: str, label: str = ""):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    if label:
        node.label = label
    return node


def _neutralize_ue_light_node_values(light_data: bpy.types.Light) -> None:
    """Keep color/power on the light; its node tree supplies only attenuation.

    Also resets trees made by the older importer that duplicated those values
    in the nodes, multiplying HDR color and power a second time in Blender 5.x.
    """
    tree = getattr(light_data, "node_tree", None)
    if tree is None:
        return

    for node in tree.nodes:
        if node.label == UE_LIGHT_EMISSION_NODE_LABEL:
            color_input = node.inputs.get("Color")
            if color_input is not None:
                color_input.default_value = (1.0, 1.0, 1.0, 1.0)
def set_light_energy(light_data: bpy.types.Light, energy: float) -> None:
    """Set power once on the light, keeping attenuation nodes neutral."""
    light_data.energy = energy
    _neutralize_ue_light_node_values(light_data)


def set_light_color(
    light_data: bpy.types.Light,
    color: tuple[float, float, float],
) -> None:
    """Set color once on the light, keeping attenuation nodes neutral."""
    light_data.color = color
    _neutralize_ue_light_node_values(light_data)


def _new_ue_light_attribute(nodes, property_name: str, label: str):
    node = nodes.new("ShaderNodeAttribute")
    node.label = label
    node.attribute_name = property_name
    if hasattr(node, "attribute_type"):
        node.attribute_type = "INSTANCER"
    return node


def get_ue_light_attenuation_group() -> bpy.types.NodeTree:
    """Return the single editable attenuation group used by imported lights."""
    group = bpy.data.node_groups.get(UE_LIGHT_ATTENUATION_GROUP_NAME)
    if group is not None and group.get("sqex_group_version") == UE_LIGHT_ATTENUATION_GROUP_VERSION:
        return group

    if group is None:
        group = bpy.data.node_groups.new(UE_LIGHT_ATTENUATION_GROUP_NAME, "ShaderNodeTree")
    group.nodes.clear()
    group.interface.clear()
    group.interface.new_socket(name="Strength", in_out="OUTPUT", socket_type="NodeSocketFloat")
    group["sqex_group_version"] = UE_LIGHT_ATTENUATION_GROUP_VERSION
    group["sqex_purpose"] = "Shared UE4 local-light attenuation for Square Enix imports"

    nodes = group.nodes
    links = group.links
    output = nodes.new("NodeGroupOutput")
    output.location = (760, 0)
    falloff = nodes.new("ShaderNodeLightFalloff")
    falloff.location = (-720, 120)
    falloff.inputs["Strength"].default_value = 1.0

    radius = _new_ue_light_attribute(nodes, UE_ATTENUATION_RADIUS_PROP, "UE attenuation radius")
    radius.location = (-720, -100)
    source_radius = _new_ue_light_attribute(nodes, UE_SOURCE_RADIUS_PROP, "UE source radius")
    source_radius.location = (-720, -260)
    inverse_squared = _new_ue_light_attribute(nodes, UE_INVERSE_SQUARED_FALLOFF_PROP, "UE inverse-squared")
    inverse_squared.location = (-720, -420)
    disable_custom = _new_ue_light_attribute(
        nodes, UE_DISABLE_CUSTOM_ATTENUATION_PROP, "Disable Square Enix attenuation"
    )
    disable_custom.location = (-720, -740)
    exponent = _new_ue_light_attribute(nodes, UE_LIGHT_FALLOFF_EXPONENT_PROP, "UE falloff exponent")
    exponent.location = (-720, -580)
    if "Smooth" in falloff.inputs:
        links.new(source_radius.outputs["Fac"], falloff.inputs["Smooth"])

    distance = _new_math(nodes, "DIVIDE", "UE distance")
    distance.location = (-480, 120)
    links.new(falloff.outputs["Constant"], distance.inputs[0])
    links.new(falloff.outputs["Linear"], distance.inputs[1])
    normalized = _new_math(nodes, "DIVIDE", "distance / radius")
    normalized.location = (-260, 120)
    links.new(distance.outputs[0], normalized.inputs[0])
    links.new(radius.outputs["Fac"], normalized.inputs[1])

    power4 = _new_math(nodes, "POWER", "(d/r)^4")
    power4.location = (-40, 220)
    power4.inputs[1].default_value = 4.0
    links.new(normalized.outputs[0], power4.inputs[0])
    inverse_one_minus = _new_math(nodes, "SUBTRACT", "1 - (d/r)^4")
    inverse_one_minus.location = (150, 220)
    inverse_one_minus.inputs[0].default_value = 1.0
    inverse_one_minus.use_clamp = True
    links.new(power4.outputs[0], inverse_one_minus.inputs[1])
    inverse_mask = _new_math(nodes, "MULTIPLY", "UE radius mask")
    inverse_mask.location = (340, 220)
    links.new(inverse_one_minus.outputs[0], inverse_mask.inputs[0])
    links.new(inverse_one_minus.outputs[0], inverse_mask.inputs[1])
    inverse_strength = _new_math(nodes, "MULTIPLY", "Quadratic * UE mask")
    inverse_strength.location = (520, 220)
    links.new(falloff.outputs["Quadratic"], inverse_strength.inputs[0])
    links.new(inverse_mask.outputs[0], inverse_strength.inputs[1])

    exponent_one_minus = _new_math(nodes, "SUBTRACT", "1 - d/r")
    exponent_one_minus.location = (-40, -20)
    exponent_one_minus.inputs[0].default_value = 1.0
    exponent_one_minus.use_clamp = True
    links.new(normalized.outputs[0], exponent_one_minus.inputs[1])
    exponent_power = _new_math(nodes, "POWER", "UE falloff exponent")
    exponent_power.location = (150, -20)
    links.new(exponent_one_minus.outputs[0], exponent_power.inputs[0])
    links.new(exponent.outputs["Fac"], exponent_power.inputs[1])
    exponent_strength = _new_math(nodes, "MULTIPLY", "Constant * UE exponent")
    exponent_strength.location = (340, -20)
    links.new(falloff.outputs["Constant"], exponent_strength.inputs[0])
    links.new(exponent_power.outputs[0], exponent_strength.inputs[1])

    inverse_weighted = _new_math(nodes, "MULTIPLY", "Inverse-squared selection")
    inverse_weighted.location = (520, 60)
    links.new(inverse_strength.outputs[0], inverse_weighted.inputs[0])
    links.new(inverse_squared.outputs["Fac"], inverse_weighted.inputs[1])
    one_minus_inverse = _new_math(nodes, "SUBTRACT", "1 - inverse-squared")
    one_minus_inverse.location = (150, -190)
    one_minus_inverse.inputs[0].default_value = 1.0
    links.new(inverse_squared.outputs["Fac"], one_minus_inverse.inputs[1])
    exponent_weighted = _new_math(nodes, "MULTIPLY", "Exponent selection")
    exponent_weighted.location = (520, -100)
    links.new(exponent_strength.outputs[0], exponent_weighted.inputs[0])
    links.new(one_minus_inverse.outputs[0], exponent_weighted.inputs[1])
    result = _new_math(nodes, "ADD", "UE attenuation")
    result.location = (700, 40)
    links.new(inverse_weighted.outputs[0], result.inputs[0])
    links.new(exponent_weighted.outputs[0], result.inputs[1])

    # Missing custom properties read as zero, so existing imported lights keep
    # the custom attenuation path. Setting this object property to true
    # selects neutral strength and leaves Blender's native light attenuation
    # in charge.
    one_minus_disable = _new_math(nodes, "SUBTRACT", "1 - disable custom attenuation")
    one_minus_disable.location = (700, -120)
    one_minus_disable.inputs[0].default_value = 1.0
    links.new(disable_custom.outputs["Fac"], one_minus_disable.inputs[1])
    enabled_strength = _new_math(nodes, "MULTIPLY", "Custom attenuation enabled")
    enabled_strength.location = (880, 40)
    links.new(result.outputs[0], enabled_strength.inputs[0])
    links.new(one_minus_disable.outputs[0], enabled_strength.inputs[1])
    disabled_strength = _new_math(nodes, "MULTIPLY", "Custom attenuation disabled")
    disabled_strength.location = (880, -120)
    disabled_strength.inputs[0].default_value = 1.0
    links.new(disable_custom.outputs["Fac"], disabled_strength.inputs[1])
    bypassed_result = _new_math(nodes, "ADD", "UE attenuation bypass")
    bypassed_result.location = (1060, 40)
    links.new(enabled_strength.outputs[0], bypassed_result.inputs[0])
    links.new(disabled_strength.outputs[0], bypassed_result.inputs[1])
    links.new(bypassed_result.outputs[0], output.inputs["Strength"])
    return group


def apply_ue_attenuation_nodes(light_data: bpy.types.Light, attenuation_radius: float) -> bool:
    """Attach the shared UE attenuation node group to one local light."""
    if attenuation_radius <= 0.0 or not hasattr(light_data, "node_tree"):
        return False
    try:
        if bpy.app.version < (5, 0, 0):
            light_data.use_nodes = True
        tree = light_data.node_tree
        if tree is None:
            return False
        nodes = tree.nodes
        links = tree.links
        nodes.clear()
        output = nodes.new("ShaderNodeOutputLight")
        emission = nodes.new("ShaderNodeEmission")
        attenuation = nodes.new("ShaderNodeGroup")
        attenuation.node_tree = get_ue_light_attenuation_group()
        emission.label = UE_LIGHT_EMISSION_NODE_LABEL
        attenuation.label = "Square Enix shared UE4 attenuation"
        output.location = (440, 0)
        emission.location = (220, 0)
        attenuation.location = (-80, 0)
        emission.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        links.new(attenuation.outputs["Strength"], emission.inputs["Strength"])
        links.new(emission.outputs["Emission"], output.inputs["Surface"])
        return True
    except Exception as exc:
        print(f"[Talisman UE4 Import]   Failed to attach UE4 attenuation group to '{light_data.name}': {exc}")
        return False


def apply_common_static_light_properties(
    light_data: bpy.types.Light,
    props: dict,
    location_scale: float = 0.01,
    exposure_mult: float = 1.0,
    attenuation_radius_mult: float = 1.0,
    always_cast_shadows: bool = False,
) -> tuple[float, tuple[float, float, float]]:
    """Apply static UE light properties shared by point and spot components."""
    # ``IntensityNits`` is normally UE's derived source-surface luminance for
    # a lumens/candelas light. It is the authoring value only when Intensity is
    # omitted (or explicitly null), so don't replace an authored lumen value
    # with its radius-dependent nits conversion.
    raw_intensity = props.get("Intensity")
    intensity_source = "Intensity"
    if raw_intensity is None:
        raw_intensity = props.get("IntensityNits", 0.0)
        intensity_source = "IntensityNits"

    intensity = float_or_default(raw_intensity)
    set_light_energy(light_data, intensity * exposure_mult)
    intensity_units = props.get("IntensityUnits")
    if isinstance(intensity_units, str):
        light_data["ue_intensity_units"] = intensity_units
    light_data["ue_intensity_source"] = intensity_source
    if props.get("IntensityNits") is not None:
        light_data["ue_intensity_nits"] = float_or_default(props.get("IntensityNits"))

    color_dict = props.get("LightColor", {})
    r = float_or_default(color_dict.get("R", 255.0), 255.0) / 255.0
    g = float_or_default(color_dict.get("G", 255.0), 255.0) / 255.0
    b = float_or_default(color_dict.get("B", 255.0), 255.0) / 255.0
    set_light_color(light_data, (r, g, b))

    light_data.use_shadow = always_cast_shadows or bool_or_default(
        props.get("CastShadows", True), True,
    )

    apply_ue_attenuation_properties(
        light_data,
        props,
        location_scale=location_scale,
        attenuation_radius_mult=attenuation_radius_mult,
    )

    temperature = get_light_temperature(props)
    if temperature is not None:
        if hasattr(light_data, "use_temperature"):
            light_data.use_temperature = True
        if hasattr(light_data, "temperature"):
            light_data.temperature = temperature

    if VOLUMETRIC_SCATTERING_PROP in props:
        light_data[VOLUMETRIC_SCATTERING_PROP] = float_or_default(
            props.get(VOLUMETRIC_SCATTERING_PROP),
            0.0,
        )

    return light_data.energy, light_data.color


def apply_ue_attenuation_properties(
    light_data: bpy.types.Light,
    props: dict,
    location_scale: float = 0.01,
    attenuation_radius_mult: float = 1.0,
) -> None:
    """Apply the shared UE local-light attenuation setup without changing power or color.

    This is intentionally separate from ``apply_common_static_light_properties``
    so sequencer imports can use the same node graph while retaining animated
    energy and color curves on the Blender light datablock.
    """
    if light_data is None:
        return

    raw_source_radius = props.get("SourceRadius", DEFAULT_SOURCE_RADIUS_CM)
    if raw_source_radius is None:
        raw_source_radius = DEFAULT_SOURCE_RADIUS_CM
    src_radius = float_or_default(raw_source_radius) * location_scale
    if hasattr(light_data, "shadow_soft_size"):
        light_data.shadow_soft_size = src_radius

    att_radius = (
        float_or_default(props.get("AttenuationRadius", 0.0))
        * location_scale
        * max(float_or_default(attenuation_radius_mult, 1.0), 0.0)
    )
    use_inverse_squared = bool_or_default(props.get("bUseInverseSquaredFalloff", True), True)
    falloff_exponent = float_or_default(props.get("LightFalloffExponent", 8.0), 8.0)

    light_data[UE_ATTENUATION_RADIUS_PROP] = att_radius
    light_data[UE_ATTENUATION_RADIUS_UNITS_PROP] = "Blender units"
    light_data[UE_INVERSE_SQUARED_FALLOFF_PROP] = use_inverse_squared
    light_data[UE_DISABLE_CUSTOM_ATTENUATION_PROP] = False
    light_data[UE_LIGHT_FALLOFF_EXPONENT_PROP] = falloff_exponent
    light_data[UE_SOURCE_RADIUS_PROP] = src_radius

    if hasattr(light_data, "use_custom_distance"):
        light_data.use_custom_distance = att_radius > 0.0
    if hasattr(light_data, "cutoff_distance"):
        light_data.cutoff_distance = att_radius

    apply_ue_attenuation_nodes(
        light_data, attenuation_radius=att_radius,
    )

def apply_ue_light_object_properties(
    light_obj: bpy.types.Object,
    remove_from_data: bool = True,
) -> None:
    """Move UE light custom properties from the light datablock to its object."""
    if light_obj is None:
        return
    light_data = getattr(light_obj, "data", None)
    if light_data is None:
        return

    for prop_name in UE_LIGHT_OBJECT_PROPS:
        if prop_name not in light_data:
            continue
        light_obj[prop_name] = light_data[prop_name]
        if remove_from_data:
            try:
                del light_data[prop_name]
            except Exception:
                pass


def apply_spot_cone_properties(light_data: bpy.types.Light, props: dict) -> None:
    """Apply UE full cone angles to a Blender spot light."""
    inner_full_deg = float_or_default(
        props.get("InnerFullConeAngle", DEFAULT_SPOT_FULL_CONE_ANGLE_DEG),
        DEFAULT_SPOT_FULL_CONE_ANGLE_DEG,
    )
    # UE serializes default-valued properties sparsely.  A missing outer cone
    # therefore means its 90-degree default, rather than the supplied inner
    # cone (which only defines the fully-lit centre of that cone).
    outer_full_deg = float_or_default(
        props.get("OuterFullConeAngle", DEFAULT_SPOT_FULL_CONE_ANGLE_DEG),
        DEFAULT_SPOT_FULL_CONE_ANGLE_DEG,
    )
    if outer_full_deg <= 0.0:
        return

    light_data.spot_size = math.radians(outer_full_deg)
    light_data.spot_blend = min(1.0, max(0.0, 1.0 - (inner_full_deg / outer_full_deg)))


def create_static_light_data(
    name: str,
    light_type: str,
    props: dict,
    location_scale: float = 0.01,
    exposure_mult: float = 1.0,
    attenuation_radius_mult: float = 1.0,
    always_cast_shadows: bool = False,
) -> bpy.types.Light:
    """Create and configure Blender light data from static UE component props."""
    light_data = bpy.data.lights.new(name, light_type)
    apply_default_light_options(light_data, location_scale)
    apply_common_static_light_properties(
        light_data,
        props,
        location_scale,
        exposure_mult,
        attenuation_radius_mult,
        always_cast_shadows,
    )
    if light_type == "SPOT":
        apply_spot_cone_properties(light_data, props)
    return light_data
