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


class DATA_PT_sqex_ue4_light_attenuation(bpy.types.Panel):
    bl_idname = "DATA_PT_sqex_ue4_light_attenuation"
    bl_label = "Talisman Light Attenuation"
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
        inverse_owner = _draw_custom_property(
            settings,
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
        _draw_custom_property(
            settings,
            light_object,
            lights.UE_SOURCE_RADIUS_PROP,
            "Source Radius",
        )
        layout.label(text="Values are UE properties retained from the imported light.", icon="INFO")


CLASSES = (DATA_PT_sqex_ue4_light_attenuation,)
