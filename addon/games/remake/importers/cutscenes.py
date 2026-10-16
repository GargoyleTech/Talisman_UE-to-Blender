"""Import UE4 LevelSequence cutscenes directly from Remake packages."""

from __future__ import annotations

from ....language import tooltips

from pathlib import Path
import traceback

import bpy

from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....formats.ue_map import cutscene_import
from ... import package_browser
from ....formats import unreal_package as shared_packages
from ..profile import PROFILE
from . import static_mesh


_CUTSCENE_BROWSER = package_browser.make_state(
    "Remake LevelSequence camera packages",
    initial_directory="End/Content/GameContents/Cut/Game",
    file_icon="CAMERA_DATA",
)
_CUTSCENES: list[str] = []
_CUTSCENE_CACHE_KEY = None


def _search_cutscenes(_self, _context, edit_text):
    return shared_packages._search_virtual_paths(_CUTSCENES, edit_text)


def _refresh_cutscenes(context, *, force=False) -> list[str]:
    global _CUTSCENE_CACHE_KEY, _CUTSCENES
    paths = static_mesh._configured_paths(context)
    cache_key = (
        *shared_packages._package_config_key(
            paths.install_root, paths.oodle_dll, paths.usmap_path),
        paths.aes_key,
    )
    if force or cache_key != _CUTSCENE_CACHE_KEY:
        result = shared_packages._run_gargoyle(
            paths.install_root, paths.oodle_dll, paths.usmap_path,
            path_filter="/GameContents/Cut/Game/", profile=PROFILE, aes_key=paths.aes_key,
        )
        _CUTSCENES = sorted(
            (path for path in result.get("files", [])
             if path.casefold().endswith("_camera.uasset")),
            key=shared_packages._natural_path_key,
        )
        _CUTSCENE_CACHE_KEY = cache_key
    return _CUTSCENES


class FF7R_REMAKE_OT_import_cutscene_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_remake_cutscene_game_packages"
    bl_label = "Cutscene from Remake Packages"
    bl_description = tooltips.REMAKE_CUTSCENE_DESCRIPTION
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(
        name="Cutscene",
        description=tooltips.REMAKE_CUTSCENE_VIRTUAL_PATH,
        search=_search_cutscenes,
        search_options={"SUGGESTION"},
    )
    import_cameras: bpy.props.BoolProperty(name="Import Cameras", default=True)
    import_lights: bpy.props.BoolProperty(name="Import Lights", default=True)
    import_characters: bpy.props.BoolProperty(
        name="Apply Character Sequencing",
        description=tooltips.REMAKE_CUTSCENE_IMPORT_CHARACTERS,
        default=True,
    )
    always_cast_shadows: bpy.props.BoolProperty(name="Always Cast Shadows", default=False)

    def invoke(self, context, _event):
        try:
            paths = _refresh_cutscenes(context)
        except Exception as exc:
            report(self, {"ERROR"}, f"Remake cutscene index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            report(self, {"WARNING"}, "No Remake _Camera LevelSequence packages were found.")
            return {"CANCELLED"}
        package_browser.activate(context, _CUTSCENE_BROWSER, paths, dialog_operator=self.bl_idname)
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, _CUTSCENE_BROWSER)
        layout.prop(self, "import_cameras")
        layout.prop(self, "import_lights")
        layout.prop(self, "import_characters")
        layout.prop(self, "always_cast_shadows")
        layout.label(text=f"{len(_CUTSCENES):,} Remake camera sequences indexed", icon="PACKAGE")
        if self.import_characters:
            layout.label(text="Character actions must be imported first and retain their package source paths.", icon="INFO")

    def execute(self, context):
        try:
            compatible = _refresh_cutscenes(context)
            _CUTSCENE_BROWSER["paths"] = list(compatible)
            selected = package_browser.resolve_paths(context, _CUTSCENE_BROWSER, self.virtual_path)
            if len(selected) != 1:
                raise ValueError("Select exactly one _Camera package.")
            camera_path = selected[0]
            root = camera_path[:-len("_Camera.uasset")]
            paths = static_mesh._configured_paths(context)
        except Exception as exc:
            report(self, {"ERROR"}, f"Remake cutscene import failed: {exc}")
            return {"CANCELLED"}

        name = Path(root).name
        scene = context.scene
        collection = shared_packages._ensure_scene_collection(scene, name)
        known_collections = {child.name for child in scene.collection.children}
        try:
            with shared_packages.PackageAssetSession(
                    paths.install_root, paths.oodle_dll, paths.usmap_path,
                    profile=PROFILE, aes_key=paths.aes_key) as session, \
                    shared_packages._active_collection(context, collection):
                decoded = {"camera": session.cutscene_asset(camera_path).get("exports") or []}
                for kind in ("character", "light"):
                    if kind == "character" and not self.import_characters:
                        continue
                    if kind == "light" and not self.import_lights:
                        continue
                    try:
                        decoded[kind] = session.cutscene_asset(root + f"_{kind.title()}.uasset").get("exports") or []
                    except Exception as exc:
                        print(f"[FF7R Remake cutscene] {kind} sequence unavailable: {exc}")
                cutscene_import.import_ue_cutscene_data(
                    decoded.get("camera"), decoded.get("character"), decoded.get("light"), name,
                    import_cameras=self.import_cameras,
                    import_lights=self.import_lights,
                    import_characters=self.import_characters,
                    always_cast_shadows=self.always_cast_shadows,
                    target_collection=collection,
                )
        except Exception as exc:
            print(f"[FF7R Remake cutscene] Import failed for '{camera_path}':")
            traceback.print_exc()
            report(self, {"ERROR"}, f"Remake cutscene import failed: {exc}")
            return {"CANCELLED"}
        adopted = shared_packages._adopt_new_scene_collections(scene, collection, known_collections)
        report(self, {"INFO"},
               f"Imported Remake cutscene '{name}' into '{collection.name}' "
               f"({len(collection.all_objects)} object(s)"
               + (f", {adopted} adopted collection(s)" if adopted else "") + ").")
        return {"FINISHED"}


CLASSES = (FF7R_REMAKE_OT_import_cutscene_game_packages,)
