"""Shared texture memory controls for map importers."""

from ..language import strings

import bpy


TEXTURE_OPTION_NAMES = ("max_texture_resolution", "texture_mip_offset")
TEXTURE_RESOLUTION_ITEMS = (
    ("0", "0 (Unlimited)", "Keep the original texture resolution", 0),
    *((str(1 << exponent), str(1 << exponent), "Maximum texture width or height", exponent + 1)
      for exponent in range(31)),
)


def _snap_texture_resolution(operator, _context):
    value = operator.max_texture_resolution
    snapped = 1 << (value.bit_length() - 1) if value > 0 else 0
    if value != snapped:
        operator.max_texture_resolution = snapped


def _resolution_choice_get(operator):
    return operator.max_texture_resolution.bit_length()


def _resolution_choice_set(operator, value):
    operator.max_texture_resolution = 1 << (value - 1) if value else 0


def texture_properties():
    return {
        "max_texture_resolution": bpy.props.IntProperty(
            name="Max Texture Resolution", default=0, min=0, max=1 << 30, soft_max=8192,
            description=(strings.SHARED_MAX_TEXTURE_RESOLUTION),
            update=_snap_texture_resolution, options={"HIDDEN"},
        ),
        # Keep the integer API and saved importer settings compatible. Only the
        # UI uses an enum, so its arrows/dropdown select discrete powers of two.
        "max_texture_resolution_choice": bpy.props.EnumProperty(
            name="Max Texture Resolution", items=TEXTURE_RESOLUTION_ITEMS,
            get=_resolution_choice_get, set=_resolution_choice_set,
            description=strings.SHARED_MAX_TEXTURE_RESOLUTION,
            options={"SKIP_SAVE"},
        ),
        "texture_mip_offset": bpy.props.IntProperty(
            name="Texture Mip Offset", default=0, min=-16, max=0,
            description=(strings.SHARED_TEXTURE_MIP_OFFSET),
        ),
    }


def texture_options(operator):
    return {name: getattr(operator, name) for name in TEXTURE_OPTION_NAMES}


def draw_texture_options(layout, operator):
    box = layout.box()
    box.label(text="Texture Memory", icon="TEXTURE")
    for name in TEXTURE_OPTION_NAMES:
        box.prop(operator, "max_texture_resolution_choice" if name == "max_texture_resolution" else name)

