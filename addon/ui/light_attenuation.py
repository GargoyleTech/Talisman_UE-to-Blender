"""Editable UI for Unreal local-light attenuation imported from UMAPs."""

from __future__ import annotations

import bpy

from ..formats.ue_map import lights


DISABLE_CUSTOM_ATTENUATION_PROP = getattr(
    lights,
    "UE_DISABLE_CUSTOM_ATTENUATION_PROP",
    "ue_disable_custom_attenuation",
)


def _property_owner(light_object: bpy.types.Object, property_name: str):
    """Return where an imported attenuation property is stored, if present."""
    light_data = getattr(light_object, "data", None)
    for owner in (light_object, light_data):
        if owner is not None and property_name in owner:
            return owner
    return None


def _draw_custom_property(layout, light_object: bpy.types.Object, property_name: str, text: str):
    owner = _property_owner(light_object, property_name)
    if owner is not None:
        layout.prop(owner, f'["{property_name}"]', text=text)
    return owner


class OBJECT_OT_sqex_refresh_light_source(bpy.types.Operator):
    bl_idname = "object.sqex_refresh_light_source"
    bl_label = "Refresh Source Shape"
    bl_description = "Reapply UE authoring values to the light and source helpers; baked lights remain baked"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (obj is not None and obj.type == 'LIGHT'
                and lights.UE_LIGHT_KIND_PROP in obj and not obj.get('ue_light_helper'))

    def execute(self, context):
        from ..formats.ue_map.light_rig import BAKED_PROP, bind_light_controls, ensure_source_helpers, bake_static_light_parameters
        was_baked = context.object.get(BAKED_PROP, False)
        bind_light_controls(context.object)
        ensure_source_helpers(context.object)
        if was_baked:
            bake_static_light_parameters([context.object])
        return {'FINISHED'}


