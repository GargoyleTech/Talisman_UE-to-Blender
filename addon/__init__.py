"""Blender add-on entry point and registration coordinator."""

bl_info = {
    "name": "FF7R Tools",
    "author": "GargoyleTech",
    "version": (0, 9, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > FF7R Retrilogy; Object > Retrilogy tools",
    "description": "FF7R package/static-mesh, UMAP, KineDriver, and cleanup tools",
    "category": "Import-Export",
}

import importlib

import bpy


# Blender retains registered Python class objects across a script reload. Clean
# up the previous generation before importing and registering replacements.
_previous_reload_cleanup = globals().get("_ff7r_reload_cleanup")
if callable(_previous_reload_cleanup):
    try:
        _previous_reload_cleanup()
    except Exception as exc:
        print(f"[FF7R reload WARNING] Previous registration cleanup failed: {exc}")


from .core import bridge as bridge_core
from .core import profiles as game_profiles
from .core.blender import render_settings, reporting, skeletons, z_fighting
from . import games as game_registry
from .formats.kdi import audit as kdi_audit
from .formats.kdi import drivers as kdi_drivers
from .formats.kdi import nodetree as kdi_nodetree
from .formats.mec import importer as mec_importer
from .formats.mec import material as mec_material
from .formats.mec import parser as mec_parser
from .formats.ue_map import lights, map_import, particles, timeline_actions, worlds
from .games import conventional_map, package_browser
from .games.crisis_core import profile as crisis_core_profile
from .games.crisis_core.importers import static_mesh as crisis_core_static_mesh
from .games.rebirth import profile as rebirth_profile
from .games.rebirth.importers import animations
from .games.rebirth.importers import packages as game_packages
from .games.rebirth.materials import rmi_surface
from .games.remake import profile as remake_profile
from .games.remake.importers import static_mesh as remake_static_mesh
from .ui import menus as ui_menus
from .ui import operators as ui_operators
from .ui import preferences as ui_preferences


# Reload dependencies before their consumers so in-place add-on development
# does not require restarting Blender after a source edit.
for _module in (
    game_profiles,
    bridge_core,
    remake_profile,
    rebirth_profile,
    crisis_core_profile,
    game_registry,
    package_browser,
    conventional_map,
    reporting,
    render_settings,
    lights,
    particles,
    worlds,
    timeline_actions,
    map_import,
    kdi_audit,
    kdi_drivers,
    kdi_nodetree,
    mec_material,
    mec_parser,
    mec_importer,
    skeletons,
    rmi_surface,
    game_packages,
    animations,
    remake_static_mesh,
    crisis_core_static_mesh,
    z_fighting,
    ui_preferences,
    ui_operators,
    ui_menus,
):
    importlib.reload(_module)


classes = tuple(
    cls
    for cls in (
        *ui_preferences.CLASSES,
        *animations.CLASSES,
        *package_browser.CLASSES,
        *conventional_map.CLASSES,
        mec_importer.FF7R_REBIRTH_OT_import_mec_umap,
        *game_packages.CLASSES,
        *remake_static_mesh.CLASSES,
        *crisis_core_static_mesh.CLASSES,
        *kdi_nodetree.CLASSES,
        mec_importer.FF7R_REBIRTH_FH_import_mec_umap,
        z_fighting.MESH_OT_find_opposite_faces,
        *ui_operators.CLASSES,
        *ui_menus.CLASSES,
    )
    if cls is not None
)


_REGISTERED = False


def _remove_menu_callback(menu, callback) -> None:
    try:
        menu.remove(callback)
    except (AttributeError, RuntimeError, ValueError):
        pass


def _unregister_class(cls) -> None:
    try:
        bpy.utils.unregister_class(cls)
    except (RuntimeError, ValueError):
        pass


def _register_class(cls) -> None:
    _unregister_class(cls)
    stale_class = getattr(bpy.types, cls.__name__, None)
    if stale_class is not None and stale_class is not cls:
        _unregister_class(stale_class)
    bpy.utils.register_class(cls)


def register():
    global _REGISTERED
    if _REGISTERED:
        unregister()
    _REGISTERED = True
    try:
        for cls in classes:
            _register_class(cls)
        kdi_nodetree.register_add_menu()
        package_browser.register_runtime_properties()
        conventional_map.register_runtime_properties()
        game_packages.register_runtime_properties()
        bpy.types.TOPBAR_MT_file_import.append(ui_menus.menu_func_import)
        bpy.types.VIEW3D_MT_object.append(ui_menus.menu_func_object)
        bpy.types.VIEW3D_MT_edit_armature.append(ui_menus.menu_func_edit_armature)
        bpy.types.VIEW3D_MT_pose_context_menu.append(ui_menus.menu_func_pose_bone)
        kdi_drivers.register()
    except Exception:
        unregister()
        raise


def unregister():
    global _REGISTERED
    try:
        kdi_drivers.unregister()
    except Exception as exc:
        print(f"[FF7R reload WARNING] KDI cleanup failed: {exc}")
    try:
        kdi_nodetree.unregister_add_menu()
    except Exception as exc:
        print(f"[FF7R reload WARNING] KDI node-menu cleanup failed: {exc}")
    _remove_menu_callback(bpy.types.VIEW3D_MT_edit_armature, ui_menus.menu_func_edit_armature)
    _remove_menu_callback(bpy.types.VIEW3D_MT_object, ui_menus.menu_func_object)
    _remove_menu_callback(bpy.types.VIEW3D_MT_pose_context_menu, ui_menus.menu_func_pose_bone)
    _remove_menu_callback(bpy.types.TOPBAR_MT_file_import, ui_menus.menu_func_import)
    try:
        game_packages.unregister_runtime_properties()
    except Exception as exc:
        print(f"[FF7R reload WARNING] Package-browser cleanup failed: {exc}")
    try:
        conventional_map.unregister_runtime_properties()
    except Exception as exc:
        print(f"[FF7R reload WARNING] Conventional package-browser cleanup failed: {exc}")
    try:
        package_browser.unregister_runtime_properties()
    except Exception as exc:
        print(f"[FF7R reload WARNING] Mesh package-browser cleanup failed: {exc}")
    for cls in reversed(classes):
        _unregister_class(cls)
    _REGISTERED = False


_ff7r_reload_cleanup = unregister


if __name__ == "__main__":
    register()
