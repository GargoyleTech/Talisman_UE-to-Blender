"""Independent shader texture browsers and asynchronous bridge job scheduling."""

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import time
import textwrap

import bpy
import bpy.utils.previews
from bpy.app.handlers import persistent

from ..core.package_utils import addon_package_name
from ..core.profiles import GamePaths, normalize_optional_input
from ..core.blender.material_nodes import load_packed_image, set_channel_packed_alpha
from ..formats.unreal_mesh.session import make_profile
from ..formats.unreal_package.texture_browser import TextureBrowserSession, configuration_signature
from ..games import SUPPORTED_PROFILES
from ..language import strings


NODE_TYPE = "SQEX_ShaderNodeUnrealTexture"
NONE = "NONE"
_STATES = {}
_ENUM_ITEMS = {}
_MENUS = []


def preferences(context=None):
    addon = (context or bpy.context).preferences.addons.get(addon_package_name(__package__))
    return addon.preferences if addon else None


def game_choices(context=None):
    items = [("title:" + profile.key, profile.label) for profile in SUPPORTED_PROFILES]
    prefs = preferences(context)
    if prefs:
        items.extend(("custom:" + profile.profile_id, profile.name or "Unnamed Profile")
                     for profile in prefs.generic_unreal_profiles if profile.profile_id)
    return [(NONE, " ")] + sorted(items, key=lambda item: (item[1].casefold(), item[0]))


def _number(key):
    return 0 if key == NONE else (int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) & 0x7fffffff) or 1


def game_items(_node, context):
    # Retain all enum strings across redraws/profile edits (Blender's RNA keeps references).
    choices = tuple(game_choices(context))
    if choices not in _ENUM_ITEMS:
        _ENUM_ITEMS[choices] = [(key, label, strings.TEXTURE_BROWSER_NONE if key == NONE else label,
                               _number(key)) for key, label in choices]
    return _ENUM_ITEMS[choices]


def game_get(node):
    key = node.game_key
    return _number(key) if any(choice == key for choice, _label in game_choices()) else 0


def game_set(node, number):
    current = _STATES.get(node.browser_id)
    if current and current.batch is not None:
        return
    node.game_key = next((key for key, _label in game_choices() if _number(key) == number), NONE)


def configuration(key, context=None):
    prefs = preferences(context)
    if prefs is None:
        raise ValueError("The add-on preferences are unavailable.")
    if key.startswith("title:"):
        profile = next((profile for profile in SUPPORTED_PROFILES if "title:" + profile.key == key), None)
        if profile is None:
            raise ValueError("This game profile no longer exists.")
        paths = profile.paths_from_preferences(prefs, bpy.path.abspath)
    else:
        custom = next((profile for profile in prefs.generic_unreal_profiles if "custom:" + profile.profile_id == key), None)
        if custom is None:
            raise ValueError("This custom game profile no longer exists.")
        profile = make_profile(custom.game_version)
        paths = GamePaths(bpy.path.abspath(custom.game_path) if custom.game_path else "",
                          bpy.path.abspath(prefs.oodle_dll) if prefs.oodle_dll else "",
                          bpy.path.abspath(normalize_optional_input(custom.usmap_path)) if normalize_optional_input(custom.usmap_path) else "",
                          custom.aes_key)
    if not paths.install_root or not Path(paths.install_root).is_dir():
        raise ValueError("Configure this game's package folder in the add-on preferences.")
    for label, path in (("Oodle library", paths.oodle_dll), ("Mappings file", paths.usmap_path)):
        if path and not Path(path).is_file():
            raise ValueError(f"The configured {label.lower()} does not exist. Check the add-on preferences.")
    return profile, paths


def cache_root():
    root = bpy.utils.user_resource("CONFIG")
    return str(Path(root) / "talisman") if root else ""


