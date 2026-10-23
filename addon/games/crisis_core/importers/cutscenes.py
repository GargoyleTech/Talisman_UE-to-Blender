"""Crisis Core LevelSequences on the shared Sequencer import workflow."""

import hashlib
import json

from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....formats import unreal_package as packages
from ....formats.unreal_mesh import sequences
from ....formats.unreal_mesh.sequence_data import asset_path
from ....formats.unreal_mesh.session import source_id
from ....language import strings
from ... import package_browser
from .. import materials
from ..profile import PROFILE
from . import static_mesh


_CUTSCENE_BROWSER = package_browser.make_state(
    "Crisis Core LevelSequence assets",
    initial_directory="CCFF7R/Content/Fair/Camera/Event",
    file_icon="CAMERA_DATA",
)
_CUTSCENES = []
_CUTSCENE_CACHE_KEY = None


class CrisisCoreSequenceSession(packages.PackageAssetSession):
    """Keep Crisis Core's profile, textures and materials for bound actors."""

    material_builder = staticmethod(materials.build_material)

    def __init__(self, paths):
        super().__init__(paths.install_root, paths.oodle_dll, paths.usmap_path,
                         profile=PROFILE, aes_key=paths.aes_key)
        self.cache_namespace = source_id(paths, PROFILE.gargoyle_profile)
        self.game_version = "GAME_UE4_27"
        self.mount_info = {"contentRoot": PROFILE.mounted_content_root + "/"}

    def request(self, payload, *, report_errors=True):
        # Sequencer templates refer to /Game/Package.Object; the title mesh
        # endpoints consume package paths rather than object references.
        payload = dict(payload)
        path = payload.get("assetPath")
        if path:
            if not path.casefold().endswith((".uasset", ".umap")):
                path = asset_path(path)
            if path.startswith("/Game/"):
                path = PROFILE.mounted_content_root + "/" + path[6:]
            payload["assetPath"] = path
        object_path = payload.get("objectPath") or ""
        content_root = PROFILE.mounted_content_root + "/"
        if object_path.casefold().startswith(content_root.casefold()):
            # Existing level bindings use mounted paths for lookup, while
            # UObject.GetPathName() uses /Game when locating the export.
            payload["objectPath"] = "/Game/" + object_path[len(content_root):]
        return super().request(payload, report_errors=report_errors)


def refresh_cutscene_index(context, *, force=False):
    global _CUTSCENES, _CUTSCENE_CACHE_KEY
    paths = static_mesh._configured_paths(context)
    key = (*packages._package_config_key(paths.install_root, paths.oodle_dll, paths.usmap_path),
           hashlib.sha256(paths.aes_key.encode()).hexdigest())
    if force or key != _CUTSCENE_CACHE_KEY:
        result = packages._run_gargoyle_asset_request(
            paths.install_root, paths.oodle_dll, paths.usmap_path,
            {"action": "generic_asset_index", "assetClass": "LevelSequence"},
            profile=PROFILE, aes_key=paths.aes_key,
        )["index"]
        _CUTSCENES = sorted((item["path"] for item in result.get("assets") or []),
                            key=packages._natural_path_key)
        _CUTSCENE_CACHE_KEY = key
        for warning in result.get("warnings") or []:
            print(f"[Crisis Core sequence WARNING] {warning}")
    return _CUTSCENES


class FF7R_CRISIS_CORE_OT_import_cutscene_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_crisis_core_cutscene_game_packages"
    bl_label = "Cutscene from Crisis Core Packages"
    bl_description = strings.GENERIC_SEQUENCE_DESCRIPTION
    bl_options = {"REGISTER", "UNDO"}

    __annotations__ = sequences.sequence_properties()
    _persisted_props = (
        "scale_factor", "load_missing", "import_models", "import_cameras", "import_lights",
        "import_animation", "replace_existing", "set_frame_range",
    )
    _import_path = sequences.import_sequence_path

    def invoke(self, context, _event):
        self.start_frame = context.scene.frame_current
        self._load_last_import_settings(context)
        try:
            paths = refresh_cutscene_index(context)
            if not paths:
                raise ValueError("No Crisis Core LevelSequence assets were found.")
            package_browser.activate(context, _CUTSCENE_BROWSER, paths, dialog_operator=self.bl_idname)
        except Exception as exc:
            report(self, {"ERROR"}, f"Crisis Core cutscene index failed: {exc}")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=1050)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, _CUTSCENE_BROWSER, rows=9)
        layout.label(text=f"{len(_CUTSCENES):,} Crisis Core sequences indexed", icon="PACKAGE")
        layout.prop(self, "virtual_path")
        layout.label(text="Select a master sequence to include nested shots. Multiple selections create separate scenes.", icon="SCENE_DATA")
        row = layout.row()
        row.prop(self, "start_frame")
        row.prop(self, "scale_factor")
        row = layout.row()
        for key in ("import_models", "import_cameras", "import_lights", "import_animation"):
            row.prop(self, key)
        for key in ("load_missing", "replace_existing", "set_frame_range"):
            layout.prop(self, key)
        layout.label(text="Unsupported events, audio and effects are recorded in the sequence report.", icon="INFO")

    def execute(self, context):
        try:
            paths = static_mesh._configured_paths(context)
            if self.virtual_path.strip():
                selected = [self.virtual_path.strip()]
            else:
                _CUTSCENE_BROWSER["paths"] = list(refresh_cutscene_index(context))
                selected = package_browser.selected_paths(context, _CUTSCENE_BROWSER)
            if not selected:
                raise ValueError("Select at least one Crisis Core LevelSequence.")
            overrides = json.loads(self.binding_overrides or "{}")
            if not isinstance(overrides, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in overrides.items()):
                raise ValueError("Binding overrides must map binding IDs to scene object names.")
            if len(selected) > 1 and overrides:
                raise ValueError("Explicit binding overrides require a single selected LevelSequence.")
            with CrisisCoreSequenceSession(paths) as mounted:
                return sequences.import_selected_sequences(self, context, mounted, selected, overrides)
        except Exception as exc:
            report(self, {"ERROR"}, f"Crisis Core cutscene import failed: {exc}")
            return {"CANCELLED"}


CLASSES = (FF7R_CRISIS_CORE_OT_import_cutscene_game_packages,)
