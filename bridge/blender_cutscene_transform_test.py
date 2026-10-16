"""Run with Blender --background --factory-startup --python this_file -- Character.json.

Uses the actual GOLDE_0500 binding/transform data with small synthetic skeletal
actions to isolate object placement from the ACL decoder and mesh importer.
"""
import importlib
import copy
import json
import math
from pathlib import Path
import sys
import types

import bpy
from mathutils import Matrix, Vector
from bpy_extras import anim_utils

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("cutscene_test_source")
package.__path__ = [str(root / "addon" / "json")]
sys.modules[package.__name__] = package
ci = importlib.import_module(package.__name__ + ".cutscene_import")
source = Path(sys.argv[sys.argv.index("--") + 1])
data = json.loads(source.read_text(encoding="utf-8-sig"))
scene = bpy.context.scene
scene.render.fps = 30
timing = ci._extract_timing(data, 30)
bindings = ci._parse_binding_refs(data, "EV_GOLDE_0500")
tracks = ci._parse_obj_bindings(data)
actors = {}

for guid, cid in bindings.items():
    obj = bpy.data.objects.new(cid, bpy.data.armatures.new(cid))
    scene.collection.objects.link(obj)
    actors[cid] = obj
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = obj.data.edit_bones.new("Trans")
    bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    for section in ci._skeletal_sections_for_binding(data, tracks[guid], 24000, 30):
        if bpy.data.actions.get(section["anim_name"]):
            continue
        action, slot, strip = ci._setup_action(obj, "OBJECT", section["anim_name"])
        for axis, value in enumerate((5, 6, 7)):
            keys = [{"frame": frame, "value": value, "interp": ci.INTERP_CONSTANT,
                     "arrive": 0, "leave": 0} for frame in (1, 100)]
            # Avoid collapsing the synthetic action's duration in this fixture.
            bag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
            curve = bag.fcurves.new('pose.bones["Trans"].location', index=axis)
            for key in keys:
                curve.keyframe_points.insert(key["frame"], key["value"])
    obj.location = (400, 500, 600)
    obj.rotation_euler = (0.4, 0.5, 0.6)
    obj.scale = (2, 2, 2)
    _, slot, strip = ci._setup_action(obj, "OBJECT", cid + "_old_bad_transform")
    ci._write_keys(strip, slot, "location", 0, [
        {"frame": 0, "value": 400, "interp": 0, "arrive": 0, "leave": 0}])

for reference_format in ("fmodel", "gargoyle", "qualified", "path_only"):
    import_data = copy.deepcopy(data)
    for item in import_data:
        if item["Type"] != "MovieScene":
            continue
        for possessable in item["Properties"].get("Possessables", []):
            class_name = ci._possessed_class_name(possessable)
            if reference_format == "gargoyle":
                possessable["PossessedObjectClass"] = {
                    "ObjectName": f"Object'{class_name}'", "ObjectPath": class_name}
            elif reference_format == "qualified":
                possessable["PossessedObjectClass"] = {
                    "ObjectName": f"Class'/Script/Engine.{class_name}'"}
            elif reference_format == "path_only":
                possessable["PossessedObjectClass"] = {
                    "ObjectPath": f"/Script/Engine.{class_name}"}
    ci._import_characters_explicit_sections(import_data, timing, scene, "EV_GOLDE_0500")
    for frame in (1, 200, 409, 700):
        scene.frame_set(frame)
        cloud = actors["PC0000_00"]
        assert cloud.location.length < 1e-6
        assert max(abs(value) for value in cloud.rotation_euler) < 1e-6
        assert (cloud.scale - Vector((1, 1, 1))).length < 1e-6
        bag = anim_utils.action_ensure_channelbag_for_slot(
            cloud.animation_data.action, cloud.animation_data.action_slot)
        assert not any(fc.data_path in {"location", "rotation_euler", "scale"}
                       for fc in bag.fcurves)
        # The synthetic world-space root must receive its placement exactly once.
        assert (cloud.matrix_world @ cloud.pose.bones["Trans"].matrix.translation
                - Vector((5, 6, 7))).length < 1e-5

        pillow = actors["BG2099_00"]
        assert (pillow.location - Vector((491.929, -21.4867, 567.857))).length < 1e-4
        expected = (Matrix.Rotation(math.radians(-147.66997), 3, "Z")
                    @ Matrix.Rotation(math.radians(44.999992), 3, "Y"))
        actual = pillow.rotation_euler.to_matrix()
        assert max(abs(actual[r][c] - expected[r][c])
                   for r in range(3) for c in range(3)) < 1e-5

assert max(abs(v) for v in ci.ue_actor_rot_to_bl_euler(0, 0, 0)) == 0
print("CUTSCENE_TRANSFORM_TEST_OK: no Cloud object keys; pillow placement/rotation; "
      "FModel, bridge, qualified and path-only references; repeat import")
