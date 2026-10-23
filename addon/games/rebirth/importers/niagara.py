"""Rebirth Niagara mesh-resource browser and generic-material session."""

import os

import bpy

from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....core.package_utils import addon_package_name
from ....formats.niagara.package_data import decode_package
from ....formats.niagara.resources import import_mesh_resources
from ....formats.unreal_mesh.session import GenericSession
from ....formats.unreal_package.paths import _game_asset_path_to_virtual_uasset
from ....formats.unreal_package.session import _run_gargoyle_asset_request
from ....language import strings
from ....ui.textures import TEXTURE_OPTION_NAMES, draw_texture_options, texture_options, texture_properties
from ... import package_browser
from ..profile import PROFILE


DEFAULT_FOLDER = "End/Content/Effect"
_BROWSER = package_browser.make_state(
    "Niagara systems", initial_directory=DEFAULT_FOLDER, root_directory="End/Content", file_icon="PARTICLES",
)
_INDEX_KEY = None


def _paths(context):
    addon = context.preferences.addons.get(addon_package_name(__package__))
    if addon is None:
        raise RuntimeError("Talisman preferences are unavailable.")
    paths = PROFILE.paths_from_preferences(addon.preferences, bpy.path.abspath)
    if not paths.install_root or not os.path.isdir(paths.install_root):
        raise FileNotFoundError("Set a valid FINAL FANTASY VII REBIRTH install folder.")
    for path, label in ((paths.oodle_dll, "Oodle DLL"), (paths.usmap_path, "Rebirth .usmap")):
        if path and not os.path.isfile(path):
            raise FileNotFoundError(f"The configured {label} does not exist.")
    return paths


class NiagaraSession(GenericSession):
    """Use Rebirth mesh decoding and the existing generic UE material pipeline."""

    def __init__(self, paths, **options):
        super().__init__(paths, "GAME_FinalFantasy7Rebirth", nanite_mode="FALLBACK", **options)
        # Keep native Rebirth geometry/export decoding. Material and texture
        # requests deliberately remain GenericSession.generic_* operations.
        self.profile = PROFILE

    def request(self, payload, *, report_errors=True):
        if payload.get("action") in {"generic_material", "generic_texture"}:
            # Rebirth does not load the generic provider's virtual-path aliases.
            # Keep the object selector while addressing the mounted package.
            virtual = _game_asset_path_to_virtual_uasset(payload.get("assetPath"), profile=PROFILE)
            if virtual:
                payload = dict(payload, assetPath=virtual)
        return super().request(payload, report_errors=report_errors)


def refresh_index(context, folder=DEFAULT_FOLDER, *, force=False):
    global _INDEX_KEY
    paths = _paths(context)
    folder = folder.strip().replace("\\", "/").strip("/")
    key = (paths, folder)
    if force or key != _INDEX_KEY:
        response = _run_gargoyle_asset_request(
            paths.install_root, paths.oodle_dll, paths.usmap_path,
            {"action": "niagara_index", "pathFilter": folder}, profile=PROFILE,
        )
        index = response.get("index")
        if not isinstance(index, dict):
            raise RuntimeError("The bundled bridge does not support Niagara indexing. Reinstall the matching add-on and bridge.")
        if index.get("failures") and not index.get("readablePackages"):
            raise ValueError("No readable package headers were found in this folder.")
        _BROWSER["paths"] = list(index.get("paths") or [])
        _INDEX_KEY = key
    return _BROWSER["paths"]


def _activate(context, paths, folder):
    folder = folder.strip().replace("\\", "/").strip("/")
    _BROWSER["directory"] = folder if folder.startswith("End/Content") and any(
        p.startswith(folder + "/") for p in paths) else "End/Content"
    package_browser.activate(context, _BROWSER, paths,
                             dialog_operator=FF7R_REBIRTH_OT_import_niagara_game_packages.bl_idname)


