"""Smooth lip controls, upgrade/removal, and saved-driver regression checks.

blender --background --factory-startup --enable-autoexec --python-exit-code 1
--python bridge/blender_lip_rig_test.py [-- cached_asset_fixture.json ...]
Fixtures use the same format as blender_mouth_rig_test.py.
"""

import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("talisman", ROOT / "addon/__init__.py",
    submodule_search_locations=[str(ROOT / "addon")])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from talisman.core.blender import mouth_rig as jaw, lip_rig as lip
from talisman.core.blender.skeletons import build_armature_from_bones, _bones_from_gargoyle
from talisman.games.rebirth.importers.packages import import_skeletal_mesh_asset
from talisman.formats.kdi.drivers import COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90


def update(arm):
    arm.update_tag()
    bpy.context.view_layer.update()


def pose(arm):
    update(arm)
    return {b.name: b.matrix.copy() for b in arm.pose.bones}


def error(a, b):
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))


def rest(arm, names):
    return {n: (arm.data.bones[n].parent.name if arm.data.bones[n].parent else None,
        tuple(v for row in arm.data.bones[n].matrix_local for v in row),
        arm.data.bones[n].use_connect, arm.data.bones[n].use_deform,
        tuple(c.name for c in arm.data.bones[n].collections)) for n in names}


def points(mesh):
    ev = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [v.co.copy() for v in ev.data.vertices]


