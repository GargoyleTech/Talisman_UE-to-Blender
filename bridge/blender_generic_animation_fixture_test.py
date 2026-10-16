"""Headless regression tests for neutral generic animation conversion."""

import copy
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.core.blender import skeletons
from addon.formats.unreal_mesh import animations


SOURCE = "/Game/Fixture/Robot_Skeleton.Robot_Skeleton"
BONES = [
    {"name": "Trans", "parentIndex": -1, "translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [2, 2, 2]},
    {"name": 'Child"Quoted', "parentIndex": 0, "translation": [10, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
    {"name": "Tip", "parentIndex": 1, "translation": [5, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
]


def near_matrix(actual, expected, tolerance=2e-5):
    error = max(abs(a - b) for left, right in zip(actual, expected) for a, b in zip(left, right))
    assert error < tolerance, (error, actual, expected)


def payload():
    tracks = []
    for bone in BONES:
        tracks.append({"boneName": bone['name'], "translations": [bone['translation']] * 31,
                       "rotations": [bone['rotation']] * 31, "scales": [bone['scale']] * 31})
    tracks[0]['translations'] = [[frame, frame * 2, 0] for frame in range(31)]
    tracks[1]['rotations'] = [[0, 0, 0, 1] if frame == 0 else
        [0, 0, Quaternion(Vector((0, 0, 1)), frame * 0.01).z,
         Quaternion(Vector((0, 0, 1)), frame * 0.01).w] for frame in range(31)]
    return {"name": "Fixture", "linkedSkeletonPath": SOURCE, "skeletonPath": "Fixture/Content/Robot_Skeleton.uasset",
            "referenceSkeleton": {"bones": BONES}, "numFrames": 31, "framesPerSecond": 30,
            "duration": 1.0, "tracks": tracks}


bpy.context.scene.render.fps = 24
bpy.context.scene.render.fps_base = 1.001
for axes in (False, True):
    for facing in (False, True):
        for factor in (0.01, 0.1):
            armature = skeletons.build_armature_from_bones(bpy.context, "Fixture", skeletons._bones_from_gargoyle({"bones": BONES}),
                scale_factor=factor, preserve_ue_axis_order=axes, face_y_forward=facing, game_features=False)
            armature['ue_skeleton_path'] = SOURCE
            armature['ue_import_scale'] = factor
            animation = payload()
            action, bones, keys, skipped = animations.import_animation_asset(armature, '/Game/Fixture/Clip', animation,
                                                                           start_frame=7, use_fake_user=True)
            assert bones == 3 and keys > 30 and skipped == 0
            assert action.use_fake_user and abs(action.frame_end - (7 + 24 / 1.001)) < 1e-4
            bpy.context.scene.frame_set(7)
            for bone in armature.data.bones:
                near_matrix(armature.pose.bones[bone.name].matrix, bone.matrix_local)
            # Last sample at exactly one second; no title-specific root turn.
            end = 7 + 24 / 1.001
            bpy.context.scene.frame_set(int(end), subframe=end % 1)
            forward = skeletons.Y_FORWARD_ROTATION if facing else Matrix.Identity(4)
            root_delta = forward.to_3x3() @ Vector((30 * factor, -60 * factor, 0))
            near_matrix(armature.pose.bones['Trans'].matrix,
                        Matrix.Translation(root_delta) @ armature.data.bones['Trans'].matrix_local)
            # The scaled reference root must not double-scale its children.
            assert abs(armature.pose.bones['Trans'].scale.x - 1) < 1e-5
            assert (armature.pose.bones['Tip'].head - armature.data.bones['Tip'].head - root_delta).length > factor
            before = len(bpy.data.actions)
            invalid = copy.deepcopy(animation)
            invalid['linkedSkeletonPath'] = '/Game/OtherSkeleton.OtherSkeleton'
            invalid['skeletonPath'] = '/Game/OtherSkeleton'
            try:
                animations.import_animation_asset(armature, '/Game/Invalid', invalid)
                raise AssertionError('Mismatched skeleton accepted')
            except ValueError:
                assert len(bpy.data.actions) == before
            # A map placement reads metadata from shared Armature data.
            armature.data['ue_skeleton_path'] = SOURCE
            del armature['ue_skeleton_path']
            assert animations.skeleton_path(armature) == SOURCE

assert hasattr(bpy.ops.object, 'sqex_import_generic_unreal_animation')
addon.unregister()
addon.register()
print('GENERIC_ANIMATION_FIXTURES_OK: 8 rig conventions, bind scales, root motion, timing, quoted names, skeleton guard')
