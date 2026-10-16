"""One row layout for every package UMAP importer."""

from .textures import draw_texture_options


def _cell(row, operator, name, *, enabled=True, text=None):
    cell = row.column(align=True)
    cell.enabled = enabled
    cell.prop(operator, name, **({"text": text} if text is not None else {}))


def draw_package_map_options(layout, operator, *, massive_environment=False):
    """Keep the same order and dependencies in title and generic dialogs."""
    row = layout.row(align=True)
    _cell(row, operator, "recursive_import")
    _cell(row, operator, "scale_factor")

    row = layout.row(align=True)
    _cell(row, operator, "import_models")
    _cell(row, operator, "offset_opposite_faces", enabled=operator.import_models)
    _cell(row, operator, "import_textures", enabled=operator.import_models)
    textures = layout.column(align=True)
    textures.enabled = operator.import_models and operator.import_textures
    draw_texture_options(textures, operator)

    layout.separator()
    lights_enabled = operator.import_point_lights or operator.import_spot_lights
    row = layout.row(align=True)
    _cell(row, operator, "import_point_lights")
    _cell(row, operator, "import_spot_lights")
    _cell(row, operator, "always_cast_shadows", enabled=lights_enabled)
    row = layout.row(align=True)
    _cell(row, operator, "exposure", enabled=lights_enabled)
    _cell(row, operator, "attenuation_radius_mult", enabled=lights_enabled)
    _cell(row, operator, "import_light_probes")

    if massive_environment:
        box = layout.box()
        box.label(text="Massive Environment")
        options = box.column(align=True)
        options.enabled = operator.import_models
        row = options.row(align=True)
        _cell(row, operator, "import_originals")
        _cell(row, operator, "import_sway", text="Wind sway as shape keys")
        options.prop(operator, "lod_mode", expand=True)
        if operator.lod_mode == "QUALITY":
            options.prop(operator, "lod_quality", slider=True)
        elif operator.lod_mode == "LEVEL":
            options.prop(operator, "lod_level", slider=True)
