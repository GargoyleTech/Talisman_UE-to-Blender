"""Verify real Blender objects, UVs, optics and deferred attachment for map roles."""
from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.formats.ue_map import cameras, map_import


def ref(path):
    return {"ObjectPath": path, "ObjectName": f"Object'{path}'"}


def entry(kind, name, **props):
    return {"Type": kind, "Name": name, "Properties": props}


class Materials:
    cache_namespace = "basic-map-fixture"
    pbr_mapping = {}
    calls = 0

    def material_instance(self, path):
        self.calls += 1
        return {"textures": [{"path": "/Game/Decal_D.Decal_D", "labels": ["BaseColor"]}]}

    def __call__(self, path):
        image = bpy.data.images.get("DecalFixture") or bpy.data.images.new("DecalFixture", 2, 2, alpha=True)
        image.pixels = [1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0.5, 1, 1, 1, 1]
        return image


session = Materials()
parent = ref("/Game/Fixture.Map:PersistentLevel.Parent.Root")
mesh_path = "/Game/Fixture/Prop.Prop"
source = bpy.data.meshes.new("TresFixtureGeometry")
source.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
resolved = []


def mesh_resolver(path):
    resolved.append(path)
    return source


entries = [
    entry("DecalComponent", "Decal", DecalSize={"X": 10, "Y": 20, "Z": 40},
          DecalMaterial=ref("/Game/Decal.Decal"), RelativeScale3D={"X": 2, "Y": 3, "Z": 4},
          AttachParent=parent, RelativeLocation={"X": 100}),
    entry("DecalComponent", "Decal2", DecalMaterial=ref("/Game/Decal.Decal"), bHiddenInGame=True),
    entry("CameraComponent", "View", FieldOfView=60, AspectRatio=2, AttachParent=parent,
          RelativeRotation={"Yaw": 20}, RelativeLocation={"Z": 25}),
    entry("CineCameraComponent", "Cine", Filmback={"SensorWidth": 36, "SensorHeight": 24},
          CurrentFocalLength=50, CurrentAperture=4, CurrentFocusDistance=200,
          LensSettings={"DiaphragmBladeCount": 9}, FocusSettings={"FocusMethod": "ECameraFocusMethod::Manual"}),
    entry("CameraComponent", "Ortho", ProjectionMode="ECameraProjectionMode::Orthographic", OrthoWidth=400),
    entry("DirectionalLightComponent", "Sun", Intensity=683, LightSourceAngle=1, CastShadows=False,
          LightColor={"R": 255, "G": 128, "B": 0}, AttachParent=parent, RelativeRotation={"Yaw": 20}),
    entry("EndTextRenderComponent", "EndLabel", Text={"SourceString": "SQEX label"}, WorldSize=80,
          AttachParent=parent),
    entry("TresStaticMeshComponent", "TresMesh", StaticMesh=ref(mesh_path), RelativeLocation={"Z": 50}),
    {"Type": "SceneComponent", "Name": "Root", "Outer": ref("/Game/Fixture.Map:PersistentLevel.Parent"),
     "AttachmentParentOnly": True,
     "Properties": {"RelativeLocation": {"X": 1000}, "RelativeRotation": {"Yaw": 90}}},
]
collection = bpy.data.collections.new("BasicMapFixture")
bpy.context.scene.collection.children.link(collection)
active_camera = bpy.context.scene.camera
resolution = (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y)
count, missing = map_import.import_map_entries(entries, "Basic.umap", 2, 1,
    static_mesh_resolver=mesh_resolver, target_collection=collection, light_texture_loader=session,
    import_reflection_probes=False, game_features=True)
