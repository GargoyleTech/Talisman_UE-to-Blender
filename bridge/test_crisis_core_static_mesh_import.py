"""Blender background smoke test for Crisis Core Reunion StaticMesh import."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import bpy


DEFAULT_ASSET = (
    "CCFF7R/Content/Fair/Map/00_Common/Prop/00_Prop/House/Mesh/"
    "S_en_ban2_02_MP_HouseA.uasset"
)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) < 2:
        raise SystemExit(
            "Usage: blender --background --python test_crisis_core_static_mesh_import.py -- "
            "GAME_ROOT USMAP [ASSET_PATH]"
        )
    game_root, usmap_path = args[:2]
    asset_path = args[2] if len(args) > 2 else DEFAULT_ASSET

    addon_directory = Path(__file__).resolve().parent.parent / "addon"
    spec = importlib.util.spec_from_file_location(
        "ff7r_rebirth_tools",
        addon_directory / "__init__.py",
        submodule_search_locations=[str(addon_directory)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules["ff7r_rebirth_tools"] = addon
    spec.loader.exec_module(addon)
    from ff7r_rebirth_tools.games.crisis_core.profile import PROFILE
    from ff7r_rebirth_tools.games.rebirth.importers.packages import (
        PackageAssetSession,
        import_static_mesh_asset,
    )

    addon.register()
    with PackageAssetSession(game_root, "", usmap_path, profile=PROFILE) as session:
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
        "hasColors": mesh.color_attributes.get("Color") is not None,
        "virtualPath": obj.get("ff7r_virtual_path"),
    }
    assert result["vertices"] == 10441, result
    assert result["triangles"] == 12042, result
    assert result["uvLayers"] == ["Coordinate0", "Coordinate1"], result
    assert len(result["materials"]) == 3, result
    assert result["hasCustomNormals"] and result["hasTangents"], result
    assert not result["hasColors"], result
    assert result["virtualPath"] == asset_path, result
    print("CRISIS_CORE_STATIC_MESH_IMPORT_RESULT=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
