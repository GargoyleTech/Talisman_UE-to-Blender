"""Universal StaticMesh/SkeletalMesh operator definitions and dialog lifecycle.

Game modules supply source configuration, defaults, capabilities and import
backends. RNA options, persistence and presentation are defined once here.
"""

from dataclasses import dataclass, field
from typing import Callable

import bpy

from ...core.blender.reporting import SQEX_LoggedOperator, report
from ...games import package_browser
from ...language import tooltips
from ...ui.mesh_importer import (
    CORE_SKELETAL_OPTIONS, GAME_SKELETAL_OPTIONS,
    SKELETAL_OPTION_LABELS, SKELETAL_OPTION_DESCRIPTIONS, draw_package_mesh_options,
)
from . import options


MESH_DIALOG_WIDTH = 1000
MESH_BROWSER_ROWS = 12
MESH_OPTION_NAMES = ("scale_factor", "face_y_forward", "offset_opposite_faces")
SKELETAL_OPTION_NAMES = ("build_skeleton", "bind_active_armature", *CORE_SKELETAL_OPTIONS)


def mesh_properties(mesh_kind, *, game_options=(), defaults=None):
    defaults = defaults or {}
    properties = {
        "virtual_path": bpy.props.StringProperty(name="Asset Path", options={"HIDDEN"}),
        "scale_factor": bpy.props.FloatProperty(
            name="Scale", description=tooltips.SHARED_SCALE_FACTOR,
            default=defaults.get("scale_factor", 0.01), min=0.000001, max=100.0),
        "face_y_forward": bpy.props.EnumProperty(
            name="Face Forward", description=tooltips.SHARED_FACE_Y_FORWARD,
            items=options.FACE_FORWARD_ITEMS,
            default=defaults.get("face_y_forward", options.FACE_FORWARD_UNREAL)),
        "offset_opposite_faces": bpy.props.EnumProperty(
            name="Offset Faces", description=tooltips.SHARED_OFFSET_OPPOSITE_FACES,
            items=options.OFFSET_FACES_ITEMS,
            default=defaults.get("offset_opposite_faces", options.OFFSET_FACES_NONE)),
    }
    if mesh_kind == "STATIC":
        return properties
    if mesh_kind != "SKELETAL":
        raise ValueError(f"Unknown mesh kind: {mesh_kind!r}")
    properties.update({
        "build_skeleton": bpy.props.BoolProperty(
            name="Build Skeleton from Package", default=defaults.get("build_skeleton", True),
            description=tooltips.SHARED_SKELETAL_BUILD_SKELETON),
        "bind_active_armature": bpy.props.BoolProperty(
            name="Bind Active Armature", default=defaults.get("bind_active_armature", True),
            description=tooltips.SHARED_SKELETAL_BIND_ACTIVE_ARMATURE),
        "attachment_sockets": bpy.props.EnumProperty(
            name=SKELETAL_OPTION_LABELS["attachment_sockets"],
            description=SKELETAL_OPTION_DESCRIPTIONS["attachment_sockets"],
            items=options.ATTACHMENT_SOCKETS_ITEMS,
            default=defaults.get("attachment_sockets", options.ATTACHMENT_SOCKETS_EMPTIES)),
    })
    for name in (*CORE_SKELETAL_OPTIONS, *GAME_SKELETAL_OPTIONS):
        if name == "attachment_sockets":
            continue
        available = name in CORE_SKELETAL_OPTIONS or name in game_options
        properties[name] = bpy.props.BoolProperty(
            name=SKELETAL_OPTION_LABELS[name], description=SKELETAL_OPTION_DESCRIPTIONS[name],
            default=defaults.get(name, name in {"import_kdi", "create_variant_bone_collections"}) if available else False,
            # Retain unsupported legacy keyword arguments for scripts, without
            # drawing or remembering inapplicable controls.
            options=set() if available else {"HIDDEN", "SKIP_SAVE"},
        )
    return properties


@dataclass
class MeshBrowserState:
    browser: dict
    paths: list
    key: object = None
    ready: bool = True
    source: str = "mounted packages"
    messages: tuple = ()


