"""Blender dialog and explicit binding overrides for generic LevelSequences."""

from ...language import tooltips

import json
import math

import bpy

from ...core.blender.reporting import SQEX_LoggedOperator, report
from ...games import package_browser
from ...core.blender.collections import _active_collection
from . import importer, sequence_import, session
from .sequence_data import Graph, asset_path


_BROWSER = package_browser.make_state("Unreal LevelSequence assets", file_icon="CAMERA_DATA")
_INDEX = {}


def _config_properties():
    properties = importer._configuration_properties()
    return {key: properties[key] for key in ("cue4parse_profile", "path_filter")}


def _key(context, operator):
    return (session.source_id(importer._paths(context, operator, validate=False), importer._game_version(context, operator)),
            operator.path_filter.strip())


def _selected_path(context, operator):
    if operator.virtual_path.strip():
        return operator.virtual_path.strip()
    index = _INDEX.get(_key(context, operator))
    if index is None:
        raise ValueError("Load the sequence list first.")
    paths = package_browser.selected_paths(context, _BROWSER)
    if len(paths) != 1:
        raise ValueError("Select exactly one LevelSequence. Its nested shots are imported automatically.")
    if paths[0] not in index:
        raise ValueError("Refresh the sequence list after changing the game profile.")
    return paths[0]


def _binding_key(context, operator, path):
    return _key(context, operator)[0] + "|" + asset_path(path).casefold()


