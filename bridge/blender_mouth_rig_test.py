"""Background regression checks for the optional mouth layer.

Run with Blender --background --factory-startup --enable-autoexec --python-exit-code 1 --python
this_file.py. Optional arguments after -- are cached fixture JSON paths with
`skeleton`, `mesh`, `path`, and `kdis` fields from PackageAssetSession. Game
assets are not distributed with this test. Fixtures exercise actual weights
and KDI; the standalone case exercises the constraint math without game data.
"""

import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "talisman", ROOT / "addon/__init__.py",
    submodule_search_locations=[str(ROOT / "addon")],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from talisman.core.blender import mouth_rig as rig
from talisman.core.blender.skeletons import build_armature_from_bones, _bones_from_gargoyle
from talisman.games.rebirth.importers.packages import import_skeletal_mesh_asset
from talisman.formats.kdi.drivers import (
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90, COORDINATE_PROFILE_REFERENCE,
)


def update(arm):
    arm.update_tag()
    bpy.context.view_layer.update()


def matrices(arm):
    update(arm)
    return {b.name: b.matrix.copy() for b in arm.pose.bones}


def error(a, b):
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))


def original_state(arm, names):
    return {
        name: (arm.data.bones[name].parent.name if arm.data.bones[name].parent else None,
               tuple(v for row in arm.data.bones[name].matrix_local for v in row),
               arm.data.bones[name].use_connect, arm.data.bones[name].use_deform,
               arm.data.bones[name].inherit_scale, arm.data.bones[name].hide,
               tuple(c.name for c in arm.data.bones[name].collections))
        for name in names
    }


def synthetic():
    arm = bpy.data.objects.new("SyntheticFace", bpy.data.armatures.new("SyntheticFace"))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    points = {
        rig.FACE: (0, 0, 1.6), "C_Chin": (.11, 0, 1.57),
        "C_Dteeth": (.107, 0, 1.60), "L_Gonion": (.05, .055, 1.61),
        "R_Gonion": (.05, -.055, 1.61), "L_Eye": (.09, .03, 1.67),
        "R_Eye": (.09, -.03, 1.67), "C_Dlip": (.115, 0, 1.59),
        "C_Uteeth": (.107, 0, 1.605), "C_Tongtip": (.09, 0, 1.60),
    }
    for name, point in points.items():
        bone = arm.data.edit_bones.new(name)
        bone.head = point
        bone.tail = Vector(point) + Vector((0, .02, 0))
        if name != rig.FACE:
            bone.parent = arm.data.edit_bones[rig.FACE]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def mesh_points(obj):
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    result = [v.co.copy() for v in mesh.vertices]
    ev.to_mesh_clear()
    return result


def exercise(arm, mesh=None):
    names = set(arm.data.bones.keys())
    state = original_state(arm, names)
    original_drivers = {(f.data_path, f.array_index) for f in arm.animation_data.drivers} if arm.animation_data else set()
    before = matrices(arm)
    vertices = mesh_points(mesh) if mesh else None
    count = rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
    assert count > 0
    assert original_state(arm, names) == state
    assert len(arm.data.bones) == len(names) + 2
    assert rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False) == count
    after = matrices(arm)
    assert max(error(before[n], after[n]) for n in names) < 2e-5
    if mesh:
        assert max((a-b).length for a, b in zip(vertices, mesh_points(mesh))) < 2e-5

    control = arm.pose.bones[rig.CONTROL]
    manifest = json.loads(arm[rig.RIG_PROPERTY])
    constraints = [arm.pose.bones[n].constraints[c] for n, c in manifest["constraints"]]
    targets = {n for n, _ in manifest["constraints"]}
    # Neutral must remain neutral with head motion, armature transforms and
    # nonzero original facial pose channels. Test additive movement analytically.
    arm.pose.bones[rig.FACE].rotation_mode = "XYZ"
    arm.pose.bones[rig.FACE].rotation_euler = (.2, .3, -.1)
    arm.pose.bones["C_Dteeth"].location = (.003, -.002, .001)
    arm.location = (2, 3, 4)
    arm.rotation_euler = (.1, -.2, .4)
    arm.scale = (1.2, .8, 1.1)
    for angle in (0, math.radians(10), math.radians(25)):
        control.rotation_euler.x = angle
        for c in constraints:
            c.mute = True
        incoming = matrices(arm)
        face = arm.pose.bones[rig.FACE].matrix.copy()
        delta = face.inverted() @ arm.pose.bones[rig.DELTA].matrix
        for c in constraints:
            c.mute = False
        posed = matrices(arm)
        expected = face @ delta @ face.inverted() @ incoming["C_Dteeth"]
        assert error(expected, posed["C_Dteeth"]) < 2e-5, (arm.name, angle, "jaw delta")
        assert error(incoming["C_Uteeth"], posed["C_Uteeth"]) < 2e-5
        if angle == 0:
            assert max(error(incoming[n], posed[n]) for n in targets) < 2e-5
        else:
            assert (posed["C_Dteeth"].translation - incoming["C_Dteeth"].translation).length > 1e-4
        control["influence"] = 0.0
        zero = matrices(arm)
        assert max(error(incoming[n], zero[n]) for n in targets) < 2e-5
        control["influence"] = 1.0

    for prop in ("lip_follow", "corner_follow", "jaw_side_follow"):
        control[prop] = 0.0
    zero_follow = matrices(arm)
    for name in ("C_Dlip", "L_Dcor", "L_Gonion"):
        if name in targets:
            assert error(incoming[name], zero_follow[name]) < 2e-5
    for f in arm.animation_data.drivers:
        if f.data_path.endswith('.influence') and rig.CONSTRAINT in f.data_path:
            assert f.is_valid, f.data_path

    # Removing while open must restore the incoming original pose and drivers.
    rig.remove_mouth_rig(bpy.context, arm)
    assert set(arm.data.bones.keys()) == names
    assert original_state(arm, names) == state
    assert {(f.data_path, f.array_index) for f in arm.animation_data.drivers} == original_drivers
    removed = matrices(arm)
    assert max(error(incoming[n], removed[n]) for n in targets) < 2e-5
    assert not rig.remove_mouth_rig(bpy.context, arm)
    print("MOUTH_PASS", arm.name, count, "targets", flush=True)