@dataclass
class PackageMeshSource:
    game_label: str
    browser_state: Callable
    execute: Callable
    defaults: Callable | None = None
    configure: Callable | None = None
    game_options: frozenset = frozenset()
    property_defaults: dict = field(default_factory=dict)
    material_summary: str = ""


class PackageMeshOperator:
    def invoke(self, context, _event):
        source = self._mesh_source
        try:
            if source.defaults is not None:
                source.defaults(self, context)
            self._load_last_import_settings(context)
            state = source.browser_state(self, context, refresh=True)
            if state.ready and not state.paths:
                raise ValueError(f"No {source.game_label} {self.mesh_kind.title()}Mesh assets were found.")
            package_browser.activate(context, state.browser, state.paths, dialog_operator=self.bl_idname)
            self._mesh_browser_key = state.key
        except Exception as exc:
            report(self, {"ERROR"}, f"{source.game_label} mesh index failed: {exc}")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=MESH_DIALOG_WIDTH)

    def check(self, context):
        state = self._mesh_source.browser_state(self, context)
        if getattr(self, "_mesh_browser_key", None) != state.key:
            package_browser.activate(context, state.browser, state.paths, dialog_operator=self.bl_idname)
            self._mesh_browser_key = state.key
        return True

    def draw(self, context):
        layout = self.layout
        source = self._mesh_source
        if source.configure is not None:
            source.configure(self, context, layout)
        state = source.browser_state(self, context)
        browser = layout.column()
        browser.enabled = state.ready
        package_browser.draw(browser, context, state.browser, rows=MESH_BROWSER_ROWS)
        if state.ready:
            layout.label(text=f"{len(state.paths):,} {source.game_label} {self.mesh_kind.title()}Mesh assets indexed ({state.source})", icon="PACKAGE")
        else:
            layout.label(text="Load the asset list after choosing or changing mount settings.", icon="INFO")
        for text, icon in state.messages:
            layout.label(text=text, icon=icon)
        draw_package_mesh_options(layout, self, mesh_kind=self.mesh_kind,
                                  game_label=source.game_label, game_options=source.game_options)
        if source.material_summary:
            layout.label(text=source.material_summary)

    def cancel(self, context):
        self._save_last_import_settings(context)

    def execute(self, context):
        try:
            result = self._mesh_source.execute(self, context)
        except Exception as exc:
            report(self, {"ERROR"}, f"{self._mesh_source.game_label} mesh import failed: {exc}")
            return {"CANCELLED"}
        if result == {"FINISHED"}:
            self._save_last_import_settings(context)
        return result


def make_package_mesh_importer(*, class_name, bl_idname, module_name, mesh_kind, source,
                               configuration_properties=None, persisted_configuration=(),
                               default_virtual_path="", description=None):
    properties = mesh_properties(mesh_kind, game_options=source.game_options, defaults=source.property_defaults)
    properties["virtual_path"] = bpy.props.StringProperty(
        name="Asset Path", default=default_virtual_path, options={"HIDDEN"})
    persisted = (*MESH_OPTION_NAMES, *persisted_configuration)
    if mesh_kind == "SKELETAL":
        persisted += (*SKELETAL_OPTION_NAMES, *(name for name in GAME_SKELETAL_OPTIONS if name in source.game_options))
    if configuration_properties is not None:
        if set(configuration_properties) & set(properties):
            raise ValueError("Source configuration must not override shared mesh options")
        properties.update(configuration_properties)
    label = "StaticMesh" if mesh_kind == "STATIC" else "SkeletalMesh"
    return type(class_name, (PackageMeshOperator, SQEX_LoggedOperator), {
        "__module__": module_name, "__annotations__": properties,
        "bl_idname": bl_idname, "bl_label": f"{label} from {source.game_label} Packages",
        "bl_description": description or f"Import {source.game_label} {label} assets",
        "bl_options": {"REGISTER", "UNDO"}, "mesh_kind": mesh_kind,
        "_persisted_props": persisted, "_mesh_source": source,
    })