class SQEX_PG_generic_sequence_binding(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty()
    label: bpy.props.StringProperty()
    target: bpy.props.PointerProperty(type=bpy.types.Object, name="Scene Object",
        description=tooltips.GENERIC_SEQUENCE_BINDING_TARGET)


class SQEX_UL_generic_sequence_bindings(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_property, _index):
        row = layout.row()
        row.label(text=item.label)
        row.prop(item, "target", text="")


class SQEX_OT_index_generic_unreal_sequence(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_index_generic_unreal_sequence"
    bl_label = "Load / Refresh Sequence List"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            with session.GenericSession(importer._paths(context, self), importer._game_version(context, self)) as mounted:
                index = mounted.request({"action": "generic_asset_index", "assetClass": "LevelSequence", "pathFilter": self.path_filter.strip()})["index"]
            paths = [item["path"] for item in index.get("assets") or []]
            _INDEX[_key(context, self)] = paths
            package_browser.activate(context, _BROWSER, paths, dialog_operator=SQEX_OT_import_generic_unreal_sequence.bl_idname)
            for warning in index.get("warnings") or []:
                print(f"[Unreal sequence WARNING] {warning}")
            report(self, {"WARNING"} if index.get("warnings") else {"INFO"}, f"Found {len(paths):,} LevelSequence assets.")
            return {"FINISHED"}
        except Exception as exc:
            report(self, {"ERROR"}, f"Sequence indexing failed: {exc}")
            return {"CANCELLED"}


SQEX_OT_index_generic_unreal_sequence.__annotations__ = _config_properties()


class SQEX_OT_inspect_generic_sequence_bindings(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_inspect_generic_sequence_bindings"
    bl_label = "Inspect Actor Bindings"
    bl_description = tooltips.GENERIC_SEQUENCE_BINDINGS_DESCRIPTION
    bl_options = {"INTERNAL"}

    virtual_path: bpy.props.StringProperty()

    def execute(self, context):
        try:
            path = _selected_path(context, self)
            with session.GenericSession(importer._paths(context, self), importer._game_version(context, self)) as mounted:
                graph = Graph(lambda path: mounted.request({"action": "generic_sequence", "assetPath": path})["sequence"], path)
            state = context.window_manager
            old = {item.key: item.target for item in state.sqex_generic_sequence_bindings} if state.sqex_generic_sequence_binding_key == _binding_key(context, self, path) else {}
            state.sqex_generic_sequence_bindings.clear()
            for instance, binding_id, binding in graph.bindings():
                item = state.sqex_generic_sequence_bindings.add()
                item.key = instance.binding_key(binding_id)
                item.label = (binding.get("Name") or binding_id) + " — " + asset_path(instance.sequence.path).rsplit("/", 1)[-1]
                item.target = old.get(item.key)
            state.sqex_generic_sequence_binding_key = _binding_key(context, self, path)
            state.sqex_generic_sequence_binding_index = 0
            report(self, {"INFO"}, f"Read {len(state.sqex_generic_sequence_bindings):,} bindings across {len(graph.instances):,} sequence instances. Empty targets use automatic resolution.")
            return {"FINISHED"}
        except Exception as exc:
            report(self, {"ERROR"}, f"Binding inspection failed: {exc}")
            return {"CANCELLED"}


SQEX_OT_inspect_generic_sequence_bindings.__annotations__.update(_config_properties())


class SQEX_OT_import_generic_unreal_sequence(SQEX_LoggedOperator):
    bl_idname = "import_scene.sqex_generic_unreal_sequence"
    bl_label = "Import Generic Unreal Cutscene"
    bl_description = tooltips.GENERIC_SEQUENCE_DESCRIPTION
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(name="Sequence Package", description=tooltips.GENERIC_PACKAGE_PATH)
    start_frame: bpy.props.IntProperty(name="Start Frame", default=1)
    scale_factor: bpy.props.FloatProperty(name="Import Scale", default=0.01, min=0.000001)
    load_missing: bpy.props.BoolProperty(name="Load Missing Bound Actors", default=True,
        description=tooltips.GENERIC_SEQUENCE_LOAD_MISSING)
    import_models: bpy.props.BoolProperty(name="Import Models", default=True)
    import_cameras: bpy.props.BoolProperty(name="Import Cameras and Cuts", default=True)
    import_lights: bpy.props.BoolProperty(name="Import Lights", default=True)
    import_animation: bpy.props.BoolProperty(name="Import Skeletal Animation", default=True)
    replace_existing: bpy.props.BoolProperty(name="Replace Existing Animation", default=False,
        description=tooltips.GENERIC_SEQUENCE_REPLACE_EXISTING)
    set_frame_range: bpy.props.BoolProperty(name="Set Scene Playback Range", default=True)
    binding_overrides: bpy.props.StringProperty(name="Binding Overrides", options={"HIDDEN"},
        description=tooltips.GENERIC_SEQUENCE_BINDING_OVERRIDES)

    def invoke(self, context, _event):
        self.start_frame = context.scene.frame_current
        self._browser_key = _key(context, self)
        package_browser.activate(context, _BROWSER, _INDEX.get(self._browser_key) or [], dialog_operator=self.bl_idname)
        return context.window_manager.invoke_props_dialog(self, width=1050)

    def check(self, context):
        key = _key(context, self)
        if key != getattr(self, "_browser_key", None):
            package_browser.activate(context, _BROWSER, _INDEX.get(key) or [], dialog_operator=self.bl_idname)
            self._browser_key = key
        return True

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "cue4parse_profile")
        layout.label(text="Uses the same game paths, mappings, key and Oodle settings as generic models.", icon="PREFERENCES")
        layout.prop(self, "path_filter")
        refresh = layout.operator(SQEX_OT_index_generic_unreal_sequence.bl_idname, icon="FILE_REFRESH")
        refresh.cue4parse_profile, refresh.path_filter = self.cue4parse_profile, self.path_filter
        package_browser.draw(layout, context, _BROWSER, rows=7)
        layout.prop(self, "virtual_path")
        inspect = layout.operator(SQEX_OT_inspect_generic_sequence_bindings.bl_idname, icon="VIEWZOOM")
        inspect.cue4parse_profile, inspect.path_filter, inspect.virtual_path = self.cue4parse_profile, self.path_filter, self.virtual_path
        state = context.window_manager
        try:
            matching = state.sqex_generic_sequence_binding_key == _binding_key(context, self, _selected_path(context, self))
        except ValueError:
            matching = False
        if matching and len(state.sqex_generic_sequence_bindings):
            layout.template_list(SQEX_UL_generic_sequence_bindings.__name__, "", state, "sqex_generic_sequence_bindings", state,
                                 "sqex_generic_sequence_binding_index", rows=5)
            layout.label(text="Optional scene-object overrides. Empty targets are resolved automatically.")
        row = layout.row()
        row.prop(self, "start_frame")
        row.prop(self, "scale_factor")
        row = layout.row()
        for key in ("import_models", "import_cameras", "import_lights", "import_animation"):
            row.prop(self, key)
        for key in ("load_missing", "replace_existing", "set_frame_range"):
            layout.prop(self, key)
        layout.label(text="Blueprint logic, Wwise and unsupported effects become report entries/markers.", icon="INFO")

    def execute(self, context):
        runner = None
        try:
            path = _selected_path(context, self)
            overrides = json.loads(self.binding_overrides or "{}")
            if not isinstance(overrides, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in overrides.items()):
                raise ValueError("Binding overrides must map binding IDs to scene object names.")
            state = context.window_manager
            if state.sqex_generic_sequence_binding_key == _binding_key(context, self, path):
                overrides.update({item.key: item.target for item in state.sqex_generic_sequence_bindings if item.target})
            with session.GenericSession(importer._paths(context, self), importer._game_version(context, self),
                                        pbr_mapping=importer._pbr_mapping(context, self)) as mounted:
                mounted.profile_id = self.cue4parse_profile
                runner = sequence_import.Importer(context, mounted, path, start_frame=self.start_frame, factor=self.scale_factor,
                    load_missing=self.load_missing, import_models=self.import_models, import_cameras=self.import_cameras,
                    import_lights=self.import_lights, import_animation=self.import_animation, replace_existing=self.replace_existing, overrides=overrides)
                with _active_collection(context, runner.collection):
                    result = runner.run()
            if self.set_frame_range:
                context.scene.frame_start = self.start_frame
                context.scene.frame_end = max(self.start_frame, math.ceil(runner.end_frame)-1)
            context.scene.frame_set(self.start_frame)
            report(self, {"WARNING"} if result["warnings"] else {"INFO"},
                   f"Imported {result['sequenceInstances']:,} sequence instances, {result['objects']:,} objects, {result['animationStrips']:,} animation sections, "
                   f"{result['cameraCuts']:,} camera markers; {len(result['unresolvedBindings']):,} unresolved bindings. "
                   f"Details: {runner.collection['ue_import_report']} in the Text Editor.")
            return {"FINISHED"}
        except Exception as exc:
            if runner is not None:
                runner.rollback()
            report(self, {"ERROR"}, f"Unreal cutscene import failed: {exc}")
            return {"CANCELLED"}


SQEX_OT_import_generic_unreal_sequence.__annotations__.update(_config_properties())
CLASSES = (SQEX_PG_generic_sequence_binding, SQEX_UL_generic_sequence_bindings, SQEX_OT_index_generic_unreal_sequence,
           SQEX_OT_inspect_generic_sequence_bindings, SQEX_OT_import_generic_unreal_sequence)


def register_runtime_properties():
    bpy.types.WindowManager.sqex_generic_sequence_bindings = bpy.props.CollectionProperty(type=SQEX_PG_generic_sequence_binding)
    bpy.types.WindowManager.sqex_generic_sequence_binding_key = bpy.props.StringProperty()
    bpy.types.WindowManager.sqex_generic_sequence_binding_index = bpy.props.IntProperty()


def unregister_runtime_properties():
    for name in ("sqex_generic_sequence_bindings", "sqex_generic_sequence_binding_key", "sqex_generic_sequence_binding_index"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