def synthetic():
    arm = bpy.data.objects.new("LipFixture", bpy.data.armatures.new("LipFixture"))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    positions = {jaw.FACE: (0, 0, 1.6), "C_Chin": (.11, 0, 1.57),
        "C_Dteeth": (.107, 0, 1.60), "C_Uteeth": (.108, 0, 1.605),
        "L_Gonion": (.05, .055, 1.61), "R_Gonion": (.05, -.055, 1.61),
        "L_Eye": (.09, .03, 1.67), "R_Eye": (.09, -.03, 1.67)}
    for family, height in (("U", 1.608), ("D", 1.591)):
        for name in (lip.UPPER_LIPS if family == "U" else jaw.LIPS):
            side = 1 if name.startswith("L_") else -1 if name.startswith("R_") else 0
            x = side * (.008 if name.endswith("_A") else .015)
            positions[name] = (.115, x, height)
        for side, x in (("L", .02), ("R", -.02)):
            for suffix in ("", "in"):
                positions[f"{side}_{family}cor{suffix}"] = (.105, x, 1.6)
    for name, point in positions.items():
        bone = arm.data.edit_bones.new(name)
        bone.head = point
        bone.tail = Vector(point) + Vector((0, .02, 0))
        if name != jaw.FACE:
            bone.parent = arm.data.edit_bones[jaw.FACE]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def exercise(arm, mesh=None, expected_targets=38):
    names = set(arm.data.bones.keys())
    original = rest(arm, names)
    hidden = {n: arm.data.bones[n].hide for n in names}
    drivers = {(d.data_path, d.array_index) for d in arm.animation_data.drivers} if arm.animation_data else set()
    jaw.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
    jaw_manifest = arm[jaw.RIG_PROPERTY]
    arm.pose.bones[jaw.CONTROL].rotation_euler.x = .17
    before = pose(arm)
    vertices = points(mesh) if mesh else None
    # Upgrade the previous jaw rig in place while it is posed.
    jaw.generate_mouth_rig(bpy.context, arm)
    assert arm[jaw.RIG_PROPERTY] == jaw_manifest
    assert abs(arm.pose.bones[jaw.CONTROL].rotation_euler.x - .17) < 1e-6
    manifest = json.loads(arm[lip.RIG_PROPERTY])
    assert len(lip.CONTROLS) == 8 and len(manifest["hidden"]) == expected_targets
    assert rest(arm, names) == original
    upgraded = pose(arm)
    assert max(error(before[n], upgraded[n]) for n in names) < 3e-5
    if mesh:
        assert max((a-b).length for a, b in zip(vertices, points(mesh))) < 3e-5
    jaw.generate_mouth_rig(bpy.context, arm)
    assert json.loads(arm[lip.RIG_PROPERTY]) == manifest
    arm.pose.bones[jaw.CONTROL].rotation_euler.x = 0
    neutral = pose(arm)
    offset = Vector((.002, .001, -.003))
    arm.pose.bones[lip.UPPER[2]].location = offset
    moved = pose(arm)
    expected = arm.pose.bones[jaw.FACE].matrix.to_3x3() @ offset
    assert (moved["C_Ulip"].translation - neutral["C_Ulip"].translation - expected).length < 2e-5
    assert error(moved["C_Dlip"], neutral["C_Dlip"]) < 2e-5
    assert error(moved["C_Uteeth"], neutral["C_Uteeth"]) < 2e-5
    # The curve follows the evaluated handle, including pose constraints.
    for objname, controls in zip(manifest["guides"], (lip.UPPER, lip.LOWER)):
        obj = bpy.data.objects[objname].evaluated_get(bpy.context.evaluated_depsgraph_get())
        for i, (p, name) in enumerate(zip(obj.data.splines[0].bezier_points, controls)):
            assert (p.co - arm.pose.bones[name].matrix.translation).length < 2e-5
            tangent = (arm.pose.bones[controls[min(4, i+1)]].matrix.translation
                       - arm.pose.bones[controls[max(0, i-1)]].matrix.translation)/6
            assert (p.handle_left - p.co + tangent).length < 2e-5
            assert (p.handle_right - p.co - tangent).length < 2e-5
        assert all(d.is_valid for d in bpy.data.objects[objname].data.animation_data.drivers)
    arm.pose.bones[lip.UPPER[2]].location = (0, 0, 0)
    arm.pose.bones[lip.LEFT].location = offset
    moved = pose(arm)
    for n in ("L_Ucor", "L_Dcor", "L_Ucorin", "L_Dcorin"):
        assert (moved[n].translation-neutral[n].translation-expected).length < 2e-5
    assert error(moved["R_Ucor"], neutral["R_Ucor"]) < 2e-5
    arm.pose.bones[lip.LEFT].location = (0, 0, 0)
    arm.pose.bones[lip.LOWER[2]].location = offset
    arm.pose.bones[jaw.CONTROL].rotation_euler.x = .3
    arm.pose.bones[jaw.FACE].rotation_mode = "XYZ"
    arm.pose.bones[jaw.FACE].rotation_euler = (.2, .3, -.1)
    arm.location = (1, 2, 3)
    arm.rotation_euler = (.1, .2, .3)
    arm.scale = (1.2, .9, 1.1)
    control = arm.pose.bones[jaw.CONTROL]
    control["lip_controls_influence"] = 0.0
    disabled = pose(arm)
    control["lip_controls_influence"] = 1.0
    shaped = pose(arm)
    assert (shaped["C_Dlip"].translation-disabled["C_Dlip"].translation).length > .001
    for name in lip.CONTROLS:
        arm.pose.bones[name].location = (0, 0, 0)
    cleared = pose(arm)
    assert max(error(disabled[n], cleared[n]) for n in names) < 3e-5
    for d in arm.animation_data.drivers:
        if (d.data_path, d.array_index) not in drivers:
            assert d.is_valid, d.data_path
    control["show_lip_guides"] = False
    update(arm)
    assert all(bpy.data.objects[n].hide_viewport for n in manifest["guides"])
    # Removing only the lip layer preserves the earlier jaw controls/settings.
    lip.remove_lip_rig(bpy.context, arm)
    assert arm[jaw.RIG_PROPERTY] == jaw_manifest
    assert rest(arm, names) == original
    assert {n: arm.data.bones[n].hide for n in names} == hidden
    assert not any(n in bpy.data.objects for n in manifest["guides"])
    assert all(n not in control for n in lip.PROPERTIES)
    jaw.remove_mouth_rig(bpy.context, arm)
    assert set(arm.data.bones.keys()) == names
    assert {(d.data_path, d.array_index) for d in arm.animation_data.drivers} == drivers
    print("LIP_PASS", arm.name, expected_targets, "bones / 8 handles", flush=True)