assert count == len(entries) and not missing, (count, missing)
bpy.context.view_layer.update()
decal = bpy.data.objects["Decal"]
assert decal.type == "MESH" and len(decal.data.polygons) == 1
assert len(decal.data.uv_layers) == 1
assert max(v.co.y for v in decal.data.vertices) == -min(v.co.y for v in decal.data.vertices)
assert math.isclose(max(v.co.y for v in decal.data.vertices), 0.2, abs_tol=1e-6)
assert math.isclose(max(v.co.z for v in decal.data.vertices), 0.4, abs_tol=1e-6)
uv_by_vertex = {loop.vertex_index: tuple(decal.data.uv_layers[0].data[loop.index].uv) for loop in decal.data.loops}
assert uv_by_vertex == {0: (0, 1), 1: (0, 0), 2: (1, 0), 3: (1, 1)}, uv_by_vertex
assert tuple(decal.scale) == (2, 3, 4)
assert (decal.matrix_world.translation - Vector((10, -1, 0))).length < 1e-5
assert not decal.modifiers  # No projection or shrinkwrap in the flat-plane pass.
material = decal.data.materials[0]
assert bpy.data.objects["Decal2"].data.materials[0] == material and session.calls == 1
assert bpy.data.objects["Decal2"].hide_render
shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
assert shader.inputs["Base Color"].is_linked and shader.inputs["Alpha"].is_linked
assert shader.inputs["Base Color"].links[0].from_node.image is not None
base = next(m for m in bpy.data.materials if m.get("ue_virtual_path") == "/Game/Decal.Decal" and not m.get("ue_decal_material"))
assert not next(n for n in base.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].is_linked
from addon.formats.unreal_mesh.materials import build_material
assert build_material("Decal", "/Game/Decal.Decal", session.material_instance("/Game/Decal.Decal"), session) == base
view, cine, ortho, sun = [bpy.data.objects[n] for n in ("View", "Cine", "Ortho", "Sun")]
assert all(obj.type == "CAMERA" for obj in (view, cine, ortho))
assert math.isclose(view.data.angle_x, math.radians(60), abs_tol=1e-6)
assert view["ue_camera_aspect_ratio"] == 2
assert cine.data.lens == 50 and cine.data.sensor_width == 36 and cine.data.sensor_height == 24
assert cine.data.dof.use_dof and cine.data.dof.focus_distance == 2 and cine.data.dof.aperture_fstop == 4
assert ortho.data.type == "ORTHO" and ortho.data.ortho_scale == 4
assert sun.data.type == "SUN" and math.isclose(sun.data.energy, 2)
assert math.isclose(sun.data.angle, math.radians(1), rel_tol=1e-6) and not sun.data.use_shadow
assert not sun.data.node_tree or not sun.data.node_tree.nodes.get("UE4 Light Attenuation")
expected_forward = Vector((math.cos(math.radians(110)), -math.sin(math.radians(110)), 0))
for obj in (view, sun):
    assert obj.parent == decal.parent
    direction = obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    assert (direction - expected_forward).length < 1e-5, (obj.name, direction)
assert (cine.matrix_world.to_quaternion() @ Vector((0, 0, -1)) - Vector((1, 0, 0))).length < 1e-5
assert (cine.matrix_world.to_quaternion() @ Vector((0, 1, 0)) - Vector((0, 0, 1))).length < 1e-5
text = bpy.data.objects["EndLabel"]
assert text.type == "FONT" and text.data.body == "SQEX label" and math.isclose(text.data.size, 0.8, abs_tol=1e-6)
tres = next(o for o in collection.all_objects if o.data == source)
assert tres.type == "MESH" and tres.data == source and resolved == [mesh_path]
assert bpy.context.scene.camera == active_camera
assert resolution == (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y)
disabled = cameras.create_camera_object("DisabledFocus", {"CurrentFocusDistance": 200,
    "FocusSettings": {"FocusMethod": "ECameraFocusMethod::Disable"}}, collection, cine=True)
assert not disabled.data.dof.use_dof and disabled["ue_camera_filmback_fallback"]
assert math.isclose(disabled.data.lens, 35) and math.isclose(disabled.data.sensor_width, 23.76, rel_tol=1e-6)

# Independent directional/master switches and disabled model conversions.
count, _ = map_import.import_map_entries(entries[:8], "SunOnly.umap", 1, 1,
    import_models=False, import_reflection_probes=False, game_features=False,
    import_point_lights=False, import_spot_lights=False, import_rect_lights=False)
assert count == 1, count
count, _ = map_import.import_map_entries(entries[:8], "AllOff.umap", 1, 1,
    import_models=False, import_lights=False, import_reflection_probes=False)
assert count == 0
count, _ = map_import.import_map_entries(entries[:8], "SunOff.umap", 1, 1,
    import_models=False, import_directional_lights=False, import_reflection_probes=False)
assert count == 0
addon.unregister()
print("BASIC_MAP_COMPONENTS_OK")
