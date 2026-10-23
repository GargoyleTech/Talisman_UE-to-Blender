"""Generic inventories reuse images and aliases without changing shader connections."""

import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.formats.unreal_mesh.materials import build_material


class Images:
    def __init__(self, source="material-dedup"):
        self.cache_namespace = source
        self.calls = []
        self.shared = bpy.data.images.new("SharedFixture", width=2, height=2)
        self.normal = bpy.data.images.new("NormalFixture", width=2, height=2)
        self.volume = bpy.data.images.new("VolumeFixture", width=2, height=2)
        self.volume["ue_texture_layout"] = "VOLUME_ATLAS"
        self.texture_info = {}
        self.missing_available = False
        self.pbr_mapping = {
            "albedo": "ColorAlias",
            "normal": "Normal",
            "metalness": [{"parameter": "MetalAlias", "channel": "B"}],
            "roughness": [{"parameter": "RoughAlias", "channel": "G"}],
            "alpha": [{"parameter": "AlphaAlias", "channel": "A"}],
        }

    def __call__(self, path):
        self.calls.append(path.casefold())
        if "missing" in path.casefold() and not self.missing_available:
            self.texture_info[path.casefold()] = {
                "reason": "No stored pixels", "textureType": "TextureRenderTarget2D"}
            return None
        if "Normal" in path:
            return self.normal
        if "Volume" in path:
            return self.volume
        if "Other" in path:
            # A different image with the same name must remain a separate node.
            return bpy.data.images.new("SharedFixture", width=2, height=2)
        return self.shared


def texture_nodes(material):
    return [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]


images = Images()
inventory = {"textures": [
    {"path": "/Game/Shared.Shared", "labels": ["FirstAlias"]},
    {"path": "/game/shared.shared", "labels": ["ColorAlias", "FirstAlias"]},
    {"path": "/Game/SharedAlias.SharedAlias", "labels": ["MetalAlias", "RoughAlias", "AlphaAlias"]},
    {"path": "/Game/Normal.Normal", "labels": ["Normal"]},
    {"path": "/Game/Other/Shared.Shared", "labels": ["DistinctImage"]},
    {"path": "/Game/Missing.Missing", "labels": ["MissingA"]},
    {"path": "/game/missing.missing", "labels": ["MissingB"]},
    {"path": "/Game/SecondMissing.SecondMissing", "labels": []},
    {"path": "/Game/Volume.Volume", "labels": ["VolumeA"]},
    {"path": "/Game/VolumeAlias.VolumeAlias", "labels": ["VolumeB"]},
    {"path": "", "labels": ["Ignored"]},
]}
material = build_material("DedupFixture", "/Game/Dedup.Dedup", inventory, images)
textures = texture_nodes(material)
assert len(textures) == 6
assert len(images.calls) == 8
assert images.calls.count("/game/shared.shared") == 1
assert images.calls.count("/game/missing.missing") == 1
assert len({node.image.as_pointer() for node in textures if node.image}) == 4
shared = next(node for node in textures if node.image == images.shared)
assert json.loads(shared["ue_parameter_names"]) == [
    "FirstAlias", "ColorAlias", "MetalAlias", "RoughAlias", "AlphaAlias"]
assert shared["ue_texture_path"] == "/Game/Shared.Shared"
assert [tuple(node.location) for node in textures] == [
    (-1120, 0), (-840, 0), (-560, 0), (-280, 0), (-1120, -340), (-840, -340)]
volume = next(node for node in textures if node.image == images.volume)
assert volume.label == "Volume slice atlas: VolumeA, VolumeB"
assert volume["ue_texture_layout"] == "VOLUME_ATLAS"
missing = next(node for node in textures if node.get("ue_texture_path") == "/Game/Missing.Missing")
assert missing.image is None and missing["ue_texture_unavailable"]
assert json.loads(missing["ue_parameter_names"]) == ["MissingA", "MissingB"]
assert len(json.loads(material["ue_texture_warnings"])) == 2

pbr = material.node_tree.nodes["Profile PBR"]
assert pbr.inputs["Base Color"].links[0].from_node == shared
assert pbr.inputs["Alpha"].links[0].from_node == shared
assert pbr.inputs["Normal"].links[0].from_node.inputs["Color"].links[0].from_node.image == images.normal
for slot, channel in (("Metallic", "Blue"), ("Roughness", "Green")):
    link = pbr.inputs[slot].links[0]
    assert link.from_socket.name == channel
    assert link.from_node.inputs["Color"].links[0].from_node == shared

