"""Run with Blender --background --factory-startup --python this_file."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.formats.unreal_package.mesh_import import import_skeletal_mesh_asset
from addon.games.rebirth.materials import rmi_surface


class Session:
    texture_namespace = "rmi-uv-fixture"

    def __init__(self, variant):
        self.variant = variant

    def material_asset_path(self, path):
        return path

    def material_instance(self, path):
        return {"properties": [{"name": "Parent", "value": {
            "ObjectPath": "/Game/Materials/" + self.variant}}]}

    def __call__(self, path):
        return None


def assert_uvs(material, count):
    for index in range(count):
        node = material.node_tree.nodes[f"UV{index}"]
        assert node.uv_map == f"Coordinate{index}", (material.name, node.name, node.uv_map)
    texture = material.node_tree.nodes.get("TEX_WideOcclusion")
    if texture is not None and texture.bl_idname == "ShaderNodeTexImage":
        link = texture.inputs["Vector"].links[0]
        assert link.from_node == material.node_tree.nodes["UV1"]
        if not texture.mute:
            assert not link.from_node.mute


masters, _, ground_truth = rmi_surface._module_set()
for profile, count in (("surface", 4), ("eye", 2), ("hair", 3)):
    master = masters[profile]
    assert master.ROLE_UV["WideOcclusion"] == 1
    # Reproduce a saved template authored without an active mesh.
    bpy.context.view_layer.objects.active = None
    stale = master.build()
    assert stale.node_tree.nodes["UV1"].uv_map == ""
    template = rmi_surface._ensure_master(master)
    assert_uvs(template, count)
    # Old templates already have the correct named UV nodes but put this
    # sampler on UV0 (through the base reroute in the surface profile).
    sampler = template.node_tree.nodes.get("TEX_WideOcclusion")
    if sampler is not None:  # Dedicated eye/hair graphs omit this slot.
        image = bpy.data.images.new("WideOcclusion " + profile, width=1, height=1)
        sampler.image = image
        template.node_tree.links.new(template.node_tree.nodes["UV0"].outputs["UV"], sampler.inputs["Vector"])
        template.node_tree.nodes["UV1"].mute = True
        assert rmi_surface._ensure_master(master) == template
        assert sampler.image == image
        assert_uvs(template, count)

    variant = next(name for name, switches in ground_truth.items()
                   if rmi_surface._master_for_switches(switches) is master)
    session = Session(variant)
    armature = bpy.data.objects.new("Active rig", bpy.data.armatures.new("Rig"))
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    payload = {
        "name": "RMI UV fixture", "positions": [[0, 0, 0], [1, 0, 0], [0, 0, 1]],
        "normals": [[0, -1, 0]] * 3, "indices": [0, 1, 2],
        "uvChannels": [[[0, 0], [1, 0], [0, 1]]] * 4,
        "weights": [[], [], []],
        "sections": [{"materialIndex": 0, "firstIndex": 0, "triangleCount": 1,
                      "materialName": profile, "materialPath": "/Game/Test/" + profile}],
    }
    obj, _, _ = import_skeletal_mesh_asset(
        bpy.context, payload, "/Game/Test/Mesh", material_session=session,
        material_builder=rmi_surface.build_material,
    )
    assert_uvs(obj.data.materials[0], count)
    assert obj.data.materials[0].name == profile, obj.data.materials[0].name
    assert not any(mat.name.startswith(profile + ".") for mat in bpy.data.materials)
    assert [layer.name for layer in obj.data.uv_layers] == [f"Coordinate{i}" for i in range(4)]
    # Reuse must preserve explicit maps even when another mesh is active.
    other = bpy.data.objects.new("Unrelated", bpy.data.meshes.new("Unrelated"))
    bpy.context.collection.objects.link(other)
    other.data.uv_layers.new(name="WrongUV")
    bpy.context.view_layer.objects.active = other
    cached = rmi_surface.build_material(profile, "/Game/Test/" + profile,
                                        session.material_instance(""), session)
    assert cached == obj.data.materials[0]
    assert_uvs(cached, count)
    material_count = len(bpy.data.materials)
    repeated, _, _ = import_skeletal_mesh_asset(
        bpy.context, payload, "/Game/Test/Mesh", material_session=session,
        material_builder=rmi_surface.build_material,
    )
    assert repeated.data.materials[0] == cached
    assert len(bpy.data.materials) == material_count, "Reimport created a placeholder"

    # Reproduce an old cached image sampler, preserving its image assignment.
    tree = cached.node_tree
    old = tree.nodes.get("TEX_WideOcclusion")
    if old is not None:
        if old.bl_idname != "ShaderNodeTexImage":
            tree.nodes.remove(old)
            old = tree.nodes.new("ShaderNodeTexImage")
            old.name = "TEX_WideOcclusion"
        old.image = image
        old.mute = False
        tree.links.new(tree.nodes["UV0"].outputs["UV"], old.inputs["Vector"])
        tree.nodes["UV1"].uv_map = "WrongUV"
        tree.nodes["UV1"].mute = True
        assert rmi_surface.build_material(profile, "/Game/Test/" + profile,
                                          session.material_instance(""), session) == cached
        assert old.image == image
        assert_uvs(cached, count)

# Unsupported shaders and failed builders still receive a named fallback.
for name in ("Unsupported", "Failed"):
    payload["sections"][0].update(materialName=name, materialPath="/Game/Test/" + name)

    def fallback_builder(*args):
        if name == "Failed":
            raise RuntimeError("Expected fixture failure")
        return None

    obj, _, _ = import_skeletal_mesh_asset(
        bpy.context, payload, "/Game/Test/Mesh", material_session=session,
        material_builder=fallback_builder,
    )
    assert obj.data.materials[0].name == name
    assert "sqex_rmi_variant" not in obj.data.materials[0]

print("RMI_UV_PASS: surface, eye, hair; WideOcclusion Coordinate1; saved/cache migration; material reuse; names; fallbacks")