# Interpolation has exact knots, mirrored weights and a continuous first derivative.
for i in range(5):
    assert all(abs(w - (1 if j == i else 0)) < 1e-9 for j, w in enumerate(lip.spline_weights(i/4)))
for i in range(101):
    t = i/100
    assert abs(sum(lip.spline_weights(t))-1) < 1e-9
    assert max(abs(a-b) for a, b in zip(lip.spline_weights(t), reversed(lip.spline_weights(1-t)))) < 1e-9
for knot in (.25, .5, .75):
    h = 1e-6
    a, b, c = (lip.spline_weights(t) for t in (knot-h, knot, knot+h))
    assert max(abs((z-y)/h-(y-x)/h) for x, y, z in zip(a,b,c)) < 1e-3
assert not hasattr(bpy.types, "VIEW3D_PT_ff7r_mouth_controls")
arm = synthetic()
exercise(arm)
# Rollback an upgrade failure after helpers, drivers, and hidden states exist.
jaw.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
bone_names = set(arm.data.bones.keys())
hidden_before = {b.name: b.hide for b in arm.data.bones}
driver_paths = {(d.data_path, d.array_index) for d in arm.animation_data.drivers}
original_guides = lip._guides
def fail_guides(*args):
    raise RuntimeError("Injected lip guide failure")
lip._guides = fail_guides
try:
    try:
        jaw.generate_mouth_rig(bpy.context, arm)
        raise AssertionError("Injected failure did not run")
    except RuntimeError as exc:
        assert str(exc) == "Injected lip guide failure"
        assert set(arm.data.bones.keys()) == bone_names
        assert {b.name: b.hide for b in arm.data.bones} == hidden_before
        assert {(d.data_path, d.array_index) for d in arm.animation_data.drivers} == driver_paths
        assert jaw.RIG_PROPERTY in arm and lip.RIG_PROPERTY not in arm
finally:
    lip._guides = original_guides
jaw.generate_mouth_rig(bpy.context, arm)
control = arm.pose.bones[lip.UPPER[2]]
control.location.z = 0
control.keyframe_insert("location", frame=1)
control.location.z = .004
control.keyframe_insert("location", frame=10)
bpy.context.scene.frame_set(10)
saved = pose(arm)["C_Ulip"]
with tempfile.TemporaryDirectory() as temp:
    path = str(Path(temp)/"lips.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    arm = bpy.data.objects["LipFixture"]
    assert error(saved, pose(arm)["C_Ulip"]) < 2e-5
    bpy.context.scene.frame_set(1)
    assert error(saved, pose(arm)["C_Ulip"]) > .001
    jaw.remove_mouth_rig(bpy.context, arm)

fixtures = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
for fixture in fixtures:
    data = json.loads(Path(fixture).read_text())
    for forward, axes, scale, kdi in ((False, False, .01, False), (True, False, .01, True), (False, True, .02, False)):
        arm = build_armature_from_bones(bpy.context, f"{Path(fixture).stem}_{forward}_{axes}",
            _bones_from_gargoyle(data["skeleton"]), face_y_forward=forward, preserve_ue_axis_order=axes, scale_factor=scale)
        if kdi:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp)/"kdi.json"
                path.write_text(json.dumps(data["kdis"]))
                assert bpy.ops.import_scene.ff7r_kinedriver_json(filepath=str(path), translation_axis_order="YZX",
                    scale_axis_order="YZX", coordinate_profile=COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90) == {"FINISHED"}
        mesh, _, _ = import_skeletal_mesh_asset(bpy.context, data["mesh"], data["path"], armature_obj=arm,
            face_y_forward=forward, scale_factor=scale)
        exercise(arm, mesh, expected_targets=34)
        bpy.data.objects.remove(mesh, do_unlink=True)
        bpy.data.objects.remove(arm, do_unlink=True)
print("LIP_TESTS_PASSED", flush=True)
