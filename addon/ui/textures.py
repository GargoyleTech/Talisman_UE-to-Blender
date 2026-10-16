"""Shared texture memory controls for map importers."""

from ..language import tooltips

import bpy


TEXTURE_OPTION_NAMES = ("max_texture_resolution", "texture_mip_offset")


def texture_properties():
    return {
        "max_texture_resolution": bpy.props.IntProperty(
            name="Max Texture Resolution", default=0, min=0, soft_max=8192,
            description=(tooltips.SHARED_MAX_TEXTURE_RESOLUTION),
        ),
        "texture_mip_offset": bpy.props.IntProperty(
            name="Texture Mip Offset", default=0, min=-16, max=0,
            description=(tooltips.SHARED_TEXTURE_MIP_OFFSET),
        ),
    }


def texture_options(operator):
    return {name: getattr(operator, name) for name in TEXTURE_OPTION_NAMES}


def draw_texture_options(layout, operator):
    box = layout.box()
    box.label(text="Texture Memory", icon="TEXTURE")
    for name in TEXTURE_OPTION_NAMES:
        box.prop(operator, name)

