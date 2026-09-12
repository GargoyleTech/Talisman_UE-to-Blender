"""Shared folder-oriented multi-select browser for package asset importers."""

from __future__ import annotations

import re
from typing import Any

import bpy

from ..core.blender.reporting import FF7R_LoggedOperator


_ACTIVE_BROWSER: dict[str, Any] | None = None
_NATURAL_TOKEN = re.compile(r"(\d+)")


def _natural_path_key(path: str):
    return tuple(
        int(token) if token.isdigit() else token.casefold()
        for token in _NATURAL_TOKEN.split(path.replace("\\", "/"))
    )


def _entry_selection_changed(entry, _context):
    if _ACTIVE_BROWSER is None or entry.is_directory or not entry.virtual_path:
        return
    if entry.selected:
        _ACTIVE_BROWSER["selected"].add(entry.virtual_path)
    else:
        _ACTIVE_BROWSER["selected"].discard(entry.virtual_path)


def _filter_changed(_state, context):
    if _ACTIVE_BROWSER is not None:
        populate(context, _ACTIVE_BROWSER)


class FF7R_PG_package_asset_entry(bpy.types.PropertyGroup):
    display_name: bpy.props.StringProperty()
    virtual_path: bpy.props.StringProperty()
    is_directory: bpy.props.BoolProperty(default=False)
    selected: bpy.props.BoolProperty(default=False, update=_entry_selection_changed)


class FF7R_PG_package_asset_browser(bpy.types.PropertyGroup):
    entries: bpy.props.CollectionProperty(type=FF7R_PG_package_asset_entry)
    active_index: bpy.props.IntProperty(default=0)
    current_directory: bpy.props.StringProperty(default="")
    filter_text: bpy.props.StringProperty(
        name="Search",
        description="Filter assets by space-separated terms anywhere in their package path",
        options={"TEXTEDIT_UPDATE"},
        update=_filter_changed,
    )


class FF7R_UL_package_assets(bpy.types.UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon,
        _active_data, _active_propname, _index,
    ):
        if item.is_directory:
            operator = layout.operator(
                FF7R_OT_package_asset_folder.bl_idname,
                text=item.display_name,
                icon="FILE_FOLDER",
                emboss=False,
            )
            operator.virtual_path = item.virtual_path
        else:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")
            row.label(
                text=item.display_name,
                icon=(_ACTIVE_BROWSER or {}).get("file_icon", "MESH_DATA"),
            )


