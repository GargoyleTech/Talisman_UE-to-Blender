"""Headless smoke test for the shared mesh package browser."""

from __future__ import annotations

import os
import sys

import bpy


REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY not in sys.path:
    sys.path.insert(0, REPOSITORY)

bpy.ops.preferences.addon_enable(module="addon")

from addon.games import package_browser


state = package_browser.make_state(
    "Test meshes", initial_directory="End/Content", file_icon="MESH_DATA"
)
paths = [
    "End/Content/Characters/Cloud/Cloud_1.uasset",
    "End/Content/Characters/Cloud/Cloud_2.uasset",
    "End/Content/Props/Chair.uasset",
]
package_browser.activate(bpy.context, state, paths)
browser = bpy.context.window_manager.ff7r_package_asset_browser

assert [entry.display_name for entry in browser.entries] == ["Characters", "Props"]
bpy.ops.wm.ff7r_package_asset_folder(
    virtual_path="End/Content/Characters/Cloud"
)
assert [entry.display_name for entry in browser.entries] == [
    "Cloud_1.uasset", "Cloud_2.uasset"
]

bpy.ops.wm.ff7r_package_asset_selection(mode="SELECT")
assert package_browser.selected_paths(bpy.context, state) == paths[:2]

browser.filter_text = "Props Chair"
assert [entry.virtual_path for entry in browser.entries] == [paths[2]]
bpy.ops.wm.ff7r_package_asset_selection(mode="INVERT")
assert package_browser.selected_paths(bpy.context, state) == paths

bpy.ops.wm.ff7r_package_asset_selection(mode="CLEAR")
assert package_browser.selected_paths(bpy.context, state) == [paths[2]]

remake_properties = {
    prop.identifier
    for prop in bpy.ops.import_scene.ff7r_remake_skeletal_mesh_game_packages
    .get_rna_type().properties
}
assert {
    "attachment_sockets",
    "import_kdi",
    "setup_naive_ik",
    "create_variant_bone_collections",
}.issubset(remake_properties), sorted(remake_properties)
assert "create_limbal_bone" not in remake_properties

print("MESH_PACKAGE_BROWSER_OK")