# Preserve inventory order for wildcard matching even when a late alias is
# merged into the first image node (before another image in the node list).
images.pbr_mapping = {"albedo": "Candidate*"}
wildcard = build_material("WildcardDedup", "/Game/WildcardDedup.WildcardDedup", {"textures": [
    {"path": "/Game/Shared.Shared", "labels": ["Unrelated"]},
    {"path": "/Game/Normal.Normal", "labels": ["CandidateFirst"]},
    {"path": "/Game/SharedAlias.SharedAlias", "labels": ["CandidateLater"]},
]}, images)
assert len(texture_nodes(wildcard)) == 2
assert wildcard.node_tree.nodes["Profile PBR"].inputs["Base Color"].links[0].from_node.image == images.normal

# Simulate a material generated by an older importer, including links from
# duplicate Color/Alpha outputs. Reimport must reuse the material and its graph.
tree = material.node_tree
shared_name = shared.name
duplicate = tree.nodes.new("ShaderNodeTexImage")
duplicate.image = shared.image
duplicate["ue_texture_path"] = "/Game/SharedAlias.SharedAlias"
duplicate["ue_parameter_names"] = json.dumps(["LegacyColor", "ColorAlias"])
tree.links.new(duplicate.outputs["Color"], pbr.inputs["Base Color"])
tree.links.new(duplicate.outputs["Alpha"], pbr.inputs["Alpha"])
missing_duplicate = tree.nodes.new("ShaderNodeTexImage")
missing_duplicate["ue_texture_path"] = "/GAME/MISSING.MISSING"
missing_duplicate["ue_parameter_names"] = json.dumps(["LegacyMissing"])
reused = build_material("DedupFixture", "/Game/Dedup.Dedup", inventory, images)
assert reused == material
assert len(texture_nodes(material)) == 6
assert pbr.inputs["Base Color"].links[0].from_node == shared
assert pbr.inputs["Alpha"].links[0].from_node == shared
assert shared.name == shared_name
assert "LegacyColor" in json.loads(shared["ue_parameter_names"])
assert "LegacyMissing" in json.loads(missing["ue_parameter_names"])
assert len([node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"]) == 1

# Later resolution of different unavailable paths to the same image must also
# consolidate, even though the earlier import could only compare paths.
late = Images("late-resolution")
late_material = build_material("LateFixture", "/Game/Late.Late", {"textures": [
    {"path": "/Game/MissingOne", "labels": ["One"]},
    {"path": "/Game/MissingTwo", "labels": ["Two"]},
]}, late)
assert len(texture_nodes(late_material)) == 2
late.missing_available = True
build_material("LateFixture", "/Game/Late.Late", {}, late)
assert len(texture_nodes(late_material)) == 1
assert json.loads(texture_nodes(late_material)[0]["ue_parameter_names"]) == ["One", "Two"]

# User-authored UVs, sampling settings, animation timing, and untagged nodes
# remain distinct when the existing material is reused.
for kind in ("uv", "interpolation", "mapping", "frames", "manual"):
    custom = tree.nodes.new("ShaderNodeTexImage")
    custom.image = shared.image
    if kind != "manual":
        custom["ue_texture_path"] = shared["ue_texture_path"]
        custom["ue_parameter_names"] = json.dumps([kind])
    if kind == "uv":
        uv = tree.nodes.new("ShaderNodeUVMap")
        uv.uv_map = "UV2"
        tree.links.new(uv.outputs["UV"], custom.inputs["Vector"])
    elif kind == "interpolation":
        custom.interpolation = "Closest"
    elif kind == "mapping":
        custom.texture_mapping.scale = (2, 2, 2)
    elif kind == "frames":
        custom.image_user.frame_offset = 2
    tree.links.new(custom.outputs["Color"], pbr.inputs["Emission Color"])
    before = len(texture_nodes(material))
    build_material("DedupFixture", "/Game/Dedup.Dedup", inventory, images)
    assert len(texture_nodes(material)) == before, kind
    assert pbr.inputs["Emission Color"].links[0].from_node == custom, kind

print("GENERIC_MATERIAL_DEDUP_OK", flush=True)
