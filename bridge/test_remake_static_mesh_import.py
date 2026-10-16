"""Blender background smoke test for Remake Intergrade package StaticMesh import."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import bpy


DEFAULT_ASSET = (
    "End/Content/GameContents/Environment/0Highway/Model/"
    "BuildingFactory_13_0Highway.uasset"
)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) < 3:
        raise SystemExit(
            "Usage: blender --background --python test_remake_static_mesh_import.py -- "
            "GAME_ROOT OODLE_DLL USMAP [ASSET_PATH]"
        )
    game_root, oodle_dll, usmap_path = args[:3]
    asset_path = args[3] if len(args) > 3 else DEFAULT_ASSET

    addon_directory = Path(__file__).resolve().parent.parent / "addon"
    spec = importlib.util.spec_from_file_location(
        "talisman",
        addon_directory / "__init__.py",
        submodule_search_locations=[str(addon_directory)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules["talisman"] = addon
    spec.loader.exec_module(addon)
    from talisman.games.remake.profile import PROFILE
    from talisman.games.rebirth.importers.packages import (
        PackageAssetSession,
        import_static_mesh_asset,
    )

    addon.register()
    with PackageAssetSession(
        game_root, oodle_dll, usmap_path, profile=PROFILE
    ) as session:
        static_mesh = session.static_mesh(asset_path)
    obj = import_static_mesh_asset(bpy.context, static_mesh, asset_path)
    mesh = obj.data
    result = {
        "name": obj.name,
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.polygons),
        "uvLayers": [layer.name for layer in mesh.uv_layers],
        "materials": [material.name for material in mesh.materials],
        "materialFaceCounts": dict(Counter(
            polygon.material_index for polygon in mesh.polygons
        )),
        "hasCustomNormals": mesh.has_custom_normals,
        "hasTangents": mesh.attributes.get("ff7r_tangent") is not None,
        "virtualPath": obj.get("ff7r_virtual_path"),
    }
    assert result["vertices"] == 3506, result
    assert result["triangles"] == 2936, result
    assert result["uvLayers"] == [
        "Coordinate0", "Coordinate1", "Coordinate2", "Coordinate3"
    ], result
    assert result["materials"] == ["Material_0", "Material_1"], result
    assert result["materialFaceCounts"] == {0: 2588, 1: 348}, result
    assert result["hasCustomNormals"] and result["hasTangents"], result
    assert result["virtualPath"] == asset_path, result
    print("REMAKE_STATIC_MESH_IMPORT_RESULT=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
