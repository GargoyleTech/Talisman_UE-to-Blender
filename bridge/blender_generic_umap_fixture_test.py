"""Check generic map parenting, sharing, material overrides, skinning, and instances."""

from collections import Counter
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.formats.unreal_mesh import maps
from addon.formats.ue_map import map_import


def reference(path):
    return {"ObjectPath": path, "ObjectName": f"Object'{path}'"}


def entry(kind, name, actor, **props):
    return {"Type": kind, "Name": name, "Outer": reference(f"/Game/Map.Map:PersistentLevel.{actor}"), "Properties": props}


mesh_payload = {
    "name": "Fixture", "positions": [[0, 0, 0], [10, 0, 0], [0, 0, 10]],
    "normals": [[0, 1, 0]] * 3, "indices": [0, 1, 2],
    "uvChannels": [[[0, 0], [1, 0], [0, 1]]],
    "sections": [{"materialIndex": 0, "firstIndex": 0, "triangleCount": 1,
                  "materialName": "FixtureBase", "materialPath": "/Game/Base.Base"}],
    "boneNames": ["Root"], "weights": [[[0, 1.0]]] * 3,
    "inlineSkeleton": {"bones": [{"name": "Root", "parentIndex": -1}]},
}
static = reference("/Game/Mesh.Mesh")
skeletal = reference("/Game/Rig.Rig")
override = [reference("/Game/Override.Override")]
parent = reference("/Game/Map.Map:PersistentLevel.Parent.Root")
entries = [
    entry("StaticMeshComponent", "Child", "Parent", StaticMesh=static, AttachParent=parent,
          RelativeLocation={"X": 100}, OverrideMaterials=override),
    entry("StaticMeshComponent", "Mesh", "Other", StaticMesh=static, RelativeLocation={"X": 300}),
    entry("SkeletalMeshComponent", "Rig", "RigA", SkeletalMesh=skeletal, RelativeLocation={"Z": 100}),
    entry("SkeletalMeshComponent", "Rig", "RigB", SkeletalMesh=skeletal, RelativeLocation={"Z": 200}),
    entry("SceneComponent", "Root", "Parent", RelativeLocation={"X": 1000},
          RelativeRotation={"Yaw": 90}, RelativeScale3D={"X": 2, "Y": 2, "Z": 2}),
    entry("PointLightComponent", "Point", "Light", Intensity=100, AttachParent=parent, RelativeLocation={"X": 100}),
    entry("FoliageInstancedStaticMeshComponent", "Instances", "Instanced", StaticMesh=static, OverrideMaterials=override,
          PerInstanceSMData=[{"Translation": {"X": 100, "Y": 0, "Z": 0}}, {"Translation": {"X": 200, "Y": 0, "Z": 0}}]),
    # Cooked pickup components can explicitly clear their mesh. UE's null-name
    # reference must remain an empty, without trying to load None.uasset.
    entry("SkeletalMeshComponent", "NullRig", "Unassigned", SkeletalMesh=reference("None")),
]


class Session:
    cache_namespace = "generic-map-fixture"
    calls = Counter()

    def static_mesh(self, path):
        self.calls["static"] += 1
        return mesh_payload

    def skeletal_mesh(self, path, **kwargs):
        self.calls["skeletal"] += 1
        return mesh_payload

    def material_instance(self, path):
        return {"textures": []}

    def material_asset_path(self, path):
        return path

    def umap_actors(self, path):
        return {"actors": entries}

    def __call__(self, path):
        raise AssertionError("This fixture has no texture references.")


session = Session()
assets = maps.MapAssets(bpy.context, session, 0.01)
count, missing = maps.import_map(bpy.context, session, assets, "/Game/One/Map.umap")
assert not missing
assert count == 9, count
bpy.context.view_layer.update()
collection = next(col for col in bpy.data.collections if col.get("ue_map_path") == "/Game/One/Map.umap")
objects = list(collection.all_objects)
ordinary = [obj for obj in objects if obj.type == "MESH" and obj.get("ue_component_name") in {"Child", "Mesh"}]
assert len(ordinary) == 2
assert ordinary[0].data == ordinary[1].data
child = next(obj for obj in ordinary if obj.get("ue_component_name") == "Child")
other = next(obj for obj in ordinary if obj.get("ue_component_name") == "Mesh")
assert child.name.split(".", 1)[0] == "Mesh", child.name
assert other.name.split(".", 1)[0] == "Mesh", other.name
assert child["ue_virtual_path"] == "/Game/Mesh.Mesh"
assert child.parent.get("ue_component_path") == parent["ObjectPath"]
assert child.parent.get("ue_component_name") == "Root"
assert child.material_slots[0].material != other.material_slots[0].material
assert child.material_slots[0].link == "OBJECT"
assert (child.matrix_world.translation - Vector((10, -2, 0))).length < 1e-5, child.matrix_world
light = next(obj for obj in objects if obj.type == "LIGHT")
assert (light.matrix_world.translation - Vector((10, -2, 0))).length < 1e-5, light.matrix_world
rigs = [obj for obj in objects if obj.type == "ARMATURE"]
assert len(rigs) == 2 and rigs[0].data == rigs[1].data
for rig in rigs:
    skin = next(obj for obj in rig.children if obj.type == "MESH")
    assert skin.name.split(".", 1)[0] == "Rig", skin.name
    assert skin.vertex_groups and any(mod.type == "ARMATURE" for mod in skin.modifiers)
    assert not any(mod.use_deform_preserve_volume for mod in skin.modifiers if mod.type == "ARMATURE")
for obj in objects:
    assert obj.get("ue_source_id") == session.cache_namespace
    assert "ExternalEmissiveContext" not in obj
assert session.calls == {"static": 1, "skeletal": 1}, session.calls
# Same basename in another package must create its own origin and collection,
# while both selected maps continue to share the source mesh and rig data.
session.hidden_object_patterns = ("cHi?d", "oTh*", "rIgA")
count, missing = maps.import_map(bpy.context, session, assets, "/Game/Two/Map.umap")
second = next(col for col in bpy.data.collections if col.get("ue_map_path") == "/Game/Two/Map.umap")
assert second != collection
for obj in second.objects:
    component = obj.get("ue_component_name")
    actor = obj.get("ue_actor_path", "").rsplit(".", 1)[-1]
    if component in {"Child", "Mesh"} or actor == "RigA":
        assert obj.hide_get() and obj.hide_render, obj.name
        for child_obj in obj.children_recursive:
            assert child_obj.hide_get() and child_obj.hide_render, child_obj.name
    elif component == "Rig" and actor == "RigB":
        assert not obj.hide_get() and not obj.hide_render, obj.name
assert not child.hide_get() and not child.hide_render
from addon.formats.unreal_mesh.visibility import apply_default_visibility
apply_default_visibility(other, ("  mEsH  ",))
assert other.hide_get() and other.hide_render

assert len([obj for obj in second.objects if obj.get("sqex_map_import_root")]) == 1
assert session.calls == {"static": 1, "skeletal": 1}, session.calls
addon.unregister()
print("GENERIC_UMAP_FIXTURE_OK")
