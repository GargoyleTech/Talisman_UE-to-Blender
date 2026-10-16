"""Smoke-test the installed Crisis Core StaticMesh operator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


ASSET = (
    "CCFF7R/Content/Fair/Map/00_Common/Prop/00_Prop/House/Mesh/"
    "S_en_ban2_02_MP_HouseA.uasset"
)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 3:
        raise SystemExit(
            "Usage: blender --background --python test_deployed_crisis_core_operator.py -- "
            "ADDONS_DIRECTORY GAME_ROOT USMAP"
        )
    addons_directory, game_root, usmap_path = args
    sys.path.insert(0, str(Path(addons_directory).resolve()))
    enabled = bpy.ops.preferences.addon_enable(module="talisman")
    assert enabled == {"FINISHED"}, enabled

    from talisman.games.crisis_core.importers import static_mesh

    preferences = bpy.context.preferences.addons["talisman"].preferences
    preferences.crisis_core_install_root = game_root
    preferences.oodle_dll = ""
    preferences.crisis_core_usmap_path = usmap_path
    result = bpy.ops.import_scene.ff7r_crisis_core_static_mesh_game_packages(
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
        "materials": [material.name for material in obj.data.materials],
    }
    assert summary["indexedStaticMeshes"] == 8357, summary
    assert summary["vertices"] == 10441, summary
    assert summary["triangles"] == 12042, summary
    assert len(summary["uvLayers"]) == 2, summary
    assert len(summary["materials"]) == 3, summary
    print("DEPLOYED_CRISIS_CORE_OPERATOR_RESULT=" + json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
