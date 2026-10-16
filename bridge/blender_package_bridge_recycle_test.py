"""Verify package-session memory cleanup can transparently recycle its gargoyle."""

import bpy
from talisman import game_packages


UMAP = "End/Content/Level/Game/Field/2350-GOLDS/Layout/2350-GOLDS_SQGhost_Terrain_Strip.umap"

if "talisman" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="talisman")
prefs = bpy.context.preferences.addons["talisman"].preferences
prefs.rebirth_install_root = r"G:\SteamLibrary\steamapps\common\FINAL FANTASY VII REBIRTH"
prefs.oodle_dll = r"G:\Games\Final Fantasy VII - Remake Intergrade\Engine\Binaries\ThirdParty\Oodle\Win64\oo2core_7_win64.dll"
prefs.rebirth_usmap_path = r"C:\Users\Ghouls\Downloads\Rebirth_v05.usmap"

session = game_packages.PackageAssetSession(
    bpy.path.abspath(prefs.rebirth_install_root),
    bpy.path.abspath(prefs.oodle_dll),
    bpy.path.abspath(prefs.rebirth_usmap_path),
)
# Force the fallback path without requiring a multi-gigabyte test allocation.
session.UMAP_RESTART_WORKING_SET_MB = 1
with session:
    first_pid = session.process.pid
    import_names, actor_payload = session.umap_data(UMAP)
    memory = session.release_batch_memory()
    second_pid = session.process.pid
    followup_names = session.import_names(UMAP)

print("PACKAGE_RECYCLE_FIRST_PID", first_pid)
print("PACKAGE_RECYCLE_SECOND_PID", second_pid)
print("PACKAGE_RECYCLE_MEMORY", memory)
print("PACKAGE_RECYCLE_IMPORT_NAMES", len(import_names), len(followup_names))
print("PACKAGE_RECYCLE_ACTORS", len(actor_payload.get("actors") or []))
if first_pid == second_pid or not import_names or len(import_names) != len(followup_names):
    raise SystemExit("Package bridge recycling test failed.")
