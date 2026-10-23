"""Geometry controls shared by generic Unreal static-mesh and map imports."""

import bpy

from ..language import strings


NANITE_OPTION_NAMES = ("nanite_mode", "max_nanite_triangles", "nanite_cache_mb")


def nanite_properties(*, default_mode="AUTO"):
    return {
        "nanite_mode": bpy.props.EnumProperty(
            name="Nanite Geometry", default=default_mode,
            items=(
                ("AUTO", "Auto", strings.GENERIC_NANITE_AUTO),
                ("NATIVE", "Native", strings.GENERIC_NANITE_NATIVE),
                ("FALLBACK", "Fallback", strings.GENERIC_NANITE_FALLBACK),
            ),
            description=strings.GENERIC_NANITE_MODE,
        ),
        "max_nanite_triangles": bpy.props.IntProperty(
            name="Max Native Triangles / Mesh", default=2_000_000, min=0,
            description=strings.GENERIC_NANITE_TRIANGLES,
        ),
        "nanite_cache_mb": bpy.props.IntProperty(
            name="Nanite Page Cache (MiB)", default=256, min=0, max=16384,
            description=strings.GENERIC_NANITE_CACHE,
        ),
    }


def nanite_options(operator):
    return {name: getattr(operator, name, default) for name, default in zip(
        NANITE_OPTION_NAMES, ("AUTO", 2_000_000, 256))}


def draw_nanite_options(layout, operator, *, enabled=True):
    box = layout.box()
    box.label(text="Nanite")
    box.enabled = enabled
    box.prop(operator, "nanite_mode", expand=True)
    controls = box.column(align=True)
    controls.enabled = operator.nanite_mode != "FALLBACK"
    controls.prop(operator, "max_nanite_triangles")
    controls.prop(operator, "nanite_cache_mb")
    controls.label(text="0 = unlimited. Limits apply to each source mesh.")
