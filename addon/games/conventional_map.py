"""Shared package-UMAP operator for the conventional UE4 title profiles."""

from __future__ import annotations

import bpy

from ..core.blender.reporting import FF7R_LoggedOperator
from ..formats.ue_map import map_import
from .rebirth.importers import packages as shared_packages


# Remake and Crisis Core use different mounted package sets, but can share the
# same browser controls because only one import dialog is active at a time.
_ACTIVE_BROWSER = None


def _entry_selection_changed(entry, _context):
    if _ACTIVE_BROWSER is None or entry.is_directory or not entry.virtual_path:
        return
    if entry.selected:
        _ACTIVE_BROWSER["selected"].add(entry.virtual_path)
    else:
        _ACTIVE_BROWSER["selected"].discard(entry.virtual_path)


def _browser_filter_changed(_state, context):
    if _ACTIVE_BROWSER is not None:
        _ACTIVE_BROWSER["populate"](context)


class FF7R_PG_conventional_umap_entry(bpy.types.PropertyGroup):
    display_name: bpy.props.StringProperty()
    virtual_path: bpy.props.StringProperty()
    is_directory: bpy.props.BoolProperty(default=False)
    selected: bpy.props.BoolProperty(default=False, update=_entry_selection_changed)


class FF7R_PG_conventional_umap_browser(bpy.types.PropertyGroup):
    entries: bpy.props.CollectionProperty(type=FF7R_PG_conventional_umap_entry)
    active_index: bpy.props.IntProperty(default=0)
    current_directory: bpy.props.StringProperty(default="")
    filter_text: bpy.props.StringProperty(
        name="Search",
        description="Filter UMAPs by any part of their package path",
        options={"TEXTEDIT_UPDATE"},
        update=_browser_filter_changed,
    )