@dataclass
class BrowserState:
    node: object
    game_key: str = ""
    session: object = None
    signature: str = ""
    indexed: bool = False
    indexing: bool = False
    count: int = 0
    total: int = 0
    message: str = ""
    error: bool = False
    selected: dict = field(default_factory=dict)
    browse_revision: int = 0
    displayed_revision: int = -1
    browse_due: float = 0
    preview_key: str = ""
    preview_due: float = 0
    preview_icon: int = 0
    preview_message: str = "Select a texture to preview"
    previews: object = None
    preview_cache: OrderedDict = field(default_factory=OrderedDict)
    touched: float = 0
    populating: bool = False
    force: bool = False
    batch: object = None
    batch_response: object = None

    def close(self):
        if self.previews is not None:
            bpy.utils.previews.remove(self.previews)
            self.previews = None
        self.preview_cache.clear()
        self.preview_icon = 0
        self.preview_due = time.monotonic() + 0.2
        self.preview_message = "Loading preview…" if self.preview_key else "Select a texture to preview"
        if self.session is not None:
            self.session.close()
            self.session = None


def state(node):
    key = node.browser_id
    current = _STATES.get(key)
    if current is None or current.node != node:
        current = _STATES[key] = BrowserState(node)
    return current


def find_node(node_id):
    current = _STATES.get(node_id)
    if current is not None:
        try:
            node = current.node
            if node.id_data.nodes.get(node.name) == node:
                return node
        except ReferenceError:
            pass
    return None


def schedule():
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.05)


def touch(node):
    current = state(node)
    current.touched = time.monotonic()
    schedule()
    return current


def game_changed(node, _context):
    current = _STATES.pop(node.browser_id, None)
    if current:
        current.close()
    node.browser_entries.clear()
    node.active_index = -1
    node.directory = ""
    node.search = ""
    node.browser_page = 0
    node.image = None
    node.browser_message = ""
    prefs = preferences()
    if node.game_key == NONE and prefs:
        prefs.texture_browser_last_game = NONE
    if node.game_key != NONE:
        node.browser_open = True
        touch(node)


def browse_changed(node, _context):
    current = state(node)
    if current.populating:
        return
    current.browse_revision += 1
    current.browse_due = time.monotonic() + 0.15
    current.preview_key = ""
    current.preview_icon = 0
    current.preview_message = "Select a texture to preview"
    schedule()


def search_changed(node, context):
    node.browser_page = 0
    browse_changed(node, context)


def selected_changed(entry, _context):
    current = _STATES.get(entry.owner_id)
    if current and not current.populating and not entry.is_directory:
        if entry.selected:
            current.selected[entry.object_path] = entry_data(entry)
        else:
            current.selected.pop(entry.object_path, None)


def entry_data(entry):
    return {"path": entry.virtual_path, "objectPath": entry.object_path,
            "name": entry.display_name, "textureType": entry.texture_type}


def highlight_changed(node, _context):
    current = state(node)
    if current.populating:
        return
    current.preview_key = ""
    current.preview_icon = 0
    current.preview_message = "Select a texture to preview"
    if 0 <= node.active_index < len(node.browser_entries):
        entry = node.browser_entries[node.active_index]
        if not entry.is_directory:
            current.preview_key = entry.object_path
            current.preview_due = time.monotonic() + 0.2
            current.preview_message = "Loading preview…"
            if entry.object_path in current.preview_cache:
                current.preview_icon = current.preview_cache[entry.object_path][0]
                current.preview_cache.move_to_end(entry.object_path)
                current.preview_message = ""
    schedule()


def selected_entries(node):
    current = state(node)
    if current.selected:
        return list(current.selected.values())
    if 0 <= node.active_index < len(node.browser_entries):
        entry = node.browser_entries[node.active_index]
        if not entry.is_directory:
            return [entry_data(entry)]
    return []


