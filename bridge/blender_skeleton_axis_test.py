"""Source axes must bypass the complete display correction, including sockets.

Run with Blender --background --factory-startup --python-exit-code 1 --python.
"""

from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.core.blender import skeletons as skel
from addon.formats.kdi import drivers as kdi
from addon.games.rebirth.importers import animations


def near(actual, expected, tolerance=2e-5):
    error = max(abs(a - b) for row_a, row_b in zip(actual, expected)
                for a, b in zip(row_a, row_b))
    assert error < tolerance, (error, actual, expected)


source = {"bones": [
    {"name": "Root", "parentIndex": -1},
    {"name": "Child", "parentIndex": 0, "translation": [10, 0, 0],
     "rotation": list(Quaternion(Vector((1, 2, 3)).normalized(), 0.7))[1:]
                 + [Quaternion(Vector((1, 2, 3)).normalized(), 0.7).w]},
    {"name": "Tip", "parentIndex": 1, "translation": [7, 0, 0]},
    {"name": "NearNegativeY", "parentIndex": 0, "translation": [0, 0, 10],
     "rotation": [0, 0, 0.999999995, 0.0001]},
]}
socket = {"name": "Attach", "boneName": "Child", "translation": [2, 3, 4],
          "rotation": [0, 0, 0.3826834324, 0.9238795325]}