class FF7R_UL_conventional_umaps(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        if item.is_directory:
            op = layout.operator(
                FF7R_OT_conventional_umap_folder.bl_idname,
                text=item.display_name,
                icon="FILE_FOLDER",
                emboss=False,
            )
            op.virtual_path = item.virtual_path
        else:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")
            row.label(text=item.display_name, icon="FILE")


class FF7R_OT_conventional_umap_folder(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_conventional_umap_folder"
    bl_label = "Open Package Folder"
    bl_options = {"INTERNAL"}
    virtual_path: bpy.props.StringProperty()

    def execute(self, context):
        if _ACTIVE_BROWSER is not None:
            _ACTIVE_BROWSER["sync_selection"](context)
            _ACTIVE_BROWSER["directory"] = self.virtual_path.strip("/")
            _ACTIVE_BROWSER["populate"](context)
        return {"FINISHED"}


class FF7R_OT_conventional_umap_up(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_conventional_umap_up"
    bl_label = "Parent Folder"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if _ACTIVE_BROWSER is not None:
            _ACTIVE_BROWSER["sync_selection"](context)
            directory = _ACTIVE_BROWSER["directory"].rstrip("/")
            _ACTIVE_BROWSER["directory"] = directory.rsplit("/", 1)[0] if "/" in directory else ""
            _ACTIVE_BROWSER["populate"](context)
        return {"FINISHED"}


class FF7R_OT_conventional_umap_selection(FF7R_LoggedOperator):
    bl_idname = "wm.ff7r_conventional_umap_selection"
    bl_label = "Change UMAP Selection"
    bl_options = {"INTERNAL"}
    mode: bpy.props.EnumProperty(items=(
        ("SELECT", "Select Visible", "Select every visible UMAP"),
        ("CLEAR", "Clear All", "Clear the complete batch selection"),
        ("INVERT", "Invert Visible", "Invert visible UMAP selections"),
    ))

    def execute(self, context):
        if _ACTIVE_BROWSER is None:
            return {"CANCELLED"}
        browser = _ACTIVE_BROWSER
        state = context.window_manager.ff7r_conventional_umap_browser
        if self.mode == "CLEAR":
            browser["selected"].clear()
        else:
            browser["sync_selection"](context)
            for entry in state.entries:
                if entry.is_directory:
                    continue
                if self.mode == "SELECT":
                    browser["selected"].add(entry.virtual_path)
                else:
                    browser["selected"].symmetric_difference_update({entry.virtual_path})
        browser["populate"](context)
        return {"FINISHED"}


CLASSES = (
    FF7R_PG_conventional_umap_entry,
    FF7R_PG_conventional_umap_browser,
    FF7R_UL_conventional_umaps,
    FF7R_OT_conventional_umap_folder,
    FF7R_OT_conventional_umap_up,
    FF7R_OT_conventional_umap_selection,
)


def register_runtime_properties():
    bpy.types.WindowManager.ff7r_conventional_umap_browser = bpy.props.PointerProperty(
        type=FF7R_PG_conventional_umap_browser
    )


def unregister_runtime_properties():
    if hasattr(bpy.types.WindowManager, "ff7r_conventional_umap_browser"):
        del bpy.types.WindowManager.ff7r_conventional_umap_browser


def make_umap_importer(
        *,
        class_name: str,
        bl_idname: str,
        game_label: str,
        profile,
        configured_paths,
        material_builder=None,
        initial_directory="",
):
    """Create a title-specific conventional UMAP operator.

    Remake and Crisis Core store ordinary UE map components, so this deliberately
    shares the package actor path rather than invoking Rebirth's MEC decoder.
    Each generated operator keeps a small independent UMAP index because its
    mounted game and preference paths are distinct.
    """
    state = {
        "paths": [], "cache_key": None, "source": "", "directory": initial_directory,
        "selected": set(),
    }

    def refresh(context, *, force=False) -> list[str]:
        paths = configured_paths(context)
        cache_key = shared_packages._package_config_key(
            paths.install_root, paths.oodle_dll, paths.usmap_path
        )
        if force or cache_key != state["cache_key"]:
            result = shared_packages._run_bridge_asset_request(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                {"action": "umap_index"},
                profile=profile,
            )
            state["paths"] = sorted(
                (str(path) for path in result.get("umaps") or []),
                key=shared_packages._natural_path_key,
            )
            state["cache_key"] = cache_key
            state["source"] = "mounted packages"
        return state["paths"]

    def search(_self, _context, edit_text):
        return shared_packages._search_virtual_paths(
            state["paths"], edit_text, sort_key=shared_packages._natural_path_key,
        )

    def sync_selection(context):
        browser_state = context.window_manager.ff7r_conventional_umap_browser
        for entry in browser_state.entries:
            if not entry.is_directory:
                if entry.selected:
                    state["selected"].add(entry.virtual_path)
                else:
                    state["selected"].discard(entry.virtual_path)

    def populate(context):
        browser_state = context.window_manager.ff7r_conventional_umap_browser
        browser_state.entries.clear()
        terms = shared_packages._package_search_terms(browser_state.filter_text)
        if terms:
            rows = [(path, path, False) for path in state["paths"]
                    if shared_packages._path_matches_package_search(path, terms)]
        else:
            directory = state["directory"].strip("/")
            prefix = directory + "/" if directory else ""
            folders = {}
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
            rows = [(folder.rsplit("/", 1)[-1], folder, True)
                    for folder in sorted(folders.values(), key=str.casefold)]
            rows.extend(sorted(files, key=lambda row: row[0].casefold()))
        for display_name, virtual_path, is_directory in rows:
            entry = browser_state.entries.add()
            entry.display_name = display_name
            entry.virtual_path = virtual_path
            entry.is_directory = is_directory
            entry.selected = virtual_path in state["selected"]
        browser_state.active_index = min(browser_state.active_index, max(0, len(browser_state.entries) - 1))

    state["sync_selection"] = sync_selection
    state["populate"] = populate

    def invoke(self, context, _event):
        global _ACTIVE_BROWSER
        try:
            paths = refresh(context)
        except Exception as exc:
            self.report({"ERROR"}, f"{game_label} UMAP index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            self.report({"WARNING"}, f"No {game_label} UMAP assets were found.")
            return {"CANCELLED"}
        self._load_last_import_settings(context)
        _ACTIVE_BROWSER = state
        state["selected"].clear()
        browser_state = context.window_manager.ff7r_conventional_umap_browser
        browser_state.filter_text = ""
        browser_state.current_directory = state["directory"]
        populate(context)
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        browser_state = context.window_manager.ff7r_conventional_umap_browser
        header = layout.row(align=True)
        header.label(
            text=f"{len(state['paths']):,} UMAPs available — {len(state['selected']):,} selected",
            icon="PACKAGE",
        )
        header.operator(FF7R_OT_conventional_umap_up.bl_idname, text="", icon="FILE_PARENT")
        header.label(text=state["directory"] or "Package root")
        layout.prop(browser_state, "filter_text", text="", icon="VIEWZOOM")
        layout.template_list(
            FF7R_UL_conventional_umaps.__name__, "", browser_state, "entries",
            browser_state, "active_index", rows=12,
        )
        selection = layout.row(align=True)
        selection.operator(FF7R_OT_conventional_umap_selection.bl_idname, text="Select Visible").mode = "SELECT"
        selection.operator(FF7R_OT_conventional_umap_selection.bl_idname, text="Invert Visible").mode = "INVERT"
        selection.operator(FF7R_OT_conventional_umap_selection.bl_idname, text="Clear All").mode = "CLEAR"
        layout.separator()
        layout.prop(self, "scale_factor")
        layout.prop(self, "import_models")
        layout.prop(self, "import_lights")
        layout.prop(self, "import_light_probes")
        shadows_row = layout.row()
        shadows_row.enabled = self.import_lights
        shadows_row.prop(self, "always_cast_shadows")
        layout.label(
            text=(f"{len(state['paths']):,} {game_label} UMAP assets indexed "
                  f"({state['source'] or 'memory'})"),
            icon="PACKAGE",
        )
        layout.label(text="Imports placed mesh components and point/spot lights.")

    def execute(self, context):
        try:
            paths = configured_paths(context)
            indexed_paths = refresh(context)
            sync_selection(context)
            virtual_paths = [path for path in indexed_paths if path in state["selected"]]
            if not virtual_paths:
                browser_state = context.window_manager.ff7r_conventional_umap_browser
                if 0 <= browser_state.active_index < len(browser_state.entries):
                    highlighted = browser_state.entries[browser_state.active_index]
                    if not highlighted.is_directory:
                        virtual_paths = [highlighted.virtual_path]
            if not virtual_paths:
                raise ValueError("Highlight or select at least one UMAP from the package browser.")
            created = 0
            missing_assets = set()
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=profile,
            ) as session:
                static_mesh_resolver = (
                    shared_packages.PackageStaticMeshResolver(
                        context,
                        session,
                        self.scale_factor,
                        build_materials=material_builder is not None,
                        material_builder=material_builder,
                    )
                    if self.import_models else None
                )
                skeletal_mesh_resolver = (
                    shared_packages.PackageSkeletalMeshResolver(
                        context,
                        session,
                        self.scale_factor,
                        build_materials=material_builder is not None,
                        material_builder=material_builder,
                    )
                    if self.import_models else None
                )
                for virtual_path in virtual_paths:
                    actor_payload = session.umap_actors(virtual_path)
                    actor_data = actor_payload.get("actors") or []
                    if not actor_data:
                        continue
                    map_created, map_missing = map_import.import_map_entries(
                        actor_data, virtual_path, exposure_mult=1.0,
                        attenuation_radius_mult=1.0, location_scale=self.scale_factor,
                        always_cast_shadows=self.always_cast_shadows,
                        static_mesh_resolver=static_mesh_resolver,
                        skeletal_mesh_resolver=skeletal_mesh_resolver,
                        import_models=self.import_models, import_lights=self.import_lights,
                        import_reflection_probes=self.import_light_probes,
                    )
                    created += map_created
                    missing_assets.update(map_missing)
            if not created:
                raise ValueError("The selected UMAPs have no supported mesh or light components.")
        except Exception as exc:
            self.report({"ERROR"}, f"{game_label} UMAP import failed: {exc}")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        missing_note = f"; {len(missing_assets)} mesh asset(s) missing" if missing_assets else ""
        self.report({"INFO"}, f"Imported {len(virtual_paths)} {game_label} UMAP(s): {created:,} placement(s){missing_note}")
        return {"FINISHED"}

    attributes = {
        "bl_idname": bl_idname,
        "bl_label": f"UMAP from {game_label} Packages",
        "bl_description": f"Import placed meshes and lights from a {game_label} UMAP",
        "bl_options": {"REGISTER", "UNDO"},
        "__annotations__": {
            "scale_factor": bpy.props.FloatProperty(
                name="Scale",
                description="Convert Unreal centimeters to Blender units",
                default=0.01,
                min=0.0001,
                max=100.0,
            ),
            "import_models": bpy.props.BoolProperty(
                name="Import Mesh Placements",
                description="Create placed StaticMesh and SkeletalMesh components",
                default=True,
            ),
        "import_lights": bpy.props.BoolProperty(
                name="Import Light Placements",
                description="Create placed point and spot lights",
            default=True,
        ),
        "import_light_probes": bpy.props.BoolProperty(
            name="Generate Eevee Light Probes",
            description=(
                "Create editable Eevee light probes for sphere and box reflection captures. "
                "Box capture offsets are stored but left unapplied for manual adjustment"
            ),
            default=False,
        ),
            "always_cast_shadows": bpy.props.BoolProperty(
                name="Always Cast Shadows",
                description="Force imported lights to cast shadows",
                default=False,
            ),
        },
        "_persisted_props": (
            "scale_factor", "import_models", "import_lights", "import_light_probes", "always_cast_shadows",
        ),
        "invoke": invoke,
        "draw": draw,
        "execute": execute,
    }
    return type(class_name, (FF7R_LoggedOperator,), attributes)
