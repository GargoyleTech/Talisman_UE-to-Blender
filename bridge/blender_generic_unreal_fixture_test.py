"""Verify unlinked material inventories and neutral geometry/skeleton behavior."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.core.blender.skeletons import _bones_from_gargoyle, build_armature_from_bones
from addon.formats.mec.parser import get_untextured_mec_material
from addon.formats.unreal_mesh.materials import build_material, _match_parameter_node
from addon.formats.unreal_mesh import importer
from addon.games.crisis_core.materials import build_material as build_crisis_core_material
from addon.games.kingdom_hearts.materials import build_material as build_kingdom_hearts_material
from addon.games.rebirth.importers import packages
from addon.games.remake.materials import build_material as build_remake_material


class Images:
    def __init__(self, source):
        self.cache_namespace = source

    def __call__(self, path):
        if "Missing" in path:
            return None
        return bpy.data.images.new("Fixture", width=2, height=2)


data = {"type": "MaterialInstanceConstant", "textures": [
    {"path": "/Game/First/Duplicate.Duplicate", "labels": ["Albedo"]},
    {"path": "/Game/Second/Duplicate.Duplicate", "labels": []},
    {"path": "/Game/Missing.Missing", "labels": ["Mask"]},
]}
first = build_material("SharedName", "/Game/Shared.Shared", data, Images("source-a"))
second = build_material("SharedName", "/Game/Shared.Shared", data, Images("source-b"))
assert first != second
assert build_material("SharedName", "/Game/Shared.Shared", data, Images("source-a")) == first
assert len(first.node_tree.links) == 1  # Default surface, with no texture links.
assert first.node_tree.links[0].from_node.type == "BSDF_PRINCIPLED"
textures = [node for node in first.node_tree.nodes if node.type == "TEX_IMAGE"]
assert len(textures) == 3
assert sum(node.image is not None for node in textures) == 2
assert textures[-1].get("ue_texture_unavailable")
assert textures[-1].label == "Mask"
assert len({node["ue_texture_path"] for node in textures}) == 3


class PbrImages(Images):
    def __init__(self):
        super().__init__("pbr-source")
        self.pbr_mapping = {
            "albedo": ["ColorPrimary", "ColorFallback"],
            "normal": "Normal",
            "metalness": [
                {"parameter": "AbsentMetal", "channel": "R"},
                {"parameter": "AO_Rough_Metal", "channel": "B"},
            ],
            "roughness": [{"parameter": "AO_Rough_Metal", "channel": "G"}],
            "alpha": [{"parameter": "AO_Rough_Metal", "channel": "A"}],
            "emission": ["AbsentEmission", "EmissionColor", "ColorFallback"],
        }


pbr = build_material("PbrFixture", "/Game/Pbr.Pbr", {"textures": [
    {"path": "/Game/ColorPrimary.ColorPrimary", "labels": ["ColorPrimary"]},
    {"path": "/Game/ColorFallback.ColorFallback", "labels": ["ColorFallback"]},
    {"path": "/Game/Normal.Normal", "labels": ["Normal"]},
    {"path": "/Game/AO_Rough_Metal.AO_Rough_Metal", "labels": ["AO_Rough_Metal"]},
    {"path": "/Game/Emission.Emission", "labels": ["EmissionColor"]},
]}, PbrImages())
pbr_node = next(node for node in pbr.node_tree.nodes if node.name == "Profile PBR")
assert pbr_node.inputs["Base Color"].is_linked
assert pbr_node.inputs["Base Color"].links[0].from_node.label == "ColorPrimary"
assert abs(pbr_node.inputs["IOR"].default_value - 1.3) < 1e-6
assert pbr_node.inputs["Normal"].is_linked
assert pbr_node.inputs["Metallic"].is_linked
assert pbr_node.inputs["Roughness"].is_linked
assert pbr_node.inputs["Alpha"].is_linked
assert pbr_node.inputs["Metallic"].links[0].from_socket.name == "Blue"
assert pbr_node.inputs["Roughness"].links[0].from_socket.name == "Green"
assert pbr_node.inputs["Alpha"].links[0].from_socket.name == "Alpha"
assert pbr_node.inputs["Emission Color"].links[0].from_node.label == "EmissionColor"
assert pbr_node.inputs["Emission Color"].links[0].from_socket.name == "Color"
assert pbr_node.inputs["Emission Strength"].default_value == 1.0
assert pbr.get("ue_pbr_mapping")
assert not first.node_tree.nodes["Profile PBR"].inputs["Emission Color"].is_linked
assert first.node_tree.nodes["Profile PBR"].inputs["Emission Strength"].default_value == 0.0


# Only asterisks are special; patterns must match the whole parameter name.
parameter_nodes = {name: object() for name in (
    "basecolor01", "basecolor", "body_normal_map", "mask[0]?", "mask0x", "a.b",
)}
for pattern, expected in (
    ("basecolor", "basecolor"),
    ("basecolor*", "basecolor01"),
    ("*color01", "basecolor01"),
    ("*normal*", "body_normal_map"),
    ("body*map", "body_normal_map"),
    ("base**color*", "basecolor01"),
    ("*", "basecolor01"),
    ("mask[0]?*", "mask[0]?"),
    ("a.*", "a.b"),
    ("base*01*", "basecolor01"),
    ("color", None),
    ("normal*", None),
    ("basecolor?", None),
    ("*missing*", None),
):
    assert _match_parameter_node(parameter_nodes, pattern) is parameter_nodes.get(expected), pattern

# Exercise profile priority, aliases, case/whitespace normalization, legacy
# strings, and per-match scalar channels through the real material graph.
wildcard_images = PbrImages()
wildcard_images.pbr_mapping = {
    "albedo": ["Absent*", "  cOlOr*  ", "ColorFallback"],
    "normal": "*oRmAl*",
    "metalness": [{"parameter": "AO*Metal", "channel": "B"}],
    "roughness": [{"parameter": "*Rough*", "channel": "G"}],
    "alpha": [{"parameter": "*", "channel": "A"}],
    "emission": ["Absent*", "  cOlOr*  ", "ColorFallback"],
}
wildcard = build_material("WildcardFixture", "/Game/Wildcard.Wildcard", {"textures": [
    {"path": "/Game/Primary.Primary", "labels": ["UnrelatedAlias", "ColorPrimary"]},
    {"path": "/Game/Fallback.Fallback", "labels": ["ColorFallback"]},
    {"path": "/Game/Normal.Normal", "labels": ["Normal"]},
    {"path": "/Game/ORM.ORM", "labels": ["AO_Rough_Metal"]},
]}, wildcard_images)
wildcard_node = wildcard.node_tree.nodes["Profile PBR"]
assert wildcard_node.inputs["Base Color"].links[0].from_node.label == "UnrelatedAlias, ColorPrimary"
assert wildcard_node.inputs["Normal"].links[0].from_node.inputs["Color"].links[0].from_node.label == "Normal"
assert wildcard_node.inputs["Metallic"].links[0].from_socket.name == "Blue"
assert wildcard_node.inputs["Roughness"].links[0].from_socket.name == "Green"
assert wildcard_node.inputs["Alpha"].links[0].from_node.label == "UnrelatedAlias, ColorPrimary"
assert wildcard_node.inputs["Alpha"].links[0].from_socket.name == "Alpha"
assert wildcard_node.inputs["Emission Color"].links[0].from_node.label == "UnrelatedAlias, ColorPrimary"
assert wildcard_node.inputs["Emission Strength"].default_value == 1.0
assert json.loads(wildcard["ue_texture_warnings"]) == []

wildcard_images.pbr_mapping = {"albedo": ["Missing*"], "emission": ["MissingEmission*"]}
unmatched = build_material("UnmatchedFixture", "/Game/Unmatched.Unmatched", data, wildcard_images)
assert len(unmatched.node_tree.links) == 1
assert unmatched.node_tree.links[0].from_node.type == "BSDF_PRINCIPLED"
assert not unmatched.node_tree.nodes["Profile PBR"].inputs["Emission Color"].is_linked
assert unmatched.node_tree.nodes["Profile PBR"].inputs["Emission Strength"].default_value == 0.0
assert any("'Missing*'" in warning for warning in json.loads(unmatched["ue_texture_warnings"]))


def _principled_ior(material):
    return next(
        node for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeBsdfPrincipled"
    ).inputs["IOR"].default_value


empty_image_loader = lambda _path: None
assert abs(_principled_ior(build_remake_material(
    "IOR Remake", "/Game/IOR.Remake", {}, empty_image_loader
)) - 1.3) < 1e-6
assert abs(_principled_ior(build_crisis_core_material(
    "IOR Crisis Core", "/Game/IOR.CrisisCore", {}, empty_image_loader
)) - 1.3) < 1e-6
assert abs(_principled_ior(build_kingdom_hearts_material(
    "IOR Kingdom Hearts", "/Game/IOR.KingdomHearts", {}, empty_image_loader
)) - 1.3) < 1e-6
assert abs(_principled_ior(get_untextured_mec_material()) - 1.3) < 1e-6
assert abs(_principled_ior(packages._static_mesh_material(
    "IOR Rebirth Placeholder", "/Game/IOR.Rebirth", "ior-fixture"
)) - 1.3) < 1e-6

# Generic names must not trigger the existing Square Enix deformation rules,
# and parent scale must contribute to child bind-pose positions.
bones = _bones_from_gargoyle({"bones": [
    {"name": "C_KDIRoot", "parentIndex": -1, "translation": [0, 0, 0], "scale": [2, 2, 2]},
    {"name": "ChildKdi", "parentIndex": 0, "translation": [10, 0, 0]},
]})
armature = build_armature_from_bones(bpy.context, "GenericFixture", bones, [], game_features=False)
assert all(bone.use_deform for bone in armature.data.bones)
assert (armature.data.bones["ChildKdi"].head_local - Vector((0.2, 0, 0))).length < 1e-5
legacy = build_armature_from_bones(bpy.context, "LegacyFixture", bones, [])
assert not legacy.data.bones["C_KDIRoot"].use_deform
assert not legacy.data.bones["ChildKdi"].use_deform
assert (legacy.data.bones["ChildKdi"].head_local - Vector((0.1, 0, 0))).length < 1e-5

payload = {
    "name": "Fixture", "positions": [[0, 0, 0], [10, 0, 0], [0, 0, 10]],
    "normals": [[0, -1, 0]] * 3, "indices": [0, 1, 2],
    "uvChannels": [[[0, 0], [1, 0], [0, 1]]], "sections": [],
    "boneNames": ["C_KDIRoot", "ChildKdi"], "weights": [[[0, 1.0]]] * 3,
}
obj, vertices, influences = packages.import_skeletal_mesh_asset(
    bpy.context, payload, "/Game/Fixture", armature_obj=armature, game_features=False,
)
assert vertices == 3 and influences == 3
assert obj.parent == armature
assert not next(modifier for modifier in obj.modifiers if modifier.type == "ARMATURE").use_deform_preserve_volume
assert not any("limbal" in key.lower() for key in obj.keys())
assert not obj.constraints
assert len(importer._VERSION_ITEMS) > 28

# Verify clean re-registration after development reloads as well.
addon.unregister()
addon.register()
assert bpy.ops.import_scene.sqex_generic_unreal_mesh.get_rna_type()
addon.unregister()
print("GENERIC_UNREAL_FIXTURE_OK")