arm = synthetic()
exercise(arm)
# Unsupported/missing bones and collisions must leave no partial rig behind.
arm.data.bones["C_Chin"].name = "MissingChin"
before = set(arm.data.bones.keys())
try:
    rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
    raise AssertionError("Missing required landmark was accepted")
except ValueError:
    assert set(arm.data.bones.keys()) == before
arm.data.bones["MissingChin"].name = "C_Chin"

# Name conflicts and nonstandard parent chains must fail before mutation.
arm.data.bones["C_Uteeth"].name = rig.CONTROL
try:
    rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
    raise AssertionError("Reserved name collision was accepted")
except ValueError:
    assert rig.RIG_PROPERTY not in arm
arm.data.bones[rig.CONTROL].name = "C_Uteeth"
shared = bpy.data.objects.new("SharedFace", arm.data)
bpy.context.collection.objects.link(shared)
try:
    rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
    raise AssertionError("Shared armature data was accepted")
except ValueError:
    assert rig.RIG_PROPERTY not in arm
bpy.data.objects.remove(shared, do_unlink=True)

# A failed build after bone creation must restore the original rig and mode.
collections = set(arm.data.collections.keys())
original_property = rig._property
def fail_property(*args):
    raise RuntimeError("Injected construction failure")
rig._property = fail_property
bpy.ops.object.mode_set(mode="POSE")
try:
    try:
        rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
        raise AssertionError("Injected failure did not run")
    except RuntimeError as exc:
        assert str(exc) == "Injected construction failure"
        assert rig.CONTROL not in arm.data.bones and rig.DELTA not in arm.data.bones
        assert set(arm.data.collections.keys()) == collections
        assert arm.mode == "POSE"
finally:
    rig._property = original_property
bpy.ops.object.mode_set(mode="OBJECT")

# Verify generation on an already posed rig, keyframing, and persistence.
rig.generate_mouth_rig(bpy.context, arm, create_lip_controls=False)
control = arm.pose.bones[rig.CONTROL]
control.rotation_euler.x = 0
control.keyframe_insert("rotation_euler", index=0, frame=1)
control.rotation_euler.x = .3
control.keyframe_insert("rotation_euler", index=0, frame=10)
bpy.context.scene.frame_set(10)
saved = matrices(arm)["C_Dteeth"]
with tempfile.TemporaryDirectory() as temp:
    filepath = str(Path(temp) / "mouth_roundtrip.blend")
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    bpy.ops.wm.open_mainfile(filepath=filepath)
    arm = bpy.data.objects["SyntheticFace"]
    assert error(saved, matrices(arm)["C_Dteeth"]) < 2e-5
    bpy.context.scene.frame_set(1)
    assert error(saved, matrices(arm)["C_Dteeth"]) > .001
    rig.remove_mouth_rig(bpy.context, arm)

for operator in (
    bpy.ops.import_scene.ff7r_rebirth_skeleton_game_packages,
    bpy.ops.import_scene.ff7r_rebirth_skeletal_mesh_game_packages,
):
    assert operator.get_rna_type().properties["generate_mouth_controls"].default is False

fixtures = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
for fixture in fixtures:
    data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    for forward, axes, scale, kdi in (
        (False, False, .01, False), (True, False, .01, True),
        (False, True, .02, True), (True, True, .01, False),
    ):
        name = f'{Path(fixture).stem}_{forward}_{axes}_{scale}_{kdi}'
        arm = build_armature_from_bones(
            bpy.context, name, _bones_from_gargoyle(data["skeleton"]),
            face_y_forward=forward, preserve_ue_axis_order=axes, scale_factor=scale,
        )
        if kdi:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "kdi.json"
                for asset in data["kdis"]:
                    path.write_text(json.dumps([asset]), encoding="utf-8")
                    result = bpy.ops.import_scene.ff7r_kinedriver_json(
                        filepath=str(path), translation_axis_order="XZY" if axes else "YZX",
                        scale_axis_order="XZY" if axes else "YZX",
                        coordinate_profile=COORDINATE_PROFILE_REFERENCE if axes else COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
                    )
                    assert result == {"FINISHED"}
        obj, _, _ = import_skeletal_mesh_asset(
            bpy.context, data["mesh"], data["path"], armature_obj=arm,
            scale_factor=scale, face_y_forward=forward,
        )
        exercise(arm, obj)
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.objects.remove(arm, do_unlink=True)

print("MOUTH_TESTS_PASSED", flush=True)