def _populate(current, payload):
    node = current.node
    highlighted = (node.browser_entries[node.active_index].object_path
                   if 0 <= node.active_index < len(node.browser_entries) else "")
    current.populating = True
    try:
        node.browser_entries.clear()
        for item in payload["rows"]:
            entry = node.browser_entries.add()
            entry.owner_id = node.browser_id
            entry.display_name = item["name"]
            entry.virtual_path = item["path"]
            entry.object_path = item["objectPath"]
            entry.texture_type = item["textureType"]
            entry.is_directory = item["isDirectory"]
            entry.selected = entry.object_path in current.selected
        node.browser_page = payload["page"]
        node.active_index = next((index for index, entry in enumerate(node.browser_entries)
                                  if highlighted and entry.object_path == highlighted), -1)
        current.total = payload["total"]
    finally:
        current.populating = False


def _preview_result(current, key, payload):
    if payload.get("status") == "unavailable":
        if key == current.preview_key:
            current.preview_message = payload.get("reason", "No stored image pixels")
        return
    if key != current.preview_key:
        current.session.remove_image(payload)
        return
    if current.previews is None:
        current.previews = bpy.utils.previews.new()
    icon = current.previews.load(key, payload["output"], "IMAGE", force_reload=True)
    current.preview_cache[key] = (icon.icon_id, payload)
    current.preview_cache.move_to_end(key)
    while len(current.preview_cache) > 32:
        old_key, (_icon, old_payload) = current.preview_cache.popitem(last=False)
        del current.previews[old_key]
        current.session.remove_image(old_payload)
    current.preview_icon = icon.icon_id
    current.preview_message = ""


def _advance(current):
    node = current.node
    now = time.monotonic()
    if current.game_key != node.game_key:
        current.close()
        current.game_key = node.game_key
        current.indexed = False
        current.error = False
        current.selected.clear()
    if node.game_key == NONE:
        return
    # A renamed/deleted profile must never select the next dropdown row.
    if not any(key == node.game_key for key, _label in game_choices()):
        node.game_key = NONE
        node.image = None
        node.browser_entries.clear()
        node.browser_message = "The game profile was removed. Choose another game."
        current.close()
        return
    if current.session is None:
        if current.error or now - current.touched > 2:
            return
        try:
            profile, paths = configuration(node.game_key)
        except ValueError as exc:
            node.game_key = NONE
            node.image = None
            node.browser_entries.clear()
            node.browser_message = str(exc)
            return
        current.session = TextureBrowserSession(profile, paths, cache_root())
        current.signature = configuration_signature(profile, paths)
        current.indexed = False
        current.message = "Mounting game packages…"
        prefs = preferences()
        if prefs:
            prefs.texture_browser_last_game = node.game_key
    session = current.session
    completed = session.poll()
    if completed:
        tag, response = completed
        kind = tag[0]
        payload = response.get("payload") or {}
        if kind == "texture":
            current.batch_response = response
        elif not response.get("ok"):
            if kind == "preview":
                if tag[1] == current.preview_key:
                    current.preview_message = response.get("error", "Preview unavailable")
            else:
                raise RuntimeError(response.get("error", "The texture browser request failed."))
        elif kind in {"index", "index_step"}:
            current.indexed = True
            current.indexing = not payload.get("complete", True)
            if current.count != payload["count"] or kind == "index":
                current.browse_revision += 1
            current.count = payload["count"]
            skipped = payload.get("failures", 0)
            current.message = (f"{current.count:,} textures · indexing {payload.get('scanned', 0):,} / {payload.get('total', 0):,}…"
                               if current.indexing else f"{current.count:,} textures")
            if skipped:
                current.message += f" · {skipped:,} unreadable packages"
        elif kind == "browse":
            if tag[1] == current.browse_revision:
                _populate(current, payload)
                current.displayed_revision = tag[1]
        elif kind == "preview":
            _preview_result(current, tag[1], payload)
    if session.pending:
        return
    if not session.ready:
        return
    if not current.indexed:
        session.send(("index",), action="index", signature=session.signature,
                     cachePath=session.cache_path, force=current.force)
        current.force = False
        current.message = "Indexing textures…"
    elif current.batch is not None:
        # The modal import operator owns extraction, datablocks, and undo.
        return
    elif current.displayed_revision != current.browse_revision and now >= current.browse_due:
        session.send(("browse", current.browse_revision), action="browse", directory=node.directory,
                     search=node.search, page=node.browser_page)
    elif (current.preview_key and node.show_preview and now >= current.preview_due
          and current.preview_key not in current.preview_cache and current.preview_message == "Loading preview…"):
        key = current.preview_key
        entry = next((entry for entry in node.browser_entries if entry.object_path == key), None)
        if entry:
            session.send(("preview", key), action="preview", assetPath=entry.virtual_path, objectPath=key)
            current.preview_due = float("inf")
    elif current.indexing:
        session.send(("index_step",), action="index_step")
    if now - current.touched > 120 and current.batch is None:
        current.close()


