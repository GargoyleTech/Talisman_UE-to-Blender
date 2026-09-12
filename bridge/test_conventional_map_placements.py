"""Blender smoke test for ordinary UE map mesh and light component placement."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import bpy


def main() -> None:
    addon_directory = Path(__file__).resolve().parent.parent / "addon"
    spec = importlib.util.spec_from_file_location(
        "ff7r_rebirth_tools",
        addon_directory / "__init__.py",
        submodule_search_locations=[str(addon_directory)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules["ff7r_rebirth_tools"] = addon
    spec.loader.exec_module(addon)
    from ff7r_rebirth_tools.formats.ue_map import map_import
    from ff7r_rebirth_tools.games.rebirth.importers import packages as shared_packages
    from ff7r_rebirth_tools.games.remake.profile import PROFILE as REMAKE_PROFILE

    assert shared_packages._game_asset_path_to_virtual_uasset(
        "End/Content/GameContents/Environment/1stAvenue/Model/Wall_40_1stAvenue.1",
        profile=REMAKE_PROFILE,
    ) == "End/Content/GameContents/Environment/1stAvenue/Model/Wall_40_1stAvenue.uasset"

    mesh = bpy.data.meshes.new("ConventionalMapTestMesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    static_ref = {
        "ObjectName": "StaticMesh'/Game/Test/ConventionalMapTestMesh.ConventionalMapTestMesh'",
        "ObjectPath": "/Game/Test/ConventionalMapTestMesh.ConventionalMapTestMesh",
    }
    skeletal_ref = {
        "ObjectName": "SkeletalMesh'/Game/Test/ConventionalMapCharacter.ConventionalMapCharacter'",
        "ObjectPath": "/Game/Test/ConventionalMapCharacter.ConventionalMapCharacter",
    }
    outer = {
        "ObjectName": "Object'/Game/Test/ConventionalMap.Actor'",
        "ObjectPath": "/Game/Test/ConventionalMap.Actor",
    }
    entries = [
        {
            "Type": "StaticMeshComponent",
            "Name": "Mesh",
            "Outer": outer,
            "Properties": {
                "StaticMesh": static_ref,
                "RelativeLocation": {"X": 100.0, "Y": 0.0, "Z": 0.0},
                "RelativeRotation": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0},
            },
        },
        {
            "Type": "PointLightComponent",
            "Name": "Point",
            "Outer": outer,
            "Properties": {
                "RelativeLocation": {"X": 0.0, "Y": 200.0, "Z": 0.0},
                "RelativeRotation": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0},
                "Intensity": 100.0,
            },
        },
        {
            "Type": "SkeletalMeshComponent",
            "Name": "Character",
            "Outer": outer,
            "Properties": {
                "SkeletalMesh": skeletal_ref,
                "RelativeLocation": {"X": 0.0, "Y": 0.0, "Z": 50.0},
                "RelativeRotation": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0},
            },
        },
        {
            "Type": "SpotLightComponent",
            "Name": "Spot",
            "Outer": outer,
            "Properties": {
                "RelativeLocation": {"X": 0.0, "Y": 0.0, "Z": 300.0},
                "RelativeRotation": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0},
                "Intensity": 100.0,
            },
        },
    ]
    skeletal_asset = map_import.SkeletalMeshDatablocks(
        mesh=mesh,
        armature=None,
        skeletal_mesh={"boneNames": [], "weights": [[], [], []]},
        virtual_path="End/Content/Test/ConventionalMapCharacter.uasset",
    )
    created, missing = map_import.import_map_entries(
        entries,
        "ConventionalMap.umap",
        exposure_mult=1.0,
        attenuation_radius_mult=1.0,
        static_mesh_resolver=lambda _path: mesh,
        skeletal_mesh_resolver=lambda _path: skeletal_asset,
    )
    assert created == 4, created
    assert not missing, missing
    assert {"Actor.Point", "Actor.Spot"} <= {item.name for item in bpy.data.lights}
    print("CONVENTIONAL_MAP_PLACEMENT_OK")


if __name__ == "__main__":
    main()
