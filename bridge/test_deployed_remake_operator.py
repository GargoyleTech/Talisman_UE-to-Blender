"""Smoke-test the installed Remake StaticMesh operator in background Blender."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


ASSET = (
    "End/Content/GameContents/Environment/0Highway/Model/"
    "BuildingFactory_13_0Highway.uasset"
)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 3:
        raise SystemExit(
            "Usage: blender --background --python test_deployed_remake_operator.py -- "
            "ADDONS_DIRECTORY GAME_ROOT USMAP"
        )
    addons_directory, game_root, usmap_path = args
    sys.path.insert(0, str(Path(addons_directory).resolve()))

    enabled = bpy.ops.preferences.addon_enable(module="ff7r_rebirth_tools")
    assert enabled == {"FINISHED"}, enabled
    from ff7r_rebirth_tools.games.remake.importers import static_mesh

    preferences = bpy.context.preferences.addons["ff7r_rebirth_tools"].preferences
    preferences.remake_install_root = game_root
    preferences.remake_oodle_dll = ""
    preferences.remake_usmap_path = usmap_path
    result = bpy.ops.import_scene.ff7r_remake_static_mesh_game_packages(
        "EXEC_DEFAULT", virtual_path=ASSET
    )
    assert result == {"FINISHED"}, result
    obj = bpy.context.active_object
    summary = {
        "indexedStaticMeshes": len(static_mesh._VIRTUAL_STATIC_MESHES),
        "indexSource": static_mesh._MESH_CACHE_SOURCE,
        "name": obj.name,
        "vertices": len(obj.data.vertices),
        "triangles": len(obj.data.polygons),
        "uvLayers": [layer.name for layer in obj.data.uv_layers],
    }
    assert summary["indexedStaticMeshes"] == 15105, summary
    assert summary["vertices"] == 3506, summary
    assert summary["triangles"] == 2936, summary
    assert len(summary["uvLayers"]) == 4, summary
    print("DEPLOYED_REMAKE_OPERATOR_RESULT=" + json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