def tick():
    changed = False
    for node_id, current in list(_STATES.items()):
        try:
            if find_node(node_id) is None:
                current.close()
                _STATES.pop(node_id, None)
                continue
            before = (current.message, current.preview_icon, len(current.node.browser_entries),
                      current.displayed_revision, current.preview_message)
            _advance(current)
            changed |= before != (current.message, current.preview_icon, len(current.node.browser_entries),
                                  current.displayed_revision, current.preview_message)
        except Exception as exc:
            current.close()
            current.error = True
            current.message = str(exc)
            if current.batch is not None:
                current.batch_response = {"ok": False, "error": str(exc)}
            changed = True
    if changed:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "NODE_EDITOR":
                    area.tag_redraw()
    return 0.1 if _STATES else None


class SQEX_PG_texture_browser_entry(bpy.types.PropertyGroup):
    owner_id: bpy.props.StringProperty()
    display_name: bpy.props.StringProperty()
    virtual_path: bpy.props.StringProperty()
    object_path: bpy.props.StringProperty()
    texture_type: bpy.props.StringProperty()
    is_directory: bpy.props.BoolProperty()
    selected: bpy.props.BoolProperty(update=selected_changed)


class SQEX_UL_texture_browser(bpy.types.UIList):
    def draw_item(self, _context, layout, data, entry, _icon, _active_data, _active_prop, _index):
        if entry.is_directory:
            op = layout.operator("node.sqex_texture_browse", text=entry.display_name, icon="FILE_FOLDER", emboss=False)
            op.node_id, op.directory = data.browser_id, entry.virtual_path
        else:
            row = layout.row(align=True)
            row.prop(entry, "selected", text="")
            row.label(text=entry.display_name, icon="IMAGE_DATA")


def _button(layout, operator, node, **kwargs):
    state(node)  # Operators also work on a collapsed browser after save/reload.
    op = layout.operator(operator, **kwargs)
    op.node_id = node.browser_id
    return op


