"""Blender add-on entry point and registration coordinator."""

bl_info = {
    "name": "Talisman for Unreal Engine",
    "author": "GargoyleTech",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > Unreal Engine (Talisman); Object > Talisman",
    "description": "Import Unreal Engine meshes, maps and animations into Blender",
    "doc_url": "https://github.com/GargoyleTech/Talisman_UE-to-Blender",
    "tracker_url": "https://github.com/GargoyleTech/Talisman_UE-to-Blender/issues",
    "category": "Import-Export",
}

import importlib

import bpy


# Blender retains registered Python class objects across a script reload. Clean
# up the previous generation before importing and registering replacements.
_previous_reload_cleanup = globals().get("_sqex_reload_cleanup")
if callable(_previous_reload_cleanup):
    try:
        _previous_reload_cleanup()
    except Exception as exc:
        print(f"[Talisman reload WARNING] Previous registration cleanup failed: {exc}")


# Refresh the master text module before any consumer recreates RNA properties.
from .language import tooltips
importlib.reload(tooltips)

from .core import bridge as gargoyle_core
from .core import profiles as game_profiles
from .core.blender import ik_rig, lip_rig, mouth_rig, render_settings, reporting, skeletons, z_fighting
from . import games as game_registry
from .formats.bnm import parser as bnm_parser
from .formats.bnm import storage as bnm_storage
from .formats.kdi import audit as kdi_audit
from .formats.kdi import drivers as kdi_drivers
from .formats.kdi import nodetree as kdi_nodetree
from .formats.mec import importer as mec_importer
from .formats.mec import material as mec_material
from .formats.mec import parser as mec_parser
from .formats.ue_map import lights, map_import, particles, timeline_actions, worlds
from .core.blender import material_nodes
from .core.blender import animation as animation_core
from .core.blender import collections as scene_collections
from .formats import unreal_package as package_runtime
from .formats.unreal_package import (
    options as package_options,
    paths as package_paths,
    indexing as package_indexing,
    skeleton_data as package_skeleton_data,
    session as package_session,
    mesh_import as package_mesh_import,
    resolvers as package_resolvers,
)
from .games import conventional_map, conventional_mesh, conventional_animation, package_browser
from .games.crisis_core import profile as crisis_core_profile
from .games.crisis_core.importers import static_mesh as crisis_core_static_mesh
from .games.crisis_core.importers import animations as crisis_core_animations
from .games.kingdom_hearts.importers import static_mesh as kingdom_hearts_static_mesh
from .games.kingdom_hearts.importers import matinee as kingdom_hearts_matinee
from .games.kingdom_hearts import materials as kingdom_hearts_materials
from .games.kingdom_hearts_0_2 import profile as kingdom_hearts_0_2_profile
from .games.kingdom_hearts_0_2.importers import static_mesh as kingdom_hearts_0_2_static_mesh
from .games.kingdom_hearts_iii import profile as kingdom_hearts_iii_profile
from .games.kingdom_hearts_iii.importers import static_mesh as kingdom_hearts_iii_static_mesh
from .games.rebirth import profile as rebirth_profile
from .games.rebirth.importers import animations
from .games.rebirth.importers import packages as game_packages
from .games.rebirth.materials import rmi_surface
from .games.remake import profile as remake_profile
from .games.remake import materials as remake_materials
from .games.crisis_core import materials as crisis_core_materials
from .games.remake.importers import static_mesh as remake_static_mesh
from .games.remake.importers import animations as remake_animations
from .games.remake.importers import cutscenes as remake_cutscenes
from .formats.unreal_mesh import importer as generic_unreal_importer
from .formats.unreal_mesh import materials as generic_unreal_materials
from .formats.unreal_mesh import session as generic_unreal_session
from .formats.unreal_mesh import profile_test as generic_profile_test
from .formats.unreal_mesh import maps as generic_unreal_maps
from .formats.unreal_mesh import animations as generic_unreal_animations
from .formats.unreal_mesh import sequence_data as generic_sequence_data
from .formats.unreal_mesh import sequence_bindings as generic_sequence_bindings
from .formats.unreal_mesh import sequence_import as generic_sequence_import
from .formats.unreal_mesh import sequences as generic_sequences
from .ui import menus as ui_menus
from .ui import textures as ui_textures
from .ui import mesh_importer as ui_mesh_importer
from .ui import map_importer as ui_map_importer
from .formats.ue_map import streaming as map_streaming
from .formats.ue_map import package_importer as package_map_importer
from .formats.unreal_package import importer as package_mesh_importer
from .ui import operators as ui_operators
from .ui import preferences as ui_preferences
from .ui import skeletal_mesh as ui_skeletal_mesh
from .ui import mouth_rig as ui_mouth_rig
from .ui import ik_rig as ui_ik_rig
from .ui import light_attenuation as ui_light_attenuation


