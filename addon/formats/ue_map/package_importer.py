"""Game-neutral package UMAP operator definitions and dialog lifecycle.

Title modules supply a source (browser/index configuration and import backend).
All standard UMAP operators use this factory, including generic Unreal. Keep
new options, persistence, dialog sizing and capability sections here.
"""

from dataclasses import dataclass

import bpy

from ...core.blender.reporting import SQEX_LoggedOperator, report
from ...games import package_browser
from ...language import tooltips
from ...ui.map_importer import draw_package_map_options
from ...ui.textures import TEXTURE_OPTION_NAMES, texture_properties


# One width for every standard package UMAP dialog.
UMAP_DIALOG_WIDTH = 1000
UMAP_BROWSER_ROWS = 12


MAP_OPTION_NAMES = (
    "recursive_import", "scale_factor", "import_models", "offset_opposite_faces",
    "import_textures", *TEXTURE_OPTION_NAMES, "import_point_lights", "import_spot_lights",
    "always_cast_shadows", "exposure", "attenuation_radius_mult", "import_light_probes",
)


def map_properties(*, offset_faces_default=False, light_probes_default=False):
    """Return fresh RNA properties so operator settings stay independent."""
    return {
        **texture_properties(),
        "recursive_import": bpy.props.BoolProperty(
            name="Recursively import streaming levels", default=False,
            description=tooltips.MAP_RECURSIVE_IMPORT),
        "scale_factor": bpy.props.FloatProperty(
            name="Scale", default=0.01, min=0.000001, max=100.0,
            description=tooltips.SHARED_SCALE_FACTOR),
        "import_models": bpy.props.BoolProperty(
            name="Import models", default=True, description=tooltips.MAP_IMPORT_MODELS),
        "offset_opposite_faces": bpy.props.BoolProperty(
            name="Offset overlapping faces", default=offset_faces_default,
            description=tooltips.SHARED_OFFSET_OPPOSITE_FACES),
        "import_textures": bpy.props.BoolProperty(
            name="Import and pack DDS textures", default=True,
            description=tooltips.MAP_IMPORT_TEXTURES),
        "import_point_lights": bpy.props.BoolProperty(
            name="Import point lights", default=True, description=tooltips.MAP_IMPORT_POINT_LIGHTS),
        "import_spot_lights": bpy.props.BoolProperty(
            name="Import spot lights", default=True, description=tooltips.MAP_IMPORT_SPOT_LIGHTS),
        "always_cast_shadows": bpy.props.BoolProperty(
            name="Always cast shadows", default=False, description=tooltips.MAP_ALWAYS_CAST_SHADOWS),
        "exposure": bpy.props.FloatProperty(
            name="Light exposure", default=0.0, min=-16.0, max=16.0,
            description=tooltips.MAP_EXPOSURE),
        "attenuation_radius_mult": bpy.props.FloatProperty(
            name="Attenuation Radius Multiplier", default=1.0, min=0.0, max=100.0,
            description=tooltips.MAP_ATTENUATION_RADIUS_MULT),
        "import_light_probes": bpy.props.BoolProperty(
            name="Generate light probes", default=light_probes_default, description=tooltips.MAP_IMPORT_LIGHT_PROBES),
    }


def load_map_import_settings(operator, context):
    """Migrate the remembered master light switch into the two visible controls."""
    operator._load_last_import_settings(context)
    if not operator.import_lights:
        operator.import_point_lights = False
        operator.import_spot_lights = False
        operator.import_lights = True


MASSIVE_ENVIRONMENT_OPTION_NAMES = (
    "import_originals", "import_sway", "lod_mode", "lod_quality", "lod_level",
)


def massive_environment_properties():
    return {
        "import_originals": bpy.props.BoolProperty(name="Import originals at origin", default=False),
        "import_sway": bpy.props.BoolProperty(name="Wind sway as shape keys", default=True),
        "lod_mode": bpy.props.EnumProperty(
            name="LoD level", default="QUALITY", items=(
                ("QUALITY", "Quality", tooltips.REBIRTH_MEC_LOD_MODE_QUALITY),
                ("LEVEL", "Level", tooltips.REBIRTH_MEC_LOD_MODE_LEVEL),
                ("ALL", "All LoDs", tooltips.REBIRTH_MEC_LOD_MODE_ALL),
            )),
        "lod_quality": bpy.props.FloatProperty(name="Quality", default=1.0, min=0.0, max=1.0, subtype='FACTOR'),
        "lod_level": bpy.props.IntProperty(name="Level", default=0, min=-13, max=0),
    }


