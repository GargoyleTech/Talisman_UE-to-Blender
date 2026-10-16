"""Blender smoke test for Crisis Core's named texture material builder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import bpy


def _parameter(name, value):
    return {
        "StructType": {
            "ParameterInfo": {"StructType": {"Name": name}},
            "ParameterValue": value,
        }
    }


def _material_data(rma_name: str):
    return {
        "properties": [
            {"name": "TextureParameterValues", "value": [
                _parameter("TextureAlbedo", {"StructType": {"ObjectPath": "/Game/T_Albedo.T_Albedo"}}),
                _parameter("TextureNormal", {"StructType": {"ObjectPath": "/Game/T_Normal.T_Normal"}}),
                _parameter("DetailNormal", {"StructType": {"ObjectPath": "/Game/T_Detail.T_Detail"}}),
                _parameter("TextureRMA", {"StructType": {"ObjectPath": f"/Game/{rma_name}.{rma_name}"}}),
                _parameter("TextureEmissive", {"StructType": {"ObjectPath": "/Game/T_Emissive.T_Emissive"}}),
            ]},
            {"name": "VectorParameterValues", "value": [
                _parameter("EmissiveColor", {"StructType": {"R": 0.47932, "G": 1.0, "B": 0.871367, "A": 0.0}}),
            ]},
            {"name": "ScalarParameterValues", "value": [
                _parameter("EmissiveInt", 2.0),
            ]},
        ]
    }


def main() -> None:
    addon_directory = Path(__file__).resolve().parent.parent / "addon"
    spec = importlib.util.spec_from_file_location(
        "talisman", addon_directory / "__init__.py",
        submodule_search_locations=[str(addon_directory)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules["talisman"] = addon
    spec.loader.exec_module(addon)
    from talisman.games.crisis_core.materials import build_material
    from talisman.games.crisis_core.profile import PROFILE
    from talisman.games.rebirth.importers.packages import (
        _game_asset_path_to_virtual_uasset,
    )

    assert _game_asset_path_to_virtual_uasset(
        "MaterialInstanceConstant'/Game/Character/MI_Test.MI_Test'", profile=PROFILE
    ) == "CCFF7R/Content/Character/MI_Test.uasset"

    images = {}

    def image_loader(path):
        if path not in images:
            image = bpy.data.images.new(path.rsplit("/", 1)[-1], 1, 1)
            image.pixels = (1.0, 0.5, 0.5, 1.0)
            images[path] = image
        return images[path]

    def labelled(tree, label):
        return next(node for node in tree.nodes if node.label == label)

    rmae = build_material("CC RMAE", "/Game/M_RMAE.M_RMAE", _material_data("T_Test_RMAE"), image_loader)
    tree = rmae.node_tree
    assert labelled(tree, "DetailNormal Map UV2").uv_map == "Coordinate1"
    assert labelled(tree, "TextureNormal Map invert DirectX green").operation == "SUBTRACT"
    assert labelled(tree, "DetailNormal Map invert DirectX green").operation == "SUBTRACT"
    assert labelled(tree, "RMAE alpha × EmissiveInt").inputs[1].default_value == 2.0
    assert tree.nodes["TextureAlbedo"].outputs["Color"].links
    assert tree.nodes["TextureRMA"].image.colorspace_settings.name == "Non-Color"
    assert labelled(tree, "TextureAlbedo × RMA ambient occlusion").inputs[1].links[0].from_node == tree.nodes["TextureAlbedo"]
    assert labelled(tree, "RMAE alpha × EmissiveInt").inputs[0].links[0].from_node == tree.nodes["TextureRMA"]
    assert tree.nodes["Principled BSDF"].inputs["Alpha"].links[0].from_node == tree.nodes["TextureAlbedo"]

    rma = build_material("CC RMA", "/Game/M_RMA.M_RMA", _material_data("T_Test_RMA"), image_loader)
    assert not any(node.label == "RMAE alpha × EmissiveInt" for node in rma.node_tree.nodes)
    print("CRISIS_CORE_MATERIAL_OK")


if __name__ == "__main__":
    main()
