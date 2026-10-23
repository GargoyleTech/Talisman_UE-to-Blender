"""Shared light parsing and creation helpers for Unreal map imports."""

from __future__ import annotations

import math

import bpy

from . import light_photometry as photometry


UE_LIGHT_TYPES: dict[str, str] = {
    "SpotLight": "SPOT",
    "SpotLightComponent": "SPOT",
    "PointLight": "POINT",
    "PointLightComponent": "POINT",
    "RectLight": "AREA",
    "RectLightComponent": "AREA",
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
UE_LIGHT_ATTENUATION_GROUP_VERSION = 3  # Internal node schema, not the add-on version.
UE_LIGHT_KIND_PROP = "ue_light_kind"
UE_DISTANCE_BIAS_PROP = "ue_distance_bias_squared"
UE_INNER_CONE_PROP = "ue_inner_cone_half_angle"
UE_OUTER_CONE_PROP = "ue_outer_cone_half_angle"
UE_SOFT_SOURCE_RADIUS_PROP = "ue_soft_source_radius"
UE_SOURCE_LENGTH_PROP = "ue_source_length"
UE_SOURCE_WIDTH_PROP = "ue_source_width"
UE_SOURCE_HEIGHT_PROP = "ue_source_height"
UE_BARN_ANGLE_PROP = "ue_barn_door_angle_radians"
UE_BARN_LENGTH_PROP = "ue_barn_door_length"
UE_SAMPLE_OFFSET_PROP = "ue_source_sample_offset"
UE_SAMPLE_COUNT_PROP = "ue_source_sample_count"
UE_INTENSITY_PROP = "ue_intensity"
UE_UNIT_CODE_PROP = "ue_intensity_unit_code"
UE_SCALE_PROP = "ue_light_import_scale"
UE_EXPOSURE_PROP = "ue_light_exposure_multiplier"
UE_EFFICACY_PROP = "ue_lumens_per_watt"
UE_TEMPERATURE_PROP = "ue_temperature"
UE_USE_TEMPERATURE_PROP = "ue_use_temperature"

UE_LIGHT_OBJECT_PROPS = (
    UE_ATTENUATION_RADIUS_PROP,
    UE_ATTENUATION_RADIUS_UNITS_PROP,
    UE_INVERSE_SQUARED_FALLOFF_PROP,
    UE_DISABLE_CUSTOM_ATTENUATION_PROP,
    UE_LIGHT_FALLOFF_EXPONENT_PROP,
    UE_SOURCE_RADIUS_PROP,
    UE_LIGHT_KIND_PROP, UE_DISTANCE_BIAS_PROP, UE_INNER_CONE_PROP, UE_OUTER_CONE_PROP,
    UE_SOFT_SOURCE_RADIUS_PROP, UE_SOURCE_LENGTH_PROP, UE_SOURCE_WIDTH_PROP, UE_SOURCE_HEIGHT_PROP,
    UE_BARN_ANGLE_PROP, UE_BARN_LENGTH_PROP, UE_SAMPLE_OFFSET_PROP, UE_SAMPLE_COUNT_PROP,
    UE_INTENSITY_PROP, UE_UNIT_CODE_PROP, UE_SCALE_PROP, UE_EXPOSURE_PROP, UE_EFFICACY_PROP,
    UE_TEMPERATURE_PROP, UE_USE_TEMPERATURE_PROP,
)

DEFAULT_SOURCE_RADIUS_CM = 0.0
DEFAULT_ATTENUATION_RADIUS_CM = 1000.0
DEFAULT_RECT_SIZE_CM = 64.0
DEFAULT_LOCAL_INTENSITY = 5000.0
# FF7 full-angle export dialect; stock UE4 uses 44-degree half angles.
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
        light_data.normalize = True
    if hasattr(light_data, "shadow_soft_size"):
        light_data.shadow_soft_size = DEFAULT_SOURCE_RADIUS_CM * location_scale


def set_light_energy(light_data: bpy.types.Light, energy: float) -> None:
    """Set power on the light."""
    light_data.energy = energy


def apply_light_exposure(light_data, exposure_mult):
    """Set native exposure in stops and return any remaining power multiplier."""
    multiplier = max(0.0, float(exposure_mult))
    if hasattr(light_data, "exposure"):
        light_data.exposure = math.log2(multiplier) if multiplier > 0 else 0.0
        return 1.0 if multiplier > 0 else 0.0
    return multiplier


def set_light_color(
    light_data: bpy.types.Light,
    color: tuple[float, float, float],
) -> None:
    """Set color on the light."""
    light_data.color = color


def get_ue_light_attenuation_group() -> bpy.types.NodeTree:
    from .light_nodes import attenuation_group
    group = attenuation_group()
    group["sqex_group_version"] = UE_LIGHT_ATTENUATION_GROUP_VERSION
    return group


def apply_ue_attenuation_nodes(light_data: bpy.types.Light, attenuation_radius: float) -> bool:
    """Attach the shared UE attenuation node group to one local light."""
    if not hasattr(light_data, "node_tree"):
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
        attenuation.label = "UE4 radial and emitter masks (Cycles)"
        output.location = (440, 0)
        emission.location = (220, 0)
        attenuation.location = (-80, 0)
        emission.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        links.new(attenuation.outputs["Strength"], emission.inputs["Strength"])
        links.new(emission.outputs["Emission"], output.inputs["Surface"])
        # Cycles multiplies the shader by native power/color in supported 4.x
        # and 5.x releases. Only pre-4.5 temperature needs a node fallback.
        if not hasattr(light_data, 'temperature'):
            from .light_rig import bind_temperature_nodes
            bind_temperature_nodes(light_data, emission)
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
    """Apply static UE local-light properties."""
    apply_ue_attenuation_properties(light_data, props, location_scale, attenuation_radius_mult)
    # Derived nits never override an authored Intensity value.
    raw_intensity = props.get("Intensity")
    intensity_source = "Intensity"
    if raw_intensity is None:
        raw_intensity = props.get("IntensityNits", DEFAULT_LOCAL_INTENSITY)
        intensity_source = "IntensityNits" if props.get("IntensityNits") is not None else "Intensity"

    intensity = float_or_default(raw_intensity)
    intensity_units = props.get("IntensityUnits", "ELightUnits::Unitless")
    light_data['ue_authored_intensity_units'] = str(intensity_units)
    if intensity_source == "IntensityNits":
        intensity_units = "Nits"
    light_data["ue_intensity_units"] = str(intensity_units)
    light_data[UE_INTENSITY_PROP] = intensity
    light_data[UE_UNIT_CODE_PROP] = photometry.UNIT_CODES.get(photometry.unit_name(intensity_units), 0)
    light_data[UE_EXPOSURE_PROP] = exposure_mult
    light_data[UE_EFFICACY_PROP] = photometry.LUMENS_PER_WATT
    set_light_energy(light_data, photometry.radiant_power(
        light_data.type, intensity, intensity_units,
        inverse_squared=light_data[UE_INVERSE_SQUARED_FALLOFF_PROP], scale=location_scale,
        exposure=apply_light_exposure(light_data, exposure_mult), outer=light_data.get(UE_OUTER_CONE_PROP, math.radians(44)),
        radius=light_data[UE_SOURCE_RADIUS_PROP], length=light_data[UE_SOURCE_LENGTH_PROP],
        width=light_data[UE_SOURCE_WIDTH_PROP], height=light_data[UE_SOURCE_HEIGHT_PROP]))
    light_data["ue_intensity_source"] = intensity_source
    if props.get("IntensityNits") is not None:
        light_data["ue_intensity_nits"] = float_or_default(props.get("IntensityNits"))

    set_light_color(light_data, photometry.light_color(props))

    light_data.use_shadow = always_cast_shadows or bool_or_default(
        props.get("CastShadows", True), True,
    )

    temperature = get_light_temperature(props) or 6500.0
    light_data[UE_TEMPERATURE_PROP] = temperature
    light_data[UE_USE_TEMPERATURE_PROP] = bool_or_default(props.get("bUseTemperature", False))
    if hasattr(light_data, "use_temperature"):
        light_data.use_temperature = light_data[UE_USE_TEMPERATURE_PROP]
        light_data.temperature = temperature

    light_data[VOLUMETRIC_SCATTERING_PROP] = float_or_default(props.get(VOLUMETRIC_SCATTERING_PROP), 1.0)

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

    default_source_radius = DEFAULT_SOURCE_RADIUS_CM
    raw_source_radius = props.get("SourceRadius", default_source_radius)
    if raw_source_radius is None:
        raw_source_radius = default_source_radius
    src_radius = max(0, float_or_default(raw_source_radius)) * location_scale
    if hasattr(light_data, "shadow_soft_size"):
        light_data.shadow_soft_size = src_radius

    att_radius = (
        max(0, float_or_default(props.get("AttenuationRadius"), DEFAULT_ATTENUATION_RADIUS_CM))
        * location_scale
        * max(float_or_default(attenuation_radius_mult, 1.0), 0.0)
    )
    use_inverse_squared = light_data.type == "AREA" or bool_or_default(props.get("bUseInverseSquaredFalloff", True), True)
    falloff_exponent = max(0.0001, float_or_default(props.get("LightFalloffExponent", 8.0), 8.0))

    light_data[UE_ATTENUATION_RADIUS_PROP] = att_radius
    light_data[UE_ATTENUATION_RADIUS_UNITS_PROP] = "Blender units"
    light_data[UE_INVERSE_SQUARED_FALLOFF_PROP] = use_inverse_squared
    light_data[UE_DISABLE_CUSTOM_ATTENUATION_PROP] = False
    light_data[UE_LIGHT_FALLOFF_EXPONENT_PROP] = falloff_exponent
    light_data[UE_SOURCE_RADIUS_PROP] = src_radius
    light_data[UE_SCALE_PROP] = location_scale
    light_data[UE_DISTANCE_BIAS_PROP] = location_scale ** 2
    light_data[UE_LIGHT_KIND_PROP] = {'POINT': 0, 'SPOT': 1, 'AREA': 2}[light_data.type]
    light_data[UE_SOFT_SOURCE_RADIUS_PROP] = max(0, float_or_default(props.get('SoftSourceRadius'))) * location_scale
    light_data[UE_SOURCE_LENGTH_PROP] = max(0, float_or_default(props.get('SourceLength'))) * location_scale
    light_data[UE_SOURCE_WIDTH_PROP] = max(1e-6, float_or_default(props.get('SourceWidth'), DEFAULT_RECT_SIZE_CM) * location_scale)
    light_data[UE_SOURCE_HEIGHT_PROP] = max(1e-6, float_or_default(props.get('SourceHeight'), DEFAULT_RECT_SIZE_CM) * location_scale)
    light_data[UE_BARN_ANGLE_PROP] = math.radians(min(88, max(0, float_or_default(props.get('BarnDoorAngle'), 88))))
    light_data[UE_BARN_LENGTH_PROP] = max(0.1, float_or_default(props.get('BarnDoorLength'), 20)) * location_scale
    light_data[UE_SAMPLE_OFFSET_PROP] = (0.0, 0.0, 0.0)
    light_data[UE_SAMPLE_COUNT_PROP] = 1.0
    light_data['ue_light_profile'] = props.get('_ue_light_profile', 'UE4')
    if light_data.type == 'SPOT':
        apply_spot_cone_properties(light_data, props)
    elif light_data.type == 'AREA':
        light_data.shape = 'RECTANGLE'
        light_data.size = light_data[UE_SOURCE_WIDTH_PROP]
        light_data.size_y = light_data[UE_SOURCE_HEIGHT_PROP]
        light_data['ue_barn_door_angle'] = math.degrees(light_data[UE_BARN_ANGLE_PROP])
        light_data['ue_barn_door_length_cm'] = light_data[UE_BARN_LENGTH_PROP] / location_scale
        if props.get('SourceTexture'):
            source = props['SourceTexture']
            light_data['ue_source_texture'] = str(source.get('ObjectPath') or source.get('ObjectName') or '') if isinstance(source, dict) else str(source)

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
    from .light_rig import bind_light_controls, ensure_source_helpers
    bind_light_controls(light_obj)
    ensure_source_helpers(light_obj)


def apply_spot_cone_properties(light_data: bpy.types.Light, props: dict) -> None:
    """Use a hard native cone; the node group supplies the UE cosine falloff."""
    inner, outer = photometry.cone_angles(props, props.get('_ue_light_profile', 'UE4'))
    light_data[UE_INNER_CONE_PROP], light_data[UE_OUTER_CONE_PROP] = inner, outer
    light_data.spot_size = min(math.pi, 2 * outer)
    light_data.spot_blend = 0.0


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
    if light_type == "SUN":
        # UE directional intensity is illuminance (lux). Blender sun energy is
        # irradiance; keep the same 683 lm/W scene calibration as local lights.
        intensity = max(0.0, float_or_default(props.get("Intensity"), 10.0))
        light_data["ue_intensity"] = intensity
        light_data["ue_intensity_units"] = "Lux"
        light_data["ue_light_exposure_multiplier"] = exposure_mult
        set_light_energy(light_data, intensity * apply_light_exposure(light_data, exposure_mult) / photometry.LUMENS_PER_WATT)
        set_light_color(light_data, photometry.light_color(props))
        light_data.angle = math.radians(max(0.0, min(180.0, float_or_default(props.get("LightSourceAngle"), 0.5357))))
        light_data.use_shadow = always_cast_shadows or bool_or_default(props.get("CastShadows"), True)
        if hasattr(light_data, "use_temperature"):
            light_data.use_temperature = bool_or_default(props.get("bUseTemperature"))
            light_data.temperature = get_light_temperature(props) or 6500.0
        light_data[VOLUMETRIC_SCATTERING_PROP] = float_or_default(props.get(VOLUMETRIC_SCATTERING_PROP), 1.0)
        return light_data
    apply_default_light_options(light_data, location_scale)
    apply_common_static_light_properties(
        light_data,
        props,
        location_scale,
        exposure_mult,
        attenuation_radius_mult,
        always_cast_shadows,
    )
    return light_data


def apply_source_texture(light_obj, image_loader=None):
    """Resolve a rect source through the import session or an already loaded image."""
    if light_obj.type != 'LIGHT' or light_obj.data.type != 'AREA':
        return False
    data = light_obj.data
    path = data.get('ue_source_texture', '')
    if not path:
        return False
    if "'" in path:
        path = path.split("'", 2)[1]
    image = image_loader(path) if image_loader is not None else next((image for image in bpy.data.images
        if image.get('ue_virtual_path', '').casefold() == path.casefold()), None)
    if image is None:
        data['ue_source_texture_status'] = 'Texture unavailable; neutral emission'
        return False
    tree = data.node_tree
    emission = next(node for node in tree.nodes if node.label == UE_LIGHT_EMISSION_NODE_LABEL)
    texture = tree.nodes.get('UE4 Rect Source Texture') or tree.nodes.new('ShaderNodeTexImage')
    texture.name = texture.label = 'UE4 Rect Source Texture'
    texture.image = image
    texture.extension = 'EXTEND'
    texture.location = (-550, -280)
    coords = tree.nodes.get('UE4 Rect UV') or tree.nodes.new('ShaderNodeTexCoord')
    coords.name = coords.label = 'UE4 Rect UV'
    coords.location = (-780, -280)
    tree.links.new(coords.outputs['UV'], texture.inputs['Vector'])
    if tree.nodes.get('UE4 Temperature Tint') is None:
        tree.links.new(texture.outputs['Color'], emission.inputs['Color'])
    else:
        from .light_rig import bind_temperature_texture
        bind_temperature_texture(data, texture, emission)
    data['ue_source_texture_status'] = 'Loaded'
    return True


def animation_property(light_obj, name):
    """Resolve a Sequencer channel to the same controls used by map lights."""
    scale = light_obj.get(UE_SCALE_PROP, 0.01)
    mapping = {
        'Intensity': (UE_INTENSITY_PROP, 1), 'Brightness': (UE_INTENSITY_PROP, 1),
        'AttenuationRadius': (UE_ATTENUATION_RADIUS_PROP, scale),
        'LightFalloffExponent': (UE_LIGHT_FALLOFF_EXPONENT_PROP, 1),
        'bUseInverseSquaredFalloff': (UE_INVERSE_SQUARED_FALLOFF_PROP, 1),
        'SourceRadius': (UE_SOURCE_RADIUS_PROP, scale),
        'SoftSourceRadius': (UE_SOFT_SOURCE_RADIUS_PROP, scale),
        'SourceLength': (UE_SOURCE_LENGTH_PROP, scale),
        'SourceWidth': (UE_SOURCE_WIDTH_PROP, scale), 'SourceHeight': (UE_SOURCE_HEIGHT_PROP, scale),
        'BarnDoorAngle': (UE_BARN_ANGLE_PROP, math.pi / 180),
        'BarnDoorLength': (UE_BARN_LENGTH_PROP, scale),
        'InnerConeAngle': (UE_INNER_CONE_PROP, math.pi / 180),
        'OuterConeAngle': (UE_OUTER_CONE_PROP, math.pi / 180),
        'InnerFullConeAngle': (UE_INNER_CONE_PROP, math.pi / 360),
        'OuterFullConeAngle': (UE_OUTER_CONE_PROP, math.pi / 360),
        'Temperature': (UE_TEMPERATURE_PROP, 1), 'ColorTemperature': (UE_TEMPERATURE_PROP, 1),
        'bUseTemperature': (UE_USE_TEMPERATURE_PROP, 1),
    }
    if name in mapping:
        prop, factor = mapping[name]
        if prop not in light_obj:
            return None
        return light_obj, f'["{prop}"]', factor
    if name == 'LightColor':
        return light_obj.data, 'color', 1
    if name == 'CastShadows':
        return light_obj.data, 'use_shadow', 1
    if name == VOLUMETRIC_SCATTERING_PROP:
        return light_obj.data, f'["{VOLUMETRIC_SCATTERING_PROP}"]', 1
    return None


def apply_component_visibility(obj: bpy.types.Object, props: dict) -> None:
    """Keep authored hidden components editable without lighting the render."""
    visible = bool_or_default(props.get("bVisible", True), True)
    affects_world = bool_or_default(props.get("bAffectsWorld", True), True)
    hidden_in_game = bool_or_default(props.get("bHiddenInGame", False))
    obj.hide_viewport = not visible or not affects_world
    obj.hide_render = not visible or not affects_world or hidden_in_game
    obj["ue_visible"] = visible
    obj["ue_hidden_in_game"] = hidden_in_game
