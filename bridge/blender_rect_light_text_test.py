"""Check rectangular emitters and editable text, including late/socket parents."""
from pathlib import Path
import math
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.formats.ue_map import lights, map_import, text_render


def ref(name):
    path = "/Game/Fixture.Map:PersistentLevel." + name
    return {"ObjectPath": path, "ObjectName": f"Object'{path}'"}


def entry(kind, name, **props):
    return {"Type": kind, "Name": name, "Properties": props}


parent = ref("Parent.Root")
entries = [
    entry("RectLightComponent", "Area", Intensity=123, IntensityUnits="ELightUnits::Lumens",
          SourceWidth=200, SourceHeight=50, LightColor={"R": 255, "G": 128, "B": 0},
          AttenuationRadius=1000, Temperature=3200, bUseTemperature=False, CastShadows=False,
          BarnDoorAngle=60, BarnDoorLength=20),
    entry("RectLightComponent", "AttachedArea", Intensity=10, AttachParent=parent,
          RelativeLocation={"X": 100}, RelativeRotation={"Yaw": 20}),
    entry("RectLightComponent", "DisabledArea", Intensity=100, bAffectsWorld=False),
    entry("TextRenderComponent", "Label", Text={"LocalizedString": "Hello\r\nBlender"}, WorldSize=50,
          HorizontalAlignment="EHorizTextAligment::EHTA_Center", VerticalAlignment="EVerticalTextAligment::EVRTA_TextBottom",
          TextRenderColor={"R": 64, "G": 128, "B": 255}, bHiddenInGame=True,
          RelativeLocation={"Z": 10}, AttachParent=parent, XScale=2, YScale=0.5),
    {"Type": "SceneComponent", "Name": "Root", "Outer": ref("Parent"),
     "Properties": {"RelativeLocation": {"X": 1000}, "RelativeRotation": {"Yaw": 90}}},
]
collection = bpy.data.collections.new("RectTextFixture")
bpy.context.scene.collection.children.link(collection)
count, missing = map_import.import_map_entries(entries, "RectText.umap", 2.0, 0.5,
    import_models=True, game_features=False, import_reflection_probes=False, target_collection=collection)
assert count == 5 and not missing
bpy.context.view_layer.update()
area = bpy.data.objects["Area"]
assert area.data.type == "AREA" and area.data.shape == "RECTANGLE"
assert math.isclose(area.data.size, 2.0, abs_tol=1e-6) and math.isclose(area.data.size_y, 0.5, abs_tol=1e-6)
assert math.isclose(area.data.energy, 246.0 / 683, rel_tol=1e-6)
assert (area.matrix_world.to_3x3() @ Vector((0, 0, -1)) - Vector((1, 0, 0))).length < 1e-5
assert (area.matrix_world.to_3x3() @ Vector((1, 0, 0)) - Vector((0, -1, 0))).length < 1e-5
assert (area.matrix_world.to_3x3() @ Vector((0, 1, 0)) - Vector((0, 0, 1))).length < 1e-5
assert not area.data.use_shadow
assert not getattr(area.data, "use_temperature", False)
assert area.data["ue_intensity_units"] == "ELightUnits::Lumens"
assert math.isclose(area[lights.UE_ATTENUATION_RADIUS_PROP], 5.0)
assert area[lights.UE_SOURCE_RADIUS_PROP] == 0
assert math.isclose(area.data["ue_barn_door_angle"], 60)
if hasattr(area.data, "normalize"):
    assert area.data.normalize
assert bpy.data.objects["DisabledArea"].hide_render and bpy.data.objects["DisabledArea"].hide_viewport
attached = bpy.data.objects["AttachedArea"]
assert attached.parent and attached.parent.name == "Parent"
assert (attached.matrix_world.translation - Vector((10, -1, 0))).length < 1e-5
expected = Vector((math.cos(math.radians(110)), -math.sin(math.radians(110)), 0))
assert (attached.matrix_world.to_3x3() @ Vector((0, 0, -1)) - expected).length < 1e-5
assert math.isclose(attached.data.size, 0.64, abs_tol=1e-6)
assert math.isclose(attached.data.size_y, 0.64, abs_tol=1e-6)
label = bpy.data.objects["Label"]
assert label.type == "FONT" and label.data.body == "Hello\nBlender"
assert math.isclose(label.data.size, 0.5)
assert label.data.align_x == "CENTER" and label.data.align_y == "BOTTOM_BASELINE"
assert label.hide_render and not label.hide_viewport
assert label.parent == attached.parent
assert tuple(label.scale) == (2, 0.5, 1)
assert (label.matrix_world.translation - Vector((10, 0, 0.1))).length < 1e-5
assert text_render.text_value({"TextHistory": {"SourceString": "Nested"}}) == "Nested"
assert text_render.text_value("") == ""

# Emitter width/height use UE Y/Z scale, not component forward scale.
scaled = map_import.create_rect_light_from_entry(
    entry("RectLightComponent", "ScaledArea", RelativeScale3D={"X": 2, "Y": 3, "Z": 4}),
    collection, 0.01, 1, 1)
assert tuple(scaled.scale) == (3, 4, 2)
map_import.apply_deferred_light_parent(scaled, {"RelativeScale3D": {"X": 2, "Y": 3, "Z": 4}}, attached.parent, 0.01)
assert tuple(scaled.scale) == (3, 4, 2)

# Socket parenting must retain the emitter's forward axis and text scale.
armature = bpy.data.armatures.new("SocketRig")
rig = bpy.data.objects.new("SocketRig", armature)
collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bone = armature.edit_bones.new("Socket")
bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
bpy.ops.object.mode_set(mode="OBJECT")
for obj, props in ((area, {}), (label, {"XScale": 2, "YScale": 0.5})):
    map_import.parent_to_bone(obj, rig, "Socket", props, 0.01)
    bpy.context.view_layer.update()
    assert obj.parent_type == "BONE"
    axis = Vector((0, 0, -1 if obj.type == "LIGHT" else 1))
    assert (obj.matrix_world.to_3x3() @ axis - Vector((1, 0, 0))).length < 1e-5

# A rect-only scene must import with both existing switches disabled.
before = set(bpy.data.objects)
count, _ = map_import.import_map_entries(entries, "RectOnly.umap", 1, 1,
    import_models=False, import_point_lights=False, import_spot_lights=False,
    import_rect_lights=True, game_features=False, import_reflection_probes=False)
created = set(bpy.data.objects) - before
assert len([obj for obj in created if obj.type == "LIGHT"]) == 3
assert not any(obj.type == "FONT" for obj in created)
count, _ = map_import.import_map_entries(entries[:1], "MasterOff.umap", 1, 1,
    import_lights=False, import_models=False, import_reflection_probes=False)
assert count == 0
addon.unregister()
print("RECT_LIGHT_TEXT_OK")