# Reload dependencies before their consumers so in-place add-on development
# does not require restarting Blender after a source edit.
for _module in (
    game_profiles,
    ui_textures,
    ui_map_importer,
    gargoyle_core,
    remake_profile,
    rebirth_profile,
    crisis_core_profile,
    kingdom_hearts_iii_profile,
    kingdom_hearts_0_2_profile,
    game_registry,
    package_browser,
    reporting,
    render_settings,
    lights,
    particles,
    worlds,
    animation_core,
    timeline_actions,
    map_import,
    map_streaming,
    package_map_importer,
    conventional_map,
    bnm_parser,
    bnm_storage,
    kdi_audit,
    kdi_drivers,
    kdi_nodetree,
    material_nodes,
    mec_material,
    mec_parser,
    mec_importer,
    ik_rig,
    skeletons,
    mouth_rig,
    lip_rig,
    ui_mesh_importer,
    ui_skeletal_mesh,
    rmi_surface,
    remake_materials,
    crisis_core_materials,
    scene_collections,
    package_options,
    package_paths,
    package_session,
    package_indexing,
    package_skeleton_data,
    package_mesh_import,
    package_resolvers,
    package_runtime,
    package_mesh_importer,
    conventional_mesh,
    conventional_animation,
    game_packages,
    generic_unreal_session,
    generic_profile_test,
    generic_unreal_materials,
    generic_unreal_maps,
    generic_unreal_importer,
    animations,
    generic_unreal_animations,
    generic_sequence_data,
    generic_sequence_bindings,
    generic_sequence_import,
    generic_sequences,
    remake_static_mesh,
    remake_animations,
    remake_cutscenes,
    crisis_core_static_mesh,
    crisis_core_animations,
    kingdom_hearts_materials,
    kingdom_hearts_static_mesh,
    kingdom_hearts_matinee,
    kingdom_hearts_0_2_static_mesh,
    kingdom_hearts_iii_static_mesh,
    z_fighting,
    ui_preferences,
    ui_operators,
    ui_mouth_rig,
    ui_ik_rig,
    ui_light_attenuation,
    ui_menus,
):
    importlib.reload(_module)


classes = tuple(
    cls
    for cls in (
        *ui_preferences.CLASSES,
        *animations.CLASSES,
        *remake_animations.CLASSES,
        *remake_cutscenes.CLASSES,
        *package_browser.CLASSES,
        *conventional_map.CLASSES,
        mec_importer.FF7R_REBIRTH_OT_import_mec_umap,
        *game_packages.CLASSES,
        *generic_unreal_importer.CLASSES,
        *generic_unreal_animations.CLASSES,
        *generic_sequences.CLASSES,
        *remake_static_mesh.CLASSES,
        *crisis_core_static_mesh.CLASSES,
        *crisis_core_animations.CLASSES,
        *kingdom_hearts_0_2_static_mesh.CLASSES,
        *kingdom_hearts_iii_static_mesh.CLASSES,
        *kdi_nodetree.CLASSES,
        mec_importer.FF7R_REBIRTH_FH_import_mec_umap,
        z_fighting.MESH_OT_find_opposite_faces,
        *ui_operators.CLASSES,
        *ui_mouth_rig.CLASSES,
        *ui_ik_rig.CLASSES,
        *ui_light_attenuation.CLASSES,
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
        generic_unreal_importer._load_versions()
        for cls in classes:
            _register_class(cls)
        ui_preferences.ensure_generic_unreal_profiles()
        kdi_nodetree.register_add_menu()
        package_browser.register_runtime_properties()
        package_browser.register_shortcuts()
        conventional_map.register_runtime_properties()
        game_packages.register_runtime_properties()
        generic_sequences.register_runtime_properties()
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
    generic_profile_test.unregister()
    try:
        kdi_drivers.unregister()
    except Exception as exc:
        print(f"[Talisman reload WARNING] KDI cleanup failed: {exc}")
    try:
        kdi_nodetree.unregister_add_menu()
    except Exception as exc:
        print(f"[Talisman reload WARNING] KDI node-menu cleanup failed: {exc}")
    _remove_menu_callback(bpy.types.VIEW3D_MT_edit_armature, ui_menus.menu_func_edit_armature)
    _remove_menu_callback(bpy.types.VIEW3D_MT_object, ui_menus.menu_func_object)
    _remove_menu_callback(bpy.types.VIEW3D_MT_pose_context_menu, ui_menus.menu_func_pose_bone)
    _remove_menu_callback(bpy.types.TOPBAR_MT_file_import, ui_menus.menu_func_import)
    try:
        package_browser.unregister_shortcuts()
    except Exception as exc:
        print(f"[Talisman reload WARNING] Package-browser shortcut cleanup failed: {exc}")
    try:
        game_packages.unregister_runtime_properties()
    except Exception as exc:
        print(f"[Talisman reload WARNING] Package-browser cleanup failed: {exc}")
    try:
        conventional_map.unregister_runtime_properties()
    except Exception as exc:
        print(f"[Talisman reload WARNING] Conventional package-browser cleanup failed: {exc}")
    try:
        package_browser.unregister_runtime_properties()
    except Exception as exc:
        print(f"[Talisman reload WARNING] Mesh package-browser cleanup failed: {exc}")
    generic_sequences.unregister_runtime_properties()
    for cls in reversed(classes):
        _unregister_class(cls)
    _REGISTERED = False


_sqex_reload_cleanup = unregister


if __name__ == "__main__":
    register()
