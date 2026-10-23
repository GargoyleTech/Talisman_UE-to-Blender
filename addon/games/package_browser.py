"""Shared folder-oriented multi-select browser for package asset importers."""

from __future__ import annotations

from ..language import strings

import re
from typing import Any

import bpy

from ..core.blender.reporting import SQEX_LoggedOperator


_ACTIVE_BROWSER: dict[str, Any] | None = None
_NATURAL_TOKEN = re.compile(r"(\d+)")
_SHORTCUT_KEYMAP_ITEMS: list[tuple[Any, Any]] = []
_DIALOG_SESSION: dict[str, Any] | None = None


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


class SQEX_PG_package_asset_entry(bpy.types.PropertyGroup):
    display_name: bpy.props.StringProperty()
    virtual_path: bpy.props.StringProperty()
    is_directory: bpy.props.BoolProperty(default=False)
    selected: bpy.props.BoolProperty(default=False, update=_entry_selection_changed)


class SQEX_PG_package_asset_browser(bpy.types.PropertyGroup):
    entries: bpy.props.CollectionProperty(type=SQEX_PG_package_asset_entry)
    active_index: bpy.props.IntProperty(default=0)
    current_directory: bpy.props.StringProperty(default="")
    filter_text: bpy.props.StringProperty(
        name="Search",
        description=strings.SHARED_PACKAGE_ASSET_BROWSER_FILTER_TEXT,
        options={"TEXTEDIT_UPDATE"},
        update=_filter_changed,
    )