bones = skel._bones_from_gargoyle(source)
display = Matrix(((0, 1, 0, 0), (0, 0, -1, 0), (-1, 0, 0, 0), (0, 0, 0, 1)))
legacy_display = Matrix(((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))

for game_features in (False, True):
    for forward in (False, True):
        for socket_bones in (False, True):
            rigs = {}
            raw = []
            for bone in bones:
                local = skel.ue_bone_transform_to_blender(bone["translation"], bone["rotation"], 0.01)
                parent = bone["parent_index"]
                raw.append((raw[parent] if parent >= 0 else
                            skel.Y_FORWARD_ROTATION if forward else Matrix.Identity(4)) @ local)
            raw_socket = raw[1] @ skel._socket_local_matrix(socket, 0.01)
            for preserve in (True, False):
                rig = skel.build_armature_from_bones(
                    bpy.context, "AxisFixture", bones, [socket],
                    preserve_ue_axis_order=preserve, face_y_forward=forward,
                    game_features=game_features, connect_bones=True,
                    create_socket_bones=socket_bones, create_socket_empties=not socket_bones)
                rigs[preserve] = rig
                correction = Matrix.Identity(4) if preserve else display
                for bone, expected in zip(bones, raw):
                    actual = rig.data.bones[bone["name"]]
                    # Blender quantizes directions extremely close to -Y.
                    tolerance = 3e-4 if bone["name"] == "NearNegativeY" else 2e-5
                    near(actual.matrix_local, expected @ correction, tolerance)
                    direction = (actual.tail_local - actual.head_local).normalized()
                    assert direction.dot((expected @ correction).to_3x3().col[1]) > 0.99999
                if socket_bones:
                    near(rig.data.bones["Attach"].matrix_local, raw_socket @ correction)
                else:
                    bpy.context.view_layer.update()
                    empty = next(child for child in rig.children if child.get("sqex_socket_bone"))
                    near(empty.matrix_world, raw_socket)
                # New source rigs use the identity correction; older saved
                # UNREAL rigs keep the historical X-to-Y correction.
                near(animations._display_corrections_for_armature(rig)[0], correction)
                if preserve:
                    del rig[skel.BONE_AXIS_FRAME_PROPERTY]
                    near(animations._display_corrections_for_armature(rig)[0], Matrix.Identity(4))
                    del rig.data[skel.BONE_AXIS_FRAME_PROPERTY]
                    near(animations._display_corrections_for_armature(rig)[0], legacy_display)
            for name in (bone["name"] for bone in bones):
                a, b = (rigs[flag].data.bones[name] for flag in (True, False))
                assert (a.head_local - b.head_local).length < 1e-6
                assert (a.tail_local - b.tail_local).length > 1e-5

# The KDI source-frame mapping must agree with the established package mapping
# for arbitrary vectors and rotations, and preserve per-channel target signs.
rolled_basis = Matrix(kdi.coordinate_basis_to_reference(kdi.COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90))
source_basis = Matrix(kdi.coordinate_basis_to_reference(kdi.COORDINATE_PROFILE_SOURCE_AXES))
near(source_basis, rolled_basis @ display.to_3x3().inverted())
rotation = Quaternion(Vector((2, -1, 3)).normalized(), 0.6)
source_config = {"coordinate_profile": kdi.COORDINATE_PROFILE_SOURCE_AXES}
rolled_config = {"coordinate_profile": kdi.COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90}
rolled_rotation = display.to_3x3().inverted() @ rotation.to_matrix() @ display.to_3x3()
near(Matrix(kdi.quaternion_to_matrix3(kdi.source_quaternion_in_reference_frame(source_config, list(rotation)))),
     Matrix(kdi.quaternion_to_matrix3(kdi.source_quaternion_in_reference_frame(rolled_config, list(rolled_rotation.to_quaternion())))))

# Rebirth has an additional root-track correction. Check actual keyed poses
# for new preserved rigs, unchanged Blender rigs, and pre-fix saved UNREAL rigs.
animation_bones = bones[:3]
for forward in (False, True):
    forward_matrix = skel.Y_FORWARD_ROTATION if forward else Matrix.Identity(4)
    for mode, correction in (("SOURCE", Matrix.Identity(4)),
                             ("BLENDER", display), ("LEGACY_UNREAL", legacy_display)):
        rig = skel.build_armature_from_bones(
            bpy.context, mode, animation_bones, preserve_ue_axis_order=mode != "BLENDER",
            face_y_forward=forward, game_features=False)
        if mode == "LEGACY_UNREAL":
            bpy.ops.object.mode_set(mode="EDIT")
            raw_bind = []
            for bone in animation_bones:
                parent = bone["parent_index"]
                local = skel.ue_bone_transform_to_blender(bone["translation"], bone["rotation"], 0.01)
                raw_bind.append((raw_bind[parent] if parent >= 0 else forward_matrix) @ local)
                rig.data.edit_bones[bone["name"]].matrix = raw_bind[-1] @ correction
            bpy.ops.object.mode_set(mode="OBJECT")
            del rig[skel.BONE_AXIS_FRAME_PROPERTY]
            del rig.data[skel.BONE_AXIS_FRAME_PROPERTY]
        rig["sqex_skeleton_asset_path"] = "Fixture/Skeleton.uasset"
        tracks = []
        end_locals = []
        root_correction = (animations.ROOT_DISPLAY_CORRECTION @ display.inverted()
                           if mode != "LEGACY_UNREAL" else
                           legacy_display @ animations.ROOT_TRACK_CORRECTION @ legacy_display.inverted())
        for index, bone in enumerate(animation_bones):
            if index == 0:
                end_local = Matrix.Translation((0.05, -0.02, 0.01)) @ Matrix.Rotation(0.3, 4, "Z")
                first_rotation = root_correction.inverted().to_quaternion()
                last_rotation = (end_local @ root_correction.inverted()).to_quaternion()
                translations = [[0, 0, 0], [5, 2, 1]]
            else:
                end_local = skel.ue_bone_transform_to_blender(bone["translation"], bone["rotation"], 0.01)
                first_rotation = end_local.to_quaternion()
                last_rotation = (end_local @ Matrix.Rotation(0.4, 4, "X")).to_quaternion()
                end_local = Matrix.Translation(end_local.translation) @ last_rotation.to_matrix().to_4x4()
                translations = [list(bone["translation"])] * 2
            ue_quaternion = lambda q: [-q.x, q.y, -q.z, q.w]
            tracks.append({"boneName": bone["name"], "bindTranslation": list(bone["translation"]),
                           "bindRotation": list(bone["rotation"]), "bindScale": [1, 1, 1],
                           "translations": translations, "translationFrames": [0, 1],
                           "rotations": [ue_quaternion(first_rotation), ue_quaternion(last_rotation)],
                           "rotationFrames": [0, 1], "scales": [[1, 1, 1]]})
            end_locals.append(end_local)
        result = animations.import_animation_asset(
            rig, "Fixture/Clip.uasset", {"name": mode, "numFrames": 2,
                "framesPerSecond": bpy.context.scene.render.fps, "tracks": tracks},
            replace_current_action=True)
        assert result[-1] < 2e-5, (mode, result[-1])
        bpy.context.scene.frame_set(2)
        globals_ = []
        for index, bone in enumerate(animation_bones):
            parent = bone["parent_index"]
            globals_.append((globals_[parent] if parent >= 0 else forward_matrix) @ end_locals[index])
            near(rig.pose.bones[bone["name"]].matrix, globals_[-1] @ correction)

addon.unregister()
print("SKELETON_AXES_OK: source rotations, changed tails, both game modes, forward axes, sockets, Rebirth animation, legacy rigs, KDI frames")