class FF7R_REBIRTH_OT_refresh_niagara_assets(SQEX_LoggedOperator):
    bl_idname = "wm.ff7r_rebirth_refresh_niagara_assets"
    bl_label = "Refresh Niagara Assets"
    bl_description = strings.REBIRTH_NIAGARA_REFRESH
    bl_options = {'INTERNAL'}
    path_filter: bpy.props.StringProperty(options={'HIDDEN'})

    def execute(self, context):
        try:
            _activate(context, refresh_index(context, self.path_filter, force=True), self.path_filter)
        except Exception as exc:
            report(self, {'ERROR'}, f"Niagara asset list failed: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class FF7R_REBIRTH_OT_import_niagara_game_packages(SQEX_LoggedOperator):
    bl_idname = "import_scene.ff7r_rebirth_niagara_game_packages"
    bl_label = "Niagara Meshes from Rebirth Packages"
    bl_description = strings.REBIRTH_NIAGARA_DESCRIPTION
    bl_options = {'REGISTER', 'UNDO'}
    _persisted_props = ("scale_factor", "import_textures", *TEXTURE_OPTION_NAMES)

    virtual_path: bpy.props.StringProperty(
        name="Asset Path", description=strings.REBIRTH_NIAGARA_VIRTUAL_PATH, options={'HIDDEN'},
    )
    path_filter: bpy.props.StringProperty(
        name="Asset Folder", default=DEFAULT_FOLDER, description=strings.REBIRTH_NIAGARA_FOLDER,
    )
    scale_factor: bpy.props.FloatProperty(
        name="Scale", default=0.01, min=0.000001, max=100, description=strings.SHARED_SCALE_FACTOR,
    )
    import_textures: bpy.props.BoolProperty(
        name="Import Textures", default=True, description=strings.REBIRTH_MEC_IMPORT_TEXTURES,
    )
    __annotations__.update(texture_properties())

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, _event):
        try:
            self._load_last_import_settings(context)
            self.virtual_path = ""
            _activate(context, refresh_index(context, self.path_filter), self.path_filter)
        except Exception as exc:
            report(self, {'ERROR'}, f"Niagara asset list failed: {exc}")
            return {'CANCELLED'}
        return package_browser.invoke_dialog(self, context, width=1000)

    def draw(self, context):
        layout = self.layout
        folder = layout.row(align=True)
        folder.prop(self, "path_filter")
        folder.operator(FF7R_REBIRTH_OT_refresh_niagara_assets.bl_idname,
                        text="Refresh Assets", icon="FILE_REFRESH").path_filter = self.path_filter
        package_browser.draw(layout, context, _BROWSER)
        layout.prop(self, "scale_factor")
        layout.prop(self, "import_textures")
        textures = layout.column()
        textures.enabled = self.import_textures
        draw_texture_options(textures, self)
        layout.label(text="Mesh/material resources only. Materials use the generic UE pipeline.", icon="INFO")

    def cancel(self, context):
        package_browser.close_dialog(self)
        self._save_last_import_settings(context)

    def execute(self, context):
        package_browser.close_dialog(self)
        try:
            paths = _paths(context)
            if self.virtual_path.strip():
                path = self.virtual_path.strip().replace("\\", "/")
                virtual = _game_asset_path_to_virtual_uasset(path, profile=PROFILE)
                if not virtual:
                    raise ValueError("Use a mounted Rebirth .uasset path or a /Game object path.")
                selected_paths = [virtual]
            else:
                selected_paths = package_browser.selected_paths(context, _BROWSER)
            if not selected_paths:
                raise ValueError("Select at least one Niagara system in the package browser.")
            object_count = mesh_count = skipped = 0
            failures = []
            with NiagaraSession(paths, import_textures=self.import_textures, **texture_options(self)) as mounted:
                for asset_path in selected_paths:
                    try:
                        package = decode_package(mounted.niagara_asset(asset_path), asset_path)
                        result = import_mesh_resources(context, package, mounted,
                                                       profile=PROFILE, scale_factor=self.scale_factor)
                        object_count += len(result.objects)
                        mesh_count += result.mesh_count
                        skipped += result.skipped_renderers
                        failures.extend(result.failures)
                        for warning in result.warnings:
                            print(f"[Niagara resource WARNING] {asset_path}: {warning}")
                    except Exception as exc:
                        failures.append(f"{asset_path}: {exc}")
                        print(f"[Niagara resource WARNING] {asset_path}: {exc}")
        except Exception as exc:
            report(self, {'ERROR'}, f"Niagara mesh import failed: {exc}")
            return {'CANCELLED'}
        if not object_count:
            report(self, {'WARNING'}, "No readable Niagara mesh resources were imported. "
                   + (f"{len(failures)} resource failure(s); see console." if failures else "Non-mesh renderers are not imported."))
            return {'CANCELLED'}
        self._save_last_import_settings(context)
        report(self, {'WARNING'} if failures else {'INFO'},
               f"Imported {object_count} Niagara mesh/material object(s), {mesh_count} mesh datablock(s); "
               f"{skipped} non-mesh renderer(s) skipped."
               + (f" {len(failures)} resource failure(s); see console." if failures else ""))
        return {'FINISHED'}


CLASSES = (FF7R_REBIRTH_OT_refresh_niagara_assets, FF7R_REBIRTH_OT_import_niagara_game_packages)