def draw_browser(layout, context, node, *, large=False):
    current = touch(node)
    controls = layout.row(align=True)
    controls.enabled = current.batch is None
    _button(controls, "node.sqex_texture_browse", node, text="", icon="FILE_PARENT").directory = node.directory.rsplit("/", 1)[0] if "/" in node.directory else ""
    controls.label(text=node.directory or "Package root")
    _button(controls, "node.sqex_texture_refresh", node, text="", icon="FILE_REFRESH")
    for index, line in enumerate(textwrap.wrap(current.message or "Loading texture browser…", width=90 if large else 42)):
        layout.label(text=line, icon=("ERROR" if current.error else "PACKAGE") if index == 0 else "NONE")
    if current.error:
        return
    browser = layout.column()
    browser.enabled = current.batch is None
    browser.prop(node, "search", text="", icon="VIEWZOOM")
    browser.template_list("SQEX_UL_texture_browser", node.browser_id, node, "browser_entries", node,
                          "active_index", rows=12 if large else 6)
    paging = browser.row(align=True)
    _button(paging, "node.sqex_texture_page", node, text="", icon="TRIA_LEFT").direction = -1
    paging.label(text=f"Page {node.browser_page + 1} / {max(1, (current.total + 127) // 128)}")
    _button(paging, "node.sqex_texture_page", node, text="", icon="TRIA_RIGHT").direction = 1
    row = browser.row(align=True)
    for mode, label in (("SELECT", "Select Visible"), ("INVERT", "Invert"), ("CLEAR", "Clear")):
        _button(row, "node.sqex_texture_selection", node, text=label).mode = mode
    browser.label(text=f"{len(current.selected):,} checked")
    if 0 <= node.active_index < len(node.browser_entries):
        entry = node.browser_entries[node.active_index]
        if not entry.is_directory:
            browser.label(text=entry.display_name)
            browser.label(text=entry.texture_type)
    box = layout.box()
    box.prop(node, "show_preview", text="Preview", icon="TRIA_DOWN" if node.show_preview else "TRIA_RIGHT", emboss=False)
    if node.show_preview:
        if current.preview_icon:
            box.template_icon(icon_value=current.preview_icon, scale=12 if large else 7)
        else:
            for line in textwrap.wrap(current.preview_message, width=90 if large else 36):
                box.label(text=line)
    row = layout.row()
    row.enabled = current.indexed and current.batch is None and bool(selected_entries(node))
    _button(row, "node.sqex_load_unreal_textures", node,
            text=f"Load {len(selected_entries(node))} Texture(s)", icon="IMPORT")


class SQEX_OT_texture_browse(bpy.types.Operator):
    bl_idname = "node.sqex_texture_browse"
    bl_label = "Open Texture Folder"
    bl_options = {"INTERNAL"}
    node_id: bpy.props.StringProperty()
    directory: bpy.props.StringProperty()

    def execute(self, _context):
        node = find_node(self.node_id)
        if node is None or state(node).batch is not None:
            return {"CANCELLED"}
        node.directory = self.directory
        node.search = ""
        node.browser_page = 0
        browse_changed(node, None)
        return {"FINISHED"}