class DATA_PT_sqex_ue4_light_attenuation(bpy.types.Panel):
    bl_idname = "DATA_PT_sqex_ue4_light_attenuation"
    bl_label = "Talisman UE4 Light"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        light_object = context.object
        if light_object is None or light_object.type != "LIGHT":
            return False
        return any(
            _property_owner(light_object, property_name) is not None
            for property_name in (
                lights.UE_ATTENUATION_RADIUS_PROP,
                lights.UE_INVERSE_SQUARED_FALLOFF_PROP,
                lights.UE_LIGHT_FALLOFF_EXPONENT_PROP,
                lights.UE_SOURCE_RADIUS_PROP,
            )
        )

    def draw(self, context):
        layout = self.layout
        light_object = context.object

        if light_object.get('ue_light_helper'):
            layout.label(text="Source sample; edit its parent light.", icon='INFO')
            return

        baked = light_object.get('ue_light_parameters_baked', False)
        if baked:
            layout.label(text="Baked: native light properties are editable.", icon='INFO')
            layout.prop(light_object.data, 'energy', text='Power')
            if hasattr(light_object.data, 'use_temperature'):
                layout.prop(light_object.data, 'use_temperature')
                layout.prop(light_object.data, 'temperature')
        elif lights.UE_INTENSITY_PROP in light_object:
            from ..formats.ue_map.light_photometry import unit_name
            units = unit_name(light_object[lights.UE_UNIT_CODE_PROP]).title()
            _draw_custom_property(layout, light_object, lights.UE_INTENSITY_PROP, f"Intensity ({units})")
            _draw_custom_property(layout, light_object, lights.UE_EXPOSURE_PROP, "Exposure Multiplier")
            _draw_custom_property(layout, light_object, lights.UE_EFFICACY_PROP, "Lumens per Watt")
            _draw_custom_property(layout, light_object, lights.UE_USE_TEMPERATURE_PROP, "Use Temperature")
            _draw_custom_property(layout, light_object, lights.UE_TEMPERATURE_PROP, "Temperature (K)")

        layout.separator()

        disable_owner = _draw_custom_property(
            layout,
            light_object,
            DISABLE_CUSTOM_ATTENUATION_PROP,
            "Use Blender Native Attenuation",
        )
        use_native = (
            bool(disable_owner[DISABLE_CUSTOM_ATTENUATION_PROP])
            if disable_owner else False
        )

        settings = layout.column()
        settings.enabled = not use_native
        _draw_custom_property(
            settings,
            light_object,
            lights.UE_ATTENUATION_RADIUS_PROP,
            "Attenuation Radius",
        )
        inverse = settings.column()
        inverse.enabled = light_object.data.type != 'AREA'
        inverse_owner = _draw_custom_property(
            inverse,
            light_object,
            lights.UE_INVERSE_SQUARED_FALLOFF_PROP,
            "Use Inverse-Squared Falloff",
        )

        exponent = settings.column()
        use_inverse_squared = (
            bool(inverse_owner[lights.UE_INVERSE_SQUARED_FALLOFF_PROP])
            if inverse_owner is not None else True
        )
        exponent.enabled = not use_inverse_squared
        _draw_custom_property(
            exponent,
            light_object,
            lights.UE_LIGHT_FALLOFF_EXPONENT_PROP,
            "Falloff Exponent",
        )
        shape = layout.column()
        if light_object.data.type in {'POINT', 'SPOT'}:
            if baked:
                shape.prop(light_object.data, 'shadow_soft_size', text='Source Radius')
                shape.label(text="Length/soft radius edits require Apply UE Controls.")
            for prop, label in ((lights.UE_SOURCE_RADIUS_PROP, 'Source Radius'),
                                (lights.UE_SOURCE_LENGTH_PROP, 'Source Length'),
                                (lights.UE_SOFT_SOURCE_RADIUS_PROP, 'Soft Source Radius')):
                if baked and prop == lights.UE_SOURCE_RADIUS_PROP:
                    continue
                _draw_custom_property(shape, light_object, prop, label)
            if lights.UE_LIGHT_KIND_PROP in light_object:
                shape.operator(OBJECT_OT_sqex_refresh_light_source.bl_idname,
                               text='Apply UE Controls' if baked else 'Refresh Source Shape')
                if not baked:
                    shape.label(text="Refresh after enabling length or soft radius.")
        if light_object.data.type == 'SPOT':
            if baked:
                shape.label(text="The UE cone mask also limits the beam.")
            _draw_custom_property(shape, light_object, lights.UE_INNER_CONE_PROP, 'Inner Half Angle')
            _draw_custom_property(shape, light_object, lights.UE_OUTER_CONE_PROP, 'Outer Half Angle')
        elif light_object.data.type == 'AREA':
            if baked:
                shape.prop(light_object.data, 'size', text='Source Width')
                shape.prop(light_object.data, 'size_y', text='Source Height')
            for prop, label in ((lights.UE_SOURCE_WIDTH_PROP, 'Source Width'),
                                (lights.UE_SOURCE_HEIGHT_PROP, 'Source Height'),
                                (lights.UE_BARN_ANGLE_PROP, 'Barn Door Angle'),
                                (lights.UE_BARN_LENGTH_PROP, 'Barn Door Length')):
                if baked and prop in {lights.UE_SOURCE_WIDTH_PROP, lights.UE_SOURCE_HEIGHT_PROP}:
                    label = 'Barn Mask Width' if prop == lights.UE_SOURCE_WIDTH_PROP else 'Barn Mask Height'
                _draw_custom_property(shape, light_object, prop, label)
            status = light_object.data.get('ue_source_texture_status')
            if status:
                shape.label(text='Source texture: ' + status)
        layout.label(text="Distances use Blender units.", icon="INFO")
        if context.scene.render.engine != 'CYCLES':
            layout.label(text="UE attenuation masks require Cycles.", icon="INFO")


CLASSES = (OBJECT_OT_sqex_refresh_light_source, DATA_PT_sqex_ue4_light_attenuation)