class SQEX_UL_package_assets(bpy.types.UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon,
        _active_data, _active_propname, _index,
    ):
        if item.is_directory:
            operator = layout.operator(
                SQEX_OT_package_asset_folder.bl_idname,
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


class SQEX_OT_package_asset_folder(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_package_asset_folder"
    bl_label = "Open Package Folder"
    bl_options = {"INTERNAL"}
    virtual_path: bpy.props.StringProperty()

    def execute(self, context):
        if _ACTIVE_BROWSER is not None:
            sync_selection(context, _ACTIVE_BROWSER)
            _ACTIVE_BROWSER["directory"] = self.virtual_path.strip("/")
            populate(context, _ACTIVE_BROWSER)
        return {"FINISHED"}


class SQEX_OT_package_asset_up(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_package_asset_up"
    bl_label = "Parent Folder"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if _ACTIVE_BROWSER is not None:
            sync_selection(context, _ACTIVE_BROWSER)
            directory = _ACTIVE_BROWSER["directory"].rstrip("/")
            parent = directory.rsplit("/", 1)[0] if "/" in directory else ""
            root_directory = _ACTIVE_BROWSER.get("root_directory", "")
            if root_directory and not (
                parent.casefold() == root_directory.casefold()
                or parent.casefold().startswith(root_directory.casefold() + "/")
            ):
                parent = root_directory
            _ACTIVE_BROWSER["directory"] = parent
            populate(context, _ACTIVE_BROWSER)
        return {"FINISHED"}


class SQEX_OT_package_asset_selection(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_package_asset_selection"
    bl_label = "Change Package Asset Selection"
    bl_options = {"INTERNAL"}
    mode: bpy.props.EnumProperty(items=(
        ("SELECT", "Select Visible", strings.SHARED_PACKAGE_ASSET_SELECTION_MODE_SELECT),
        ("CLEAR", "Clear All", strings.SHARED_PACKAGE_ASSET_SELECTION_MODE_CLEAR),
        ("INVERT", "Invert Visible", strings.SHARED_PACKAGE_ASSET_SELECTION_MODE_INVERT),
    ))

    def execute(self, context):
        if _ACTIVE_BROWSER is None:
            return {"CANCELLED"}
        state = _ACTIVE_BROWSER
        browser = context.window_manager.sqex_package_asset_browser
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


def _package_browser_dialog_is_open(context) -> bool:
    if _ACTIVE_BROWSER is None:
        return False
    owner_idname = _ACTIVE_BROWSER.get("dialog_operator")
    if _DIALOG_SESSION is not None:
        return (
            _DIALOG_SESSION["owner"] == owner_idname
            and _DIALOG_SESSION["window"] == context.window
        )
    return bool(owner_idname) and any(
        getattr(operator, "bl_idname", None) == owner_idname
        for operator in context.window_manager.operators
    )


def invoke_dialog(operator, context, *, width):
    """Listen ahead of the popup handler, which consumes window keymaps."""
    global _DIALOG_SESSION
    if bpy.app.background:
        return context.window_manager.invoke_props_dialog(operator, width=width)
    _DIALOG_SESSION = {
        "owner": operator.bl_idname,
        "window": context.window,
        "region": None,
        "select_all_events": _file_select_all_events(context),
    }
    try:
        result = context.window_manager.invoke_props_dialog(operator, width=width)
        if result == {"RUNNING_MODAL"}:
            # The last modal handler added runs first. Adding this before the
            # popup would leave Space trapped in Blender's popup handler.
            bpy.ops.wm.sqex_package_asset_dialog_shortcuts('INVOKE_DEFAULT')
        else:
            close_dialog(operator)
        return result
    except Exception:
        close_dialog(operator)
        raise


def close_dialog(operator) -> None:
    global _DIALOG_SESSION
    if _DIALOG_SESSION is not None and _DIALOG_SESSION["owner"] == operator.bl_idname:
        _DIALOG_SESSION = None


def _list_has_keyboard_focus(context, region) -> bool:
    # Query Blender's active UI property rather than estimating row positions.
    # While editing Search (even after moving the mouse onto a row), this is
    # still filter_text, so spaces and select-all remain text-editing events.
    with context.temp_override(region=region):
        active_property = getattr(context, "property", None)
    if not active_property:
        return False
    data, path, _index = active_property
    return data == context.window_manager and (
        path == "sqex_package_asset_browser.active_index"
        or (path.startswith("sqex_package_asset_browser.entries[") and path.endswith(".selected"))
    )


def _shortcut_is_available(context) -> bool:
    return _package_browser_dialog_is_open(context) and (
        _DIALOG_SESSION is None or context.region == _DIALOG_SESSION["region"]
    )


def _matches_shortcut(event, binding, held_keys=()) -> bool:
    event_type, value, any_modifier, shift, ctrl, alt, oskey, key_modifier, repeat = binding
    return (
        event.type == event_type and event.value == value
        and (repeat or not event.is_repeat)
        and (any_modifier or (event.shift, event.ctrl, event.alt, event.oskey) == (shift, ctrl, alt, oskey))
        and (key_modifier == "NONE" or key_modifier in held_keys)
    )


class SQEX_OT_package_asset_dialog_shortcuts(bpy.types.Operator):
    bl_idname = "wm.sqex_package_asset_dialog_shortcuts"
    bl_label = "Package Asset Dialog Shortcuts"
    bl_options = {"INTERNAL"}

    def invoke(self, context, _event):
        if not _package_browser_dialog_is_open(context):
            return {"CANCELLED"}
        self._session = _DIALOG_SESSION
        self._held_keys = set()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if _DIALOG_SESSION is not self._session:
            return {"FINISHED", "PASS_THROUGH"}
        if event.value == 'PRESS':
            self._held_keys.add(event.type)
        elif event.value == 'RELEASE':
            self._held_keys.discard(event.type)
        region = self._session["region"]
        if region is None or not _list_has_keyboard_focus(context, region):
            return {"PASS_THROUGH"}
        space = ("SPACE", "PRESS", False, False, False, False, False, "NONE", False)
        with context.temp_override(region=region):
            if _matches_shortcut(event, space, self._held_keys):
                bpy.ops.wm.sqex_package_asset_toggle_highlighted()
            elif any(_matches_shortcut(event, binding, self._held_keys) for binding in self._session["select_all_events"]):
                bpy.ops.wm.sqex_package_asset_select_all_visible()
            else:
                return {"PASS_THROUGH"}
        region.tag_redraw()
        return {"RUNNING_MODAL"}


class SQEX_OT_package_asset_select_all_visible(SQEX_LoggedOperator):
    """Apply the File Browser Select All shortcut to the visible checklist."""

    bl_idname = "wm.sqex_package_asset_select_all_visible"
    bl_label = "Select All Visible Package Assets"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _shortcut_is_available(context)

    def execute(self, context):
        state = _ACTIVE_BROWSER
        if state is None:
            return {"CANCELLED"}
        sync_selection(context, state)
        browser = context.window_manager.sqex_package_asset_browser
        state["selected"].update(
            entry.virtual_path
            for entry in browser.entries
            if not entry.is_directory and entry.virtual_path
        )
        populate(context, state)
        return {"FINISHED"}


class SQEX_OT_package_asset_toggle_highlighted(SQEX_LoggedOperator):
    """Toggle the checkbox for the highlighted package asset."""

    bl_idname = "wm.sqex_package_asset_toggle_highlighted"
    bl_label = "Toggle Highlighted Package Asset"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _shortcut_is_available(context)

    def execute(self, context):
        if _ACTIVE_BROWSER is None:
            return {"CANCELLED"}
        browser = context.window_manager.sqex_package_asset_browser
        index = browser.active_index
        if not 0 <= index < len(browser.entries):
            return {"CANCELLED"}
        entry = browser.entries[index]
        if entry.is_directory:
            return {"CANCELLED"}
        entry.selected = not entry.selected
        return {"FINISHED"}


CLASSES = (
    SQEX_PG_package_asset_entry,
    SQEX_PG_package_asset_browser,
    SQEX_UL_package_assets,
    SQEX_OT_package_asset_folder,
    SQEX_OT_package_asset_up,
    SQEX_OT_package_asset_selection,
    SQEX_OT_package_asset_dialog_shortcuts,
    SQEX_OT_package_asset_select_all_visible,
    SQEX_OT_package_asset_toggle_highlighted,
)


def register_runtime_properties():
    bpy.types.WindowManager.sqex_package_asset_browser = bpy.props.PointerProperty(
        type=SQEX_PG_package_asset_browser
    )


def unregister_runtime_properties():
    global _ACTIVE_BROWSER, _DIALOG_SESSION
    _ACTIVE_BROWSER = None
    _DIALOG_SESSION = None
    if hasattr(bpy.types.WindowManager, "sqex_package_asset_browser"):
        del bpy.types.WindowManager.sqex_package_asset_browser


def _file_select_all_events(context) -> list[tuple[Any, ...]]:
    """Copy the active File Browser's select-all bindings into our dialog."""
    def events_from(keyconfig) -> list[tuple[Any, ...]]:
        events = []
        if keyconfig is None:
            return events
        for keymap in keyconfig.keymaps:
            if keymap.space_type != 'FILE_BROWSER':
                continue
            for item in keymap.keymap_items:
                if item.idname != "file.select_all" or not item.active:
                    continue
                action = getattr(item.properties, "action", "TOGGLE")
                if action not in {"SELECT", "TOGGLE"}:
                    continue
                event = (
                    item.type,
                    item.value,
                    item.any,
                    item.shift,
                    item.ctrl,
                    item.alt,
                    item.oskey,
                    item.key_modifier,
                    item.repeat,
                )
                if event not in events:
                    events.append(event)
        return events

    # User keymaps contain overrides separately from the active preset. Prefer
    # them outright, so a rebinding replaces the preset key instead of adding a
    # second Select All shortcut to these dialogs.
    keyconfigs = context.window_manager.keyconfigs
    events = events_from(keyconfigs.user) or events_from(keyconfigs.active)
    # A File Browser keymap is not created in Blender's background mode. Keep
    # the conventional shortcut available there and in unusual keyconfigs.
    return events or [("A", "PRESS", False, False, False, False, False, "NONE", False)]


def unregister_shortcuts() -> None:
    while _SHORTCUT_KEYMAP_ITEMS:
        keymap, item = _SHORTCUT_KEYMAP_ITEMS.pop()
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError, ValueError):
            pass


def register_shortcuts(context=None) -> None:
    """Register package-browser shortcuts while a shared package dialog is open."""
    unregister_shortcuts()
    context = context or bpy.context
    keyconfig = context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name="Window", space_type='EMPTY', region_type='WINDOW')
    for event in _file_select_all_events(context):
        (
            event_type, value, any_modifier, shift, ctrl, alt, oskey,
            key_modifier, repeat,
        ) = event
        item = keymap.keymap_items.new(
            SQEX_OT_package_asset_select_all_visible.bl_idname,
            event_type,
            value,
            any=any_modifier,
            shift=shift,
            ctrl=ctrl,
            alt=alt,
            oskey=oskey,
            key_modifier=key_modifier,
            head=True,
        )
        item.repeat = repeat
        _SHORTCUT_KEYMAP_ITEMS.append((keymap, item))
    item = keymap.keymap_items.new(
        SQEX_OT_package_asset_toggle_highlighted.bl_idname,
        "SPACE",
        "PRESS",
        head=True,
    )
    item.repeat = False
    _SHORTCUT_KEYMAP_ITEMS.append((keymap, item))


def make_state(
    asset_label: str,
    *,
    initial_directory: str = "",
    root_directory: str = "",
    file_icon: str = "MESH_DATA",
) -> dict[str, Any]:
    root_directory = root_directory.strip("/")
    initial_directory = initial_directory.strip("/")
    if root_directory and not (
        initial_directory.casefold() == root_directory.casefold()
        or initial_directory.casefold().startswith(root_directory.casefold() + "/")
    ):
        raise ValueError("initial_directory must be inside root_directory")
    return {
        "asset_label": asset_label,
        "paths": [],
        "directory": initial_directory,
        "initial_directory": initial_directory,
        "root_directory": root_directory,
        "selected": set(),
        "dialog_operator": "",
        "file_icon": file_icon,
    }


def sync_selection(context, state: dict[str, Any]) -> None:
    browser = context.window_manager.sqex_package_asset_browser
    for entry in browser.entries:
        if entry.is_directory:
            continue
        if entry.selected:
            state["selected"].add(entry.virtual_path)
        else:
            state["selected"].discard(entry.virtual_path)


def populate(context, state: dict[str, Any]) -> None:
    browser = context.window_manager.sqex_package_asset_browser
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


def activate(
        context,
        state: dict[str, Any],
        paths: list[str],
        *,
        dialog_operator: str = "",
) -> None:
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
    state["dialog_operator"] = dialog_operator
    _ACTIVE_BROWSER = state
    register_shortcuts(context)
    browser = context.window_manager.sqex_package_asset_browser
    browser.filter_text = ""
    browser.current_directory = state["directory"]
    populate(context, state)


def draw(layout, context, state: dict[str, Any], *, rows: int = 12) -> None:
    if _DIALOG_SESSION is not None and _DIALOG_SESSION["owner"] == state.get("dialog_operator"):
        _DIALOG_SESSION["region"] = getattr(context, "region_popup", None) or context.region
    browser = context.window_manager.sqex_package_asset_browser
    header = layout.row(align=True)
    header.label(
        text=(
            f"{len(state['paths']):,} {state['asset_label']} available — "
            f"{len(state['selected']):,} selected"
        ),
        icon="PACKAGE",
    )
    header.operator(
        SQEX_OT_package_asset_up.bl_idname, text="", icon="FILE_PARENT"
    )
    header.label(text=state["directory"] or "Package root")
    layout.prop(browser, "filter_text", text="", icon="VIEWZOOM")
    layout.template_list(
        SQEX_UL_package_assets.__name__,
        state["asset_label"],
        browser,
        "entries",
        browser,
        "active_index",
        rows=rows,
    )
    selection = layout.row(align=True)
    selection.operator(
        SQEX_OT_package_asset_selection.bl_idname, text="Select Visible"
    ).mode = "SELECT"
    selection.operator(
        SQEX_OT_package_asset_selection.bl_idname, text="Invert Visible"
    ).mode = "INVERT"
    selection.operator(
        SQEX_OT_package_asset_selection.bl_idname, text="Clear All"
    ).mode = "CLEAR"


def selected_paths(context, state: dict[str, Any]) -> list[str]:
    if _ACTIVE_BROWSER is not state:
        return []
    sync_selection(context, state)
    selected = [path for path in state["paths"] if path in state["selected"]]
    if selected:
        return selected
    browser = context.window_manager.sqex_package_asset_browser
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