class SQEX_OT_texture_page(bpy.types.Operator):
    bl_idname = "node.sqex_texture_page"
    bl_label = "Change Texture Browser Page"
    bl_options = {"INTERNAL"}
    node_id: bpy.props.StringProperty()
    direction: bpy.props.IntProperty()

    def execute(self, _context):
        node = find_node(self.node_id)
        if node is None or state(node).batch is not None:
            return {"CANCELLED"}
        node.browser_page = max(0, min(max(0, (state(node).total - 1) // 128), node.browser_page + self.direction))
        browse_changed(node, None)
        return {"FINISHED"}


class SQEX_OT_texture_selection(bpy.types.Operator):
    bl_idname = "node.sqex_texture_selection"
    bl_label = "Change Texture Selection"
    bl_options = {"INTERNAL"}
    node_id: bpy.props.StringProperty()
    mode: bpy.props.EnumProperty(items=(("SELECT", "Select Visible", ""), ("INVERT", "Invert", ""), ("CLEAR", "Clear", "")))

    def execute(self, _context):
        node = find_node(self.node_id)
        if node is None or state(node).batch is not None:
            return {"CANCELLED"}
        current = state(node)
        if self.mode == "CLEAR":
            current.selected.clear()
        for entry in node.browser_entries:
            if not entry.is_directory:
                entry.selected = (True if self.mode == "SELECT" else
                                  not entry.selected if self.mode == "INVERT" else False)
        return {"FINISHED"}


class SQEX_OT_texture_refresh(bpy.types.Operator):
    bl_idname = "node.sqex_texture_refresh"
    bl_label = "Refresh Texture Index"
    bl_description = strings.TEXTURE_BROWSER_REFRESH
    bl_options = {"INTERNAL"}
    node_id: bpy.props.StringProperty()

    def execute(self, _context):
        node = find_node(self.node_id)
        if node is None or state(node).batch is not None:
            return {"CANCELLED"}
        current = state(node)
        current.close()
        current.error = False
        current.selected.clear()
        current.force = True
        node.browser_entries.clear()
        highlight_changed(node, None)
        touch(node)
        return {"FINISHED"}


class SQEX_OT_texture_popup(bpy.types.Operator):
    bl_idname = "node.sqex_texture_popup"
    bl_label = "Unreal Engine Texture Browser"
    bl_description = strings.TEXTURE_BROWSER_POPUP
    node_id: bpy.props.StringProperty()

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=850)

    def execute(self, _context):
        return {"FINISHED"}

    def draw(self, context):
        node = find_node(self.node_id)
        if node is not None:
            row = self.layout.row()
            row.enabled = state(node).batch is None
            row.prop(node, "game", text="Game")
            if node.game_key != NONE:
                draw_browser(self.layout, context, node, large=True)


def _load_image(current, entry, info):
    if info.get("status") == "unavailable":
        raise RuntimeError(info.get("reason", "This texture has no stored pixels."))
    identity = (current.signature, entry["objectPath"].casefold())
    for image in bpy.data.images:
        if (image.get("ue_browser_source"), image.get("ue_virtual_path", "").casefold()) == identity:
            return image
    image = load_packed_image(info["output"], entry["name"], metadata={
        "ue_browser_source": current.signature, "ue_virtual_path": entry["objectPath"],
        "ue_package_path": entry["path"], "ue_texture_type": info.get("textureType", entry["textureType"]),
        "ue_texture_layout": info.get("textureLayout", "2D"), "ue_pixel_format": info.get("pixelFormat", ""),
        "ue_texture_source_width": info.get("sourceWidth", info.get("width", 1)),
        "ue_texture_source_height": info.get("sourceHeight", info.get("height", 1)),
    }, color_space="sRGB" if info.get("srgb", True) else "Non-Color")
    set_channel_packed_alpha(image)
    return image


class SQEX_OT_load_unreal_textures(bpy.types.Operator):
    bl_idname = "node.sqex_load_unreal_textures"
    bl_label = "Load Unreal Engine Textures"
    bl_description = strings.TEXTURE_BROWSER_LOAD
    bl_options = {"REGISTER", "UNDO"}
    node_id: bpy.props.StringProperty(options={"HIDDEN"})
    _timer = None

    def execute(self, context):
        node = find_node(self.node_id)
        if node is None:
            return {"CANCELLED"}
        current = state(node)
        entries = selected_entries(node)
        if not entries or not current.indexed or current.session is None or current.batch is not None:
            return {"CANCELLED"}
        try:
            profile, paths = configuration(node.game_key)
            if configuration_signature(profile, paths) != current.signature:
                raise ValueError("The game configuration changed. Refresh the texture browser before importing.")
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        current.batch = {"entries": entries, "next": 0, "loaded": 0, "failed": [], "waiting": False}
        current.batch_response = None
        if bpy.app.background:
            while not self._step(context, current):
                tick()
                time.sleep(0.02)
            return self._finish(context, current)
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _step(self, context, current):
        batch = current.batch
        if current.error or current.session is None:
            return True
        current.touched = time.monotonic()
        if batch["waiting"]:
            response = current.batch_response
            if response is None:
                return False
            current.batch_response = None
            entry = batch["entries"][batch["next"] - 1]
            try:
                if not response.get("ok"):
                    raise RuntimeError(response.get("error", "Texture extraction failed"))
                image = _load_image(current, entry, response["payload"])
                node = current.node
                target = node
                if batch["loaded"]:
                    target = node.id_data.nodes.new(NODE_TYPE)
                    target.game_key = node.game_key
                    target.browser_open = False
                    target.location = (node.location.x + 420 * ((batch["loaded"] + 2) // 3),
                                       node.location.y - 340 * ((batch["loaded"] - 1) % 3))
                target.image = image
                target.label = entry["name"]
                batch["loaded"] += 1
            except Exception as exc:
                batch["failed"].append(f"{entry['name']}: {exc}")
            finally:
                if response.get("payload"):
                    current.session.remove_image(response["payload"])
            batch["waiting"] = False
        if batch["next"] == len(batch["entries"]):
            return True
        if current.session.pending is None:
            entry = batch["entries"][batch["next"]]
            current.session.send(("texture",), action="texture", assetPath=entry["path"], objectPath=entry["objectPath"])
            batch["next"] += 1
            batch["waiting"] = True
            current.message = f"Loading texture {batch['next']} / {len(batch['entries'])}…"
        return False

    def _finish(self, context, current, *, cancelled=False):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        batch = current.batch
        current.batch = None
        if cancelled:
            current.close()
        loaded = batch["loaded"] if batch else 0
        failures = batch["failed"] if batch else []
        current.message = f"Loaded {loaded} texture(s)" + (f" · {len(failures)} failed" if failures else "")
        for failure in failures:
            self.report({"WARNING"}, failure)
        if current.error:
            self.report({"ERROR"}, "The texture bridge stopped during import. Refresh the browser to retry.")
        else:
            self.report({"INFO"}, current.message + (" (cancelled)" if cancelled else ""))
        return {"FINISHED"} if loaded else {"CANCELLED"}

    def modal(self, context, event):
        node = find_node(self.node_id)
        current = _STATES.get(self.node_id)
        if node is None or current is None or current.batch is None:
            if self._timer:
                context.window_manager.event_timer_remove(self._timer)
                self._timer = None
            return {"CANCELLED"}
        if event.type == "ESC":
            return self._finish(context, current, cancelled=True)
        if event.type == "TIMER" and self._step(context, current):
            return self._finish(context, current)
        return {"PASS_THROUGH"}


@persistent
def reset_runtime(*_args):
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    for current in _STATES.values():
        current.close()
    _STATES.clear()


@persistent
def restore_browsers(*_args):
    # SKIP_SAVE affects operator properties, not a node's embedded ID properties.
    # Keep saved shaders/images, discard transient rows and selection on load/undo.
    trees = list(bpy.data.node_groups)
    for datablocks in (bpy.data.materials, bpy.data.worlds, bpy.data.lights):
        trees.extend(item.node_tree for item in datablocks if item.node_tree)
    for tree in trees:
        for node in tree.nodes:
            if node.bl_idname == NODE_TYPE:
                node.browser_entries.clear()
                node.active_index = -1
                node.browser_page = 0
                node.search = ""
                node.browser_message = ""
    reset_runtime()


def register():
    menu = getattr(bpy.types, "NODE_MT_category_shader_texture", None)
    if menu:
        menu.append(draw_add_menu)
        _MENUS.append(menu)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if reset_runtime not in handlers:
            handlers.append(reset_runtime)
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if restore_browsers not in handlers:
            handlers.append(restore_browsers)


def unregister():
    reset_runtime()
    for menu in _MENUS:
        menu.remove(draw_add_menu)
    _MENUS.clear()
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if reset_runtime in handlers:
            handlers.remove(reset_runtime)
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if restore_browsers in handlers:
            handlers.remove(restore_browsers)


def draw_add_menu(self, _context):
    op = self.layout.operator("node.add_node", text="Unreal Engine Texture", icon="IMAGE_DATA")
    op.type = NODE_TYPE
    op.use_transform = True


CLASSES = (SQEX_PG_texture_browser_entry, SQEX_UL_texture_browser, SQEX_OT_texture_browse,
           SQEX_OT_texture_page, SQEX_OT_texture_selection, SQEX_OT_texture_refresh,
           SQEX_OT_texture_popup, SQEX_OT_load_unreal_textures)
