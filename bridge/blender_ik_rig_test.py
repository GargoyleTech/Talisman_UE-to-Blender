"""Headless regression checks using cached Cloud/Tifa package skeleton fixtures."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('talisman', ROOT / 'addon/__init__.py',
    submodule_search_locations=[str(ROOT / 'addon')])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from talisman.core.blender.skeletons import build_armature_from_bones, _bones_from_gargoyle, apply_naive_ik
from talisman.core.blender.ik_rig import BEND_CONSTRAINT_NAME, repair_limb_ik


def update(arm):
    arm.update_tag()
    bpy.context.view_layer.update()


def error(a, b):
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))


def reset_pose(arm):
    # Includes hidden bones: stronger than clearing only the selected controls.
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    update(arm)


def check_reset_compression(arm, side, end, middle):
    for fraction in (.15, .65, .05):
        reset_pose(arm)
        target = arm.pose.bones[f'FF7R_{side}_{end}_IK']
        matrix = target.matrix.copy()
        matrix.translation += (arm.pose.bones[f'{side}_{middle}_a'].head-target.head) * fraction
        target.matrix = matrix
        update(arm)
        error_distance = (arm.pose.bones[f'{side}_{end}_a'].head-target.head).length
        assert error_distance < .0002, (side, end, fraction, error_distance)
    reset_pose(arm)


for character in ('PC0000_00', 'PC0002_00'):
    fixture = json.loads((ROOT / 'dist' / f'mouth_{character}.json').read_text())
    for forward, axes in ((False, False), (True, False), (False, True), (True, True)):
        arm = build_armature_from_bones(bpy.context, character, _bones_from_gargoyle(fixture['skeleton']),
            face_y_forward=forward, preserve_ue_axis_order=axes, connect_bones=forward)
        update(arm)
        originals = {b.name: b.matrix.copy() for b in arm.pose.bones}
        inputs = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
        rest = {b.name: (b.parent.name if b.parent else None, b.matrix_local.copy()) for b in arm.data.bones}
        assert apply_naive_ik(arm) == (4, 4)
        update(arm)
        worst = max((error(arm.pose.bones[n].matrix, m), n) for n, m in originals.items())
        print('IK NEUTRAL', character, forward, axes, worst, flush=True)
        assert worst[0] < .002, worst
        assert apply_naive_ik(arm) == (0, 0)
        assert all(error(arm.pose.bones[n].matrix_basis, m) < 1e-7 for n, m in inputs.items())
        for name, (parent, matrix) in rest.items():
            bone = arm.data.bones[name]
            assert (bone.parent.name if bone.parent else None) == parent
            assert error(bone.matrix_local, matrix) < 1e-7
        # Emulate a legacy generated rig with its transient pose hint cleared.
        hints = 0
        for pb in arm.pose.bones:
            hint = pb.constraints.get(BEND_CONSTRAINT_NAME)
            if hint:
                pb.constraints.remove(hint)
                hints += 1
        assert hints > 0
        before_repair = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
        assert repair_limb_ik(arm) == hints
        assert repair_limb_ik(arm) == 0
        assert all(error(arm.pose.bones[n].matrix_basis, m) < 1e-7 for n, m in before_repair.items())
        assert bpy.ops.object.ff7r_repair_limb_ik() == {'FINISHED'}
        if not forward and not axes:
            from talisman.formats.kdi.drivers import COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
            from talisman.core.blender.mouth_rig import generate_mouth_rig
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'kdi.json'
                path.write_text(json.dumps(fixture['kdis']))
                assert bpy.ops.import_scene.ff7r_kinedriver_json(filepath=str(path), translation_axis_order='YZX',
                    scale_axis_order='YZX', coordinate_profile=COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90) == {'FINISHED'}
            generate_mouth_rig(bpy.context, arm)
            update(arm)
            assert not any(not d.is_valid for d in arm.animation_data.drivers)
            assert all((not arm.data.bones[n].hide and any(c.is_visible for c in arm.data.bones[n].collections)) for n in arm.data.bones.keys()
                       if n.startswith('FF7R_') and (n.endswith('_IK') or n.endswith('_Pole')))
        for side in ('L', 'R'):
            for end, middle, upper, joint in (('Hand', 'Forearm', 'UpperArm', 'Elbow'), ('Foot', 'Foreleg', 'UpperLeg', 'Knee')):
                check_reset_compression(arm, side, end, middle)
                target = arm.pose.bones[f'FF7R_{side}_{end}_IK']
                pole = arm.pose.bones[f'FF7R_{side}_{joint}_Pole']
                bone = arm.pose.bones[f'{side}_{end}_a']
                # Move slightly toward the joint so the target stays reachable.
                matrix = target.matrix.copy()
                matrix.translation += (arm.pose.bones[f'{side}_{middle}_a'].head - bone.head) * .15
                target.matrix = matrix
                update(arm)
                assert (bone.head-target.head).length < .0002, (bone.name, (bone.head-target.head).length)
                original_bend = arm.pose.bones[f'{side}_{middle}_a'].head.copy()
                pole_matrix = pole.matrix.copy()
                axis = bone.head-arm.pose.bones[f'{side}_{upper}_a'].head
                normal = axis.cross(pole.head-arm.pose.bones[f'{side}_{upper}_a'].head).normalized()
                pole_matrix.translation += normal * .08
                pole.matrix = pole_matrix
                update(arm)
                assert (bone.head-target.head).length < .0002
                assert (arm.pose.bones[f'{side}_{middle}_a'].head-original_bend).length > .0001
                target.rotation_mode = 'XYZ'
                target.rotation_euler.y += .2
                update(arm)
                assert bone.matrix.to_quaternion().rotation_difference(target.matrix.to_quaternion()).angle < .001
                target.matrix_basis.identity()
                pole.matrix_basis.identity()
                update(arm)
        if character == 'PC0002_00' and not forward and not axes:
            name = arm.name
            path = ROOT / 'dist' / 'ik_roundtrip.blend'
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
            arm = bpy.data.objects[name]
            check_reset_compression(arm, 'L', 'Hand', 'Forearm')
            target = arm.pose.bones['FF7R_L_Hand_IK']
            matrix = target.matrix.copy()
            matrix.translation += (arm.pose.bones['L_Forearm_a'].head-target.head) * .15
            target.matrix = matrix
            update(arm)
            assert (arm.pose.bones['L_Hand_a'].head-target.head).length < .0002
        bpy.data.objects.remove(arm, do_unlink=True)
print('IK TESTS PASSED', flush=True)
