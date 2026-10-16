"""Import two Remake StaticMeshes through the shared checked browser state."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


ASSETS = (
    "End/Content/GameContents/Effect/Character/Player/PC0000_Cloud/Model/"
    "FX_PC0000_Cylinder_01_M.uasset",
    "End/Content/GameContents/Environment/0Highway/Model/"
    "BuildingFactory_13_0Highway.uasset",
)


def main() -> None:
    repository_root, game_root, usmap_path = sys.argv[sys.argv.index("--") + 1:]
    sys.path.insert(0, str(Path(repository_root).resolve()))
    assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}

    from addon.games import package_browser
    from addon.games.remake.importers import static_mesh

    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.remake_install_root = game_root
    preferences.oodle_dll = ""
    preferences.remake_usmap_path = usmap_path

    indexed = static_mesh.refresh_static_mesh_index(bpy.context)
    assert all(path in indexed for path in ASSETS)
    package_browser.activate(
        bpy.context, static_mesh._STATIC_MESH_BROWSER, indexed
    )
    static_mesh._STATIC_MESH_BROWSER["selected"].update(ASSETS)

    result = bpy.ops.import_scene.ff7r_remake_static_mesh_game_packages(
        "EXEC_DEFAULT"
    )
    assert result == {"FINISHED"}, result
    imported = {
        obj.get("ff7r_virtual_path")
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
    }
    assert set(ASSETS).issubset(imported), imported
    print("REMAKE_MESH_MULTISELECT_OK")


if __name__ == "__main__":
    main()
