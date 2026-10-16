"""Smoke-test combined MEC and actor/light package UMAP import."""

import bpy
from talisman import game_packages


UMAP = "End/Content/Level/Game/Field/2350-GOLDS/Layout/2350-GOLDS_SQGhost_Terrain_Strip.umap"

if "talisman" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="talisman")
prefs = bpy.context.preferences.addons["talisman"].preferences
prefs.rebirth_install_root = r"G:\SteamLibrary\steamapps\common\FINAL FANTASY VII REBIRTH"
prefs.oodle_dll = r"G:\Games\Final Fantasy VII - Remake Intergrade\Engine\Binaries\ThirdParty\Oodle\Win64\oo2core_7_win64.dll"
prefs.rebirth_usmap_path = r"C:\Users\Ghouls\Downloads\Rebirth_v05.usmap"

objects_before = set(bpy.context.scene.objects)
result = bpy.ops.import_scene.ff7r_rebirth_mec_game_packages(
    "EXEC_DEFAULT",
    virtual_path=UMAP,
    import_textures=False,
    import_actors=True,
    recursive_import=False,
)
created_objects = set(bpy.context.scene.objects) - objects_before
lights = [obj for obj in created_objects if obj.type == "LIGHT"]
print("PACKAGE_UMAP_RESULT", result)
print("PACKAGE_UMAP_LIGHTS", len(lights))
print("PACKAGE_UMAP_CREATED_OBJECTS", len(created_objects))
if result != {"FINISHED"} or len(lights) < 3 or not created_objects:
    raise SystemExit("Combined package UMAP smoke test failed.")