@dataclass
class MapBrowserState:
    browser: dict
    paths: list
    key: object = None
    ready: bool = True
    source: str = "mounted packages"
    messages: tuple = ()


@dataclass
class PackageMapSource:
    """Source configuration and backend hooks; common map controls stay here."""
    game_label: str
    browser_state: object
    execute: object
    defaults: object = None
    configure: object = None


class PackageMapOperator:
    """Shared lifecycle; concrete RNA properties are added by the factory."""

    def invoke(self, context, _event):
        source = self._map_source
        try:
            if source.defaults is not None:
                source.defaults(self, context)
            load_map_import_settings(self, context)
            state = source.browser_state(self, context, refresh=True)
            if state.ready and not state.paths:
                raise ValueError(f"No {source.game_label} UMAP assets were found.")
            package_browser.activate(context, state.browser, state.paths, dialog_operator=self.bl_idname)
            self._map_browser_key = state.key
        except Exception as exc:
            report(self, {"ERROR"}, f"{source.game_label} UMAP index failed: {exc}")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=UMAP_DIALOG_WIDTH)

    def check(self, context):
        state = self._map_source.browser_state(self, context)
        if getattr(self, "_map_browser_key", None) != state.key:
            package_browser.activate(context, state.browser, state.paths, dialog_operator=self.bl_idname)
            self._map_browser_key = state.key
        return True

    def draw(self, context):
        layout = self.layout
        source = self._map_source
        if source.configure is not None:
            source.configure(self, context, layout)
        state = source.browser_state(self, context)
        browser = layout.column()
        browser.enabled = state.ready
        package_browser.draw(browser, context, state.browser, rows=UMAP_BROWSER_ROWS)
        if state.ready:
            layout.label(text=f"{len(state.paths):,} {source.game_label} UMAP assets indexed ({state.source})", icon="PACKAGE")
        else:
            layout.label(text="Load the asset list after choosing or changing mount settings.", icon="INFO")
        for text, icon in state.messages:
            layout.label(text=text, icon=icon)
        layout.separator()
        draw_package_map_options(layout, self, massive_environment=self._massive_environment)

    def cancel(self, context):
        self._save_last_import_settings(context)

    def execute(self, context):
        try:
            result = self._map_source.execute(self, context)
        except Exception as exc:
            report(self, {"ERROR"}, f"{self._map_source.game_label} UMAP import failed: {exc}")
            return {"CANCELLED"}
        if result == {"FINISHED"}:
            self._save_last_import_settings(context)
        return result


def make_package_map_importer(*, class_name, bl_idname, source, module_name,
                              massive_environment=False, offset_faces_default=False,
                              light_probes_default=False, configuration_properties=None,
                              persisted_configuration=()):
    """Build every standard package UMAP operator from the same definition."""
    properties = {
        **map_properties(offset_faces_default=offset_faces_default, light_probes_default=light_probes_default),
        "virtual_path": bpy.props.StringProperty(
            name="UMAP Path", description=tooltips.MAP_VIRTUAL_PATH, options={"HIDDEN"}),
        # Existing scripts and saved preferences can still use the old master switch.
        "import_lights": bpy.props.BoolProperty(
            name="Import Lights", default=True, options={"HIDDEN"}, description=tooltips.MAP_IMPORT_LIGHTS),
    }
    persisted = (*MAP_OPTION_NAMES, "import_lights", *persisted_configuration)
    if massive_environment:
        properties.update(massive_environment_properties())
        persisted += MASSIVE_ENVIRONMENT_OPTION_NAMES
    if configuration_properties is not None:
        properties.update(configuration_properties)
    return type(class_name, (PackageMapOperator, SQEX_LoggedOperator), {
        "__module__": module_name,
        "__annotations__": properties,
        "bl_idname": bl_idname,
        "bl_label": f"UMAP from {source.game_label} Packages",
        "bl_description": tooltips.MAP_DESCRIPTION.format(game_label=source.game_label),
        "bl_options": {"REGISTER", "UNDO"},
        "_persisted_props": persisted,
        "_map_source": source,
        "_massive_environment": massive_environment,
        "mesh_kind": "UMAP",
    })