class FF7R_OT_package_asset_folder(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_package_asset_folder"
    bl_label = "Open Package Folder"
    bl_options = {"INTERNAL"}
    virtual_path: bpy.props.StringProperty()

    def execute(self, context):
        if _ACTIVE_BROWSER is not None:
            sync_selection(context, _ACTIVE_BROWSER)
            _ACTIVE_BROWSER["directory"] = self.virtual_path.strip("/")
            populate(context, _ACTIVE_BROWSER)
        return {"FINISHED"}


class FF7R_OT_package_asset_up(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_package_asset_up"
    bl_label = "Parent Folder"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if _ACTIVE_BROWSER is not None:
            sync_selection(context, _ACTIVE_BROWSER)
            directory = _ACTIVE_BROWSER["directory"].rstrip("/")
            _ACTIVE_BROWSER["directory"] = (
                directory.rsplit("/", 1)[0] if "/" in directory else ""
            )
            populate(context, _ACTIVE_BROWSER)
        return {"FINISHED"}


class FF7R_OT_package_asset_selection(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_package_asset_selection"
    bl_label = "Change Package Asset Selection"
    bl_options = {"INTERNAL"}
    mode: bpy.props.EnumProperty(items=(
        ("SELECT", "Select Visible", "Select every visible asset"),
        ("CLEAR", "Clear All", "Clear the complete batch selection"),
        ("INVERT", "Invert Visible", "Invert visible asset selections"),
    ))

    def execute(self, context):
        if _ACTIVE_BROWSER is None:
            return {"CANCELLED"}
        state = _ACTIVE_BROWSER
        browser = context.window_manager.ff7r_package_asset_browser
        if self.mode == "CLEAR":
            state["selected"].clear()
        else:
            sync_selection(context, state)
            for entry in browser.entries:
                if entry.is_directory:
                    continue
                if self.mode == "SELECT":
                    state["selected"].add(entry.virtual_path)
                else:
                    state["selected"].symmetric_difference_update(
                        {entry.virtual_path}
                    )
        populate(context, state)
        return {"FINISHED"}


CLASSES = (
    FF7R_PG_package_asset_entry,
    FF7R_PG_package_asset_browser,
    FF7R_UL_package_assets,
    FF7R_OT_package_asset_folder,
    FF7R_OT_package_asset_up,
    FF7R_OT_package_asset_selection,
)


def register_runtime_properties():
    bpy.types.WindowManager.ff7r_package_asset_browser = bpy.props.PointerProperty(
        type=FF7R_PG_package_asset_browser
    )


def unregister_runtime_properties():
    global _ACTIVE_BROWSER
    _ACTIVE_BROWSER = None
    if hasattr(bpy.types.WindowManager, "ff7r_package_asset_browser"):
        del bpy.types.WindowManager.ff7r_package_asset_browser


def make_state(
    asset_label: str,
    *,
    initial_directory: str = "",
    file_icon: str = "MESH_DATA",
) -> dict[str, Any]:
    return {
        "asset_label": asset_label,
        "paths": [],
        "directory": initial_directory.strip("/"),
        "initial_directory": initial_directory.strip("/"),
        "selected": set(),
        "file_icon": file_icon,
    }


def sync_selection(context, state: dict[str, Any]) -> None:
    browser = context.window_manager.ff7r_package_asset_browser
    for entry in browser.entries:
        if entry.is_directory:
            continue
        if entry.selected:
            state["selected"].add(entry.virtual_path)
        else:
            state["selected"].discard(entry.virtual_path)


def populate(context, state: dict[str, Any]) -> None:
    browser = context.window_manager.ff7r_package_asset_browser
    browser.entries.clear()
    terms = tuple(
        term.casefold() for term in browser.filter_text.split() if term.strip()
    )
    if terms:
        rows = [
            (path, path, False)
            for path in state["paths"]
            if all(term in path.casefold() for term in terms)
        ]
    else:
        directory = state["directory"].strip("/")
        prefix = directory + "/" if directory else ""
        folders: dict[str, str] = {}
        files = []
        for path in state["paths"]:
            if not path.casefold().startswith(prefix.casefold()):
                continue
            remainder = path[len(prefix):]
            if "/" in remainder:
                child = remainder.split("/", 1)[0]
                folders.setdefault(child.casefold(), prefix + child)
            else:
                files.append((remainder, path, False))
        rows = [
            (folder.rsplit("/", 1)[-1], folder, True)
            for folder in sorted(folders.values(), key=_natural_path_key)
        ]
        rows.extend(sorted(files, key=lambda row: _natural_path_key(row[0])))
    for display_name, virtual_path, is_directory in rows:
        entry = browser.entries.add()
        entry.display_name = display_name
        entry.virtual_path = virtual_path
        entry.is_directory = is_directory
        entry.selected = virtual_path in state["selected"]
    browser.current_directory = state["directory"]
    browser.active_index = min(
        browser.active_index, max(0, len(browser.entries) - 1)
    )


def activate(context, state: dict[str, Any], paths: list[str]) -> None:
    global _ACTIVE_BROWSER
    state["paths"] = sorted(
        {str(path).replace("\\", "/").lstrip("/") for path in paths},
        key=_natural_path_key,
    )
    directory = state["directory"].strip("/")
    if directory and not any(
        path.casefold().startswith((directory + "/").casefold())
        for path in state["paths"]
    ):
        state["directory"] = state["initial_directory"]
    state["selected"].clear()
    _ACTIVE_BROWSER = state
    browser = context.window_manager.ff7r_package_asset_browser
    browser.filter_text = ""
    browser.current_directory = state["directory"]
    populate(context, state)


def draw(layout, context, state: dict[str, Any], *, rows: int = 12) -> None:
    browser = context.window_manager.ff7r_package_asset_browser
    header = layout.row(align=True)
    header.label(
        text=(
            f"{len(state['paths']):,} {state['asset_label']} available — "
            f"{len(state['selected']):,} selected"
        ),
        icon="PACKAGE",
    )
    header.operator(
        FF7R_OT_package_asset_up.bl_idname, text="", icon="FILE_PARENT"
    )
    header.label(text=state["directory"] or "Package root")
    layout.prop(browser, "filter_text", text="", icon="VIEWZOOM")
    layout.template_list(
        FF7R_UL_package_assets.__name__,
        state["asset_label"],
        browser,
        "entries",
        browser,
        "active_index",
        rows=rows,
    )
    selection = layout.row(align=True)
    selection.operator(
        FF7R_OT_package_asset_selection.bl_idname, text="Select Visible"
    ).mode = "SELECT"
    selection.operator(
        FF7R_OT_package_asset_selection.bl_idname, text="Invert Visible"
    ).mode = "INVERT"
    selection.operator(
        FF7R_OT_package_asset_selection.bl_idname, text="Clear All"
    ).mode = "CLEAR"


def selected_paths(context, state: dict[str, Any]) -> list[str]:
    if _ACTIVE_BROWSER is not state:
        return []
    sync_selection(context, state)
    selected = [path for path in state["paths"] if path in state["selected"]]
    if selected:
        return selected
    browser = context.window_manager.ff7r_package_asset_browser
    if 0 <= browser.active_index < len(browser.entries):
        highlighted = browser.entries[browser.active_index]
        if not highlighted.is_directory:
            return [highlighted.virtual_path]
    return []


def resolve_paths(
    context,
    state: dict[str, Any],
    explicit_path: str = "",
) -> list[str]:
    """Return the dialog selection, or a direct operator path outside the dialog.

    ``virtual_path`` remains useful for scripts and Blender's operator redo panel,
    while an active browser deliberately does not fall back to its stale value.
    """
    if _ACTIVE_BROWSER is state:
        return selected_paths(context, state)
    explicit_path = explicit_path.strip().replace("\\", "/").lstrip("/")
    return [explicit_path] if explicit_path in state["paths"] else []
