"""Regression for Rebirth UMAP references whose case differs from mounted files.

Run in background Blender with -- GAME_ROOT OODLE_DLL USMAP [REPORT_JSON].
Exercises the registered package UMAP operator against real G-Bike packages.
"""

from pathlib import Path
from unittest.mock import patch
import json
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
bpy.ops.preferences.addon_enable(module="addon")
from addon.formats.ue_map import map_import
from addon.games.rebirth.importers import packages


args = sys.argv[sys.argv.index("--") + 1:]
if len(args) < 3:
    raise SystemExit("Expected GAME_ROOT OODLE_DLL USMAP [REPORT_JSON]")
game_root, oodle, usmap = args[:3]
prefs = bpy.context.preferences.addons["addon"].preferences
prefs.rebirth_install_root = game_root
prefs.oodle_dll = oodle
prefs.rebirth_usmap_path = usmap

maps = [
    f"End/Content/Level/Game/Field/2353-GBIKE/Layout/2353-GBIKE_{role}.umap"
    for role in ("Terrain", "Gimmick")
]
# Supply the selected maps without indexing every map in the installed game.
packages._VIRTUAL_UMAPS = maps[:]
packages._UMAP_BROWSER["paths"] = maps[:]
created_total = 0
referenced_assets = set()
map_results = []
original_import = map_import.import_map_entries


def check_map(data, source_name, **options):
    global created_total
    referenced_assets.update(
        path for path in map_import.collect_package_static_mesh_paths_for_import(data)
        if "/Environment/Minigame/Model/" in path
    )
    created, missing = original_import(data, source_name, **options)
    map_results.append((source_name, created, missing))
    created_total += created
    return created, missing


with patch.object(map_import, "import_map_entries", side_effect=check_map):
    for path in maps:
        result = bpy.ops.import_scene.ff7r_rebirth_mec_game_packages(
            "EXEC_DEFAULT", virtual_path=path,
            import_models=True, import_textures=False,
            import_lights=False, import_light_probes=False,
            import_splines=False, recursive_import=False,
            offset_opposite_faces=False,
        )
        assert result == {"FINISHED"}, (path, result)
assert len(map_results) == len(maps), map_results
for source_name, created, missing in map_results:
    assert not missing, (source_name, sorted(missing))
    assert created > 0, source_name
assert len(referenced_assets) == 35, sorted(referenced_assets)

canonical_path = "End/Content/Environment/MiniGame/Model/GBIKE_Board_01A.uasset"
with packages.PackageAssetSession(game_root, oodle, usmap, import_textures=False) as session:
    canonical = session.static_mesh(canonical_path)
    lowercase = session.static_mesh(canonical_path.lower())
    assert canonical["vertexCount"] == lowercase["vertexCount"] == 7056
    for stream in ("positions", "normals", "tangents", "indices", "uvChannels"):
        assert np.array_equal(np.asarray(canonical[stream]), np.asarray(lowercase[stream])), stream
    # Case-insensitive lookup must still reject a genuinely absent asset.
    try:
        session.request({"action": "static_mesh", "assetPath": canonical_path.replace(
            "GBIKE_Board_01A", "GBIKE_Missing_Path_Case_Fixture")}, report_errors=False)
    except RuntimeError as error:
        assert "no game file" in str(error).lower(), error
    else:
        raise AssertionError("An absent mesh resolved to an unrelated asset")

report = {
    "blender": bpy.app.version_string,
    "maps": maps,
    "caseMismatchedAssets": len(referenced_assets),
    "createdObjects": created_total,
    "missingAssets": 0,
    "lowercaseGeometryMatches": True,
    "absentAssetRejected": True,
}
if len(args) > 3:
    Path(args[3]).write_text(json.dumps(report, indent=2), encoding="utf-8")
print("REBIRTH_PACKAGE_PATH_CASE_OK", json.dumps(report))
