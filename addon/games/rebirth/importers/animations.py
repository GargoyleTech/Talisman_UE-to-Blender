"""Search and apply Rebirth animation sequences to a selected package armature."""

from __future__ import annotations

import math
import traceback
from bisect import bisect_left
from typing import Iterable

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import packages as game_packages
from ....core.blender.reporting import FF7R_LoggedOperator, report
from ....core.blender import skeletons as skeleton_importer


def _selected_armature_skeleton_path(armature: bpy.types.Object) -> str | None:
    """Get the source Skeleton path recorded by a package armature or bound mesh."""
    direct_path = armature.get(game_packages.SKELETON_ASSET_PATH_PROPERTY)
    if isinstance(direct_path, str) and direct_path.strip():
        return direct_path

    # Older package imports did not tag their armature.  A bound Rebirth mesh
    # still carries the linked Skeleton path, which lets those existing scenes
    # use the picker without reimporting their character.
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        if not any(
            modifier.type == 'ARMATURE' and modifier.object == armature
            for modifier in obj.modifiers
        ):
            continue
        linked_path = obj.get("ff7r_linked_skeleton_path")
        if isinstance(linked_path, str) and linked_path.strip():
            return linked_path
    return None


def _search_matching_animations(_self, _context, edit_text):
    return game_packages._search_virtual_animations(_self, _context, edit_text)


def _vector(value: Iterable[float], fallback: tuple[float, float, float]) -> Vector:
    parts = tuple(float(part) for part in value)
    return Vector(parts[:3] if len(parts) >= 3 else fallback)


def _ue_location(value: Iterable[float]) -> Vector:
    """Centimetres in UE's left-handed frame to metres in Blender's."""
    location = _vector(value, (0.0, 0.0, 0.0)) * 0.01
    location.y = -location.y
    return location


def _quaternion(value: Iterable[float]) -> Quaternion:
    parts = tuple(float(part) for part in value)
    if len(parts) < 4:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    # CUE4Parse serializes FQuat as UE X/Y/Z/W.  This is the same mirror
    # conversion used for the imported Skeleton's bind transforms.
    result = Quaternion((parts[3], -parts[0], parts[1], -parts[2]))
    result.normalize()
    return result


# skeleton/importer.py frames each edit bone by aiming Blender's +Y down Unreal's
# local +X, aligning +Z to Unreal's +Z, then adding a 90 degree roll.  The net
# effect is a single constant change of basis: a package bone's ``matrix_local``
# equals the UE-converted armature-space bind matrix that the importer composes,
# times this rotation.  Derived by replaying that framing on synthetic bind
# matrices; identical for every bone to within 2e-6.
DISPLAY_CORRECTION = Matrix((
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0, 0.0),
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))
DISPLAY_CORRECTION_INVERSE = DISPLAY_CORRECTION.inverted()

# The root track ("Trans") is not a bone-parented transform: its translation is
# the actor's world placement (thousands of centimetres from the origin for a
# cutscene clip, zero for a local action clip).  It is a component-to-world
# placement, so it does not carry the 90 degree display roll that
# skeleton/importer.py adds to each *bone's* frame, and applying that roll to it
# lays the whole character on its side -- hip-to-head pointing down world +X
# instead of +Z.  Undoing the roll is a -90 degree turn about the bone's own Y.
#
# That still left the character yawed 90 degrees, because the track's rotation is
# not neutral either: its rest value is 120 degrees about UE (-1, 1, -1)/sqrt(3)
# -- the value every frame of a clip without root motion carries, and the value
# root-motion clips animate away from.  A correct conversion has to send that
# rest value back to the bone's own rest frame, leaving an identity pose basis
# for a clip that does not move the root.  Solving ``R_rest @ C == matrix_local``
# for a Trans bone whose bind is the identity (so ``matrix_local`` is exactly
# DISPLAY_CORRECTION) gives the -90 Y turn above followed by a further 90 degrees
# about the bone's own X -- the axis that, for this bone, is world -Z, which is
# why the error read as a pure yaw with the character otherwise upright.
ROOT_DISPLAY_CORRECTION = (
    DISPLAY_CORRECTION
    @ Matrix.Rotation(math.radians(-90.0), 4, "Y")
    @ Matrix.Rotation(math.radians(90.0), 4, "X")
)

# Largest per-element difference tolerated between a bone's rest matrix and the
# bind pose the clip was authored against.  Connected bones nudge a parent's tail
# onto the child head, so an exact match is not expected.
REST_CONVENTION_TOLERANCE = 0.01


def _rest_local_matrix(bone: bpy.types.Bone) -> Matrix:
    if bone.parent is None:
        return bone.matrix_local.copy()
    return bone.parent.matrix_local.inverted_safe() @ bone.matrix_local


def _blender_basis_values(
        translation: Iterable[float],
        rotation: Iterable[float],
        scale: Iterable[float],
        basis_prefix: Matrix,
        display_target: Matrix,
) -> tuple[Vector, Quaternion, Vector]:
    """Convert a UE local track transform into this add-on's bone display basis.

    Write ``L`` for a parent-relative UE transform carried into Blender axes and
    ``D`` for :data:`DISPLAY_CORRECTION`.  A package bone's rest matrix is
    ``B_bind @ D`` and its posed matrix must be ``B_anim @ D``, so the
    parent-relative rest is ``D^-1 @ L_bind @ D``, the parent-relative pose is
    ``D^-1 @ L_anim @ D``, and

        matrix_basis = (D^-1 @ L_bind @ D)^-1 @ (D^-1 @ L_anim @ D)
                     = D^-1 @ L_bind^-1 @ L_anim @ D

    which is what this returns.  The same expression covers root bones, where
    both rest and pose instead pick up the importer's -Y-forward rotation and it
    cancels between them.

    Conjugating by ``D`` is the step that was missing: without it the UE delta
    gets applied in the display frame rather than being carried into it, which
    leaves poses that look plausible in scale but are rotated by ~100 degrees.
    """
    source_matrix = Matrix.LocRotScale(
        _ue_location(translation),
        _quaternion(rotation),
        _vector(scale, (1.0, 1.0, 1.0)),
    )
    basis = basis_prefix @ source_matrix @ display_target
    return basis.decompose()


def _rest_convention_error(
        bone: bpy.types.Bone,
        bind_matrix: Matrix,
        forward_rotation: Matrix,
) -> float:
    """How far this bone's rest pose is from the UE bind pose the clip assumes.

    Large values mean the armature was not built by this add-on's package
    importer, so the keys will land somewhere other than the animation intends.

    A root bone's rest is measured against the armature origin rather than a
    parent, so it also carries the importer's forward-axis rotation -- hence
    ``forward_rotation``.  Checking roots matters: the root is the one bone whose
    rest and animated frames are not related by ``DISPLAY_CORRECTION`` alone.
    """
    rest = _rest_local_matrix(bone)
    if bone.parent is None:
        expected = forward_rotation @ bind_matrix @ DISPLAY_CORRECTION
    else:
        expected = DISPLAY_CORRECTION_INVERSE @ bind_matrix @ DISPLAY_CORRECTION
    return max(abs(a - b) for row_a, row_b in zip(expected, rest) for a, b in zip(row_a, row_b))


def _action_curves(action: bpy.types.Action, target: bpy.types.Object):
    """Return a curve factory for the action, plus the slot that owns the curves.

    Blender 4.4 moved an Action's curves into a slot/layer/strip channelbag and
    5.0 dropped the old ``Action.fcurves`` shortcut, so build the channelbag when
    the shortcut is gone.  The two collections name their group argument
    differently and both refuse positional arguments, hence the factory.
    """
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        def new_curve(data_path, axis, group):
            return legacy.new(data_path, index=axis, action_group=group)
        return new_curve, None

    slot = action.slots.new(id_type='OBJECT', name=target.name)
    strip = action.layers.new("Layer").strips.new(type='KEYFRAME')
    curves = strip.channelbag(slot, ensure=True).fcurves

    def new_curve(data_path, axis, group):
        return curves.new(data_path, index=axis, group_name=group)
    return new_curve, slot


def _insert_keys(
        new_curve,
        bone_name: str,
        data_path: str,
        values: list[tuple[float, ...]],
        source_frames: list[float],
        frame_scale: float,
        start_frame: float,
) -> int:
    if not values:
        return 0
    dimensions = len(values[0])
    if not source_frames:
        source_frames = [0.0] * len(values)
    count = min(len(values), len(source_frames))
    for axis in range(dimensions):
        # ACL clips are uniformly sampled, but a channel can still be constant
        # for its whole duration.  Retaining its per-sample copies adds work to
        # Blender without changing evaluation.
        first_value = values[0][axis]
        is_constant = all(
            math.isclose(value[axis], first_value, rel_tol=1e-7, abs_tol=1e-6)
            for value in values[:count]
        )
        indices = (0,) if is_constant else range(count)
        curve = new_curve(data_path, axis, bone_name)
        points = curve.keyframe_points
        points.add(len(indices))
        points.foreach_set(
            "co",
            [coordinate
             for index in indices
             for coordinate in (
                 start_frame + source_frames[index] * frame_scale,
                 values[index][axis],
             )],
        )
        for point in points:
            point.interpolation = 'CONSTANT' if is_constant else 'LINEAR'
        curve.update()
    return sum(
        1 if all(
            math.isclose(value[axis], values[0][axis], rel_tol=1e-7, abs_tol=1e-6)
            for value in values[:count]
        ) else count
        for axis in range(dimensions)
    )


def _key_times(values: list, frames: list[float], num_frames: int) -> list[float]:
    if not values:
        return []
    if len(frames) == len(values):
        return [float(frame) for frame in frames]
    if len(values) == 1:
        return [0.0]
    last_frame = max(1, num_frames - 1)
    return [index * last_frame / (len(values) - 1) for index in range(len(values))]


def _vector_sampler(values: list, frames: list[float], default: Vector):
    """Convert channel values once and sample them with a binary lookup."""
    if not values:
        return lambda _frame: default.copy()
    keys = [_vector(value, tuple(default)) for value in values]

    def sample(frame: float) -> Vector:
        index = bisect_left(frames, frame)
        if index <= 0:
            return keys[0]
        if index >= len(keys):
            return keys[-1]
        span = frames[index] - frames[index - 1]
        fraction = 0.0 if span <= 0 else (frame - frames[index - 1]) / span
        return keys[index - 1].lerp(keys[index], fraction)

    return sample


def _ue_quaternion_sampler(
        values: list,
        frames: list[float],
        default: tuple[float, float, float, float],
):
    """Convert quaternion keys once and sample them with a binary lookup."""
    def as_ue_quaternion(value) -> Quaternion:
        parts = tuple(float(part) for part in value)
        if len(parts) < 4:
            parts = default
        return Quaternion((parts[3], parts[0], parts[1], parts[2]))

    if not values:
        return lambda _frame: default
    keys = [as_ue_quaternion(value) for value in values]

    def sample(frame: float) -> tuple[float, float, float, float]:
        index = bisect_left(frames, frame)
        if index <= 0:
            result = keys[0]
        elif index >= len(keys):
            result = keys[-1]
        else:
            span = frames[index] - frames[index - 1]
            fraction = 0.0 if span <= 0 else (frame - frames[index - 1]) / span
            result = keys[index - 1].slerp(keys[index], fraction)
        return (result.x, result.y, result.z, result.w)

    return sample


def import_animation_asset(
        armature: bpy.types.Object,
        virtual_path: str,
        animation: dict,
        *,
        start_frame: float = 1.0,
        replace_current_action: bool = False,
        scene=None,
) -> tuple[bpy.types.Action, int, int, int, float]:
    """Create a tagged Action from one decoded package AnimSequence.

    This is deliberately independent of an operator so package cutscenes can
    load their own missing clips while the manual animation button retains the
    same conversion path.
    """
    if armature.type != 'ARMATURE':
        raise ValueError("Animation targets must be armature objects.")
    skeleton_path = _selected_armature_skeleton_path(armature)
    if not skeleton_path:
        raise ValueError(f"'{armature.name}' has no Rebirth Skeleton source.")
    scene = scene or bpy.context.scene
    source_fps = float(animation.get("framesPerSecond") or 0.0)
    if source_fps <= 0.0:
        source_fps = 30.0
    scene_fps = scene.render.fps / scene.render.fps_base
    frame_scale = scene_fps / source_fps
    action_name = f"{armature.name} | {animation.get('name') or virtual_path.rsplit('/', 1)[-1]}"
    action = bpy.data.actions.new(action_name)
    new_curve, action_slot = _action_curves(action, armature)
    action["ff7r_animation_virtual_path"] = virtual_path
    action["ff7r_skeleton_asset_path"] = skeleton_path
    action["ff7r_source_fps"] = source_fps
    action["ff7r_source_duration"] = float(animation.get("duration") or 0.0)

    keyed_bones = 0
    skipped_bones = 0
    key_count = 0
    worst_rest_error = 0.0
    forward_rotation = (
        skeleton_importer.Y_FORWARD_ROTATION
        if skeleton_importer.armature_face_forward(armature) == skeleton_importer.FACE_FORWARD_BLENDER
        else Matrix.Identity(4)
    )
    for track in animation.get("tracks") or []:
        bone_name = track.get("boneName")
        bone = armature.data.bones.get(bone_name) if bone_name else None
        if bone is None:
            skipped_bones += 1
            continue
        source_translations = list(track.get("translations") or [])
        source_rotations = list(track.get("rotations") or [])
        source_scales = list(track.get("scales") or [])
        num_frames = int(animation.get("numFrames") or 1)
        translation_frames = _key_times(
            source_translations, list(track.get("translationFrames") or []), num_frames
        )
        rotation_frames = _key_times(
            source_rotations, list(track.get("rotationFrames") or []), num_frames
        )
        scale_frames = _key_times(
            source_scales, list(track.get("scaleFrames") or []), num_frames
        )
        source_frames = sorted(set(translation_frames + rotation_frames + scale_frames))
        if not source_frames:
            continue
        bind_translation = _vector(track.get("bindTranslation") or (), (0.0, 0.0, 0.0))
        bind_rotation = tuple(track.get("bindRotation") or (0.0, 0.0, 0.0, 1.0))
        bind_scale = _vector(track.get("bindScale") or (), (1.0, 1.0, 1.0))
        sample_translation = _vector_sampler(
            source_translations, translation_frames, bind_translation
        )
        sample_rotation = _ue_quaternion_sampler(
            source_rotations, rotation_frames, bind_rotation
        )
        sample_scale = _vector_sampler(source_scales, scale_frames, bind_scale)
        bind_matrix = Matrix.LocRotScale(
            _ue_location(bind_translation), _quaternion(bind_rotation), bind_scale
        )
        basis_prefix = DISPLAY_CORRECTION_INVERSE @ bind_matrix.inverted_safe()
        display_target = (
            ROOT_DISPLAY_CORRECTION if bone.parent is None else DISPLAY_CORRECTION
        )
        worst_rest_error = max(worst_rest_error, _rest_convention_error(
            bone,
            bind_matrix,
            forward_rotation,
        ))
        bases = [
            _blender_basis_values(
                sample_translation(frame),
                sample_rotation(frame),
                sample_scale(frame),
                basis_prefix,
                display_target,
            )
            for frame in source_frames
        ]
        translations = [tuple(basis[0]) for basis in bases]
        rotations = [tuple(basis[1]) for basis in bases]
        scales = [tuple(basis[2]) for basis in bases]
        path = f'pose.bones["{bone.name}"]'
        key_count += _insert_keys(new_curve, bone.name, path + ".location", translations,
                                  source_frames, frame_scale, start_frame)
        key_count += _insert_keys(new_curve, bone.name, path + ".rotation_quaternion", rotations,
                                  source_frames, frame_scale, start_frame)
        key_count += _insert_keys(new_curve, bone.name, path + ".scale", scales,
                                  source_frames, frame_scale, start_frame)
        keyed_bones += 1

    if not key_count:
        bpy.data.actions.remove(action)
        raise ValueError("No animation tracks matched bones on the selected armature.")
    action.frame_start = start_frame
    action.frame_end = start_frame + max(0.0, float(animation.get("duration") or 0.0) * scene_fps)
    if replace_current_action:
        animation_data = armature.animation_data_create()
        animation_data.action = action
        if action_slot is not None:
            animation_data.action_slot = action_slot
    return action, keyed_bones, key_count, skipped_bones, worst_rest_error


class FF7R_REBIRTH_OT_apply_animation_game_packages(FF7R_LoggedOperator):
    bl_idname = "object.ff7r_rebirth_apply_animation_game_packages"
    bl_label = "Apply Rebirth Animation"
    bl_description = "Find AnimSequence assets made for the selected package armature and apply one as a Blender Action"
    bl_options = {'REGISTER', 'UNDO'}

    virtual_path: bpy.props.StringProperty(
        name="Animation",
        description="Only AnimSequence assets linked to this armature's Rebirth Skeleton are listed",
        search=_search_matching_animations,
        search_options={'SUGGESTION'},
    )
    start_frame: bpy.props.IntProperty(
        name="Start Frame",
        description="Blender frame for the beginning of the action",
        default=1,
    )
    replace_current_action: bpy.props.BoolProperty(
        name="Set as Active Action",
        description="Assign the imported action to the selected armature immediately",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'ARMATURE'

    def invoke(self, context, _event):
        armature = context.active_object
        skeleton_path = _selected_armature_skeleton_path(armature)
        if not skeleton_path:
            report(self,
                {'ERROR'},
                "The selected armature has no Rebirth Skeleton source. Import it from packages, or bind a package SkeletalMesh first.",
            )
            return {'CANCELLED'}
        prefs = game_packages._preferences(context)
        if prefs is None:
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        try:
            game_packages.refresh_animation_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
                skeleton_path,
            )
        except Exception as exc:
            print(f"[FF7R animation ERROR] Search failed for skeleton '{skeleton_path}':")
            traceback.print_exc()
            report(self, {'ERROR'}, f"Animation search failed: {exc}")
            return {'CANCELLED'}
        if not game_packages._VIRTUAL_ANIMATIONS:
            report(self, {'WARNING'}, "No AnimSequence assets were linked to this armature's Rebirth Skeleton.")
            return {'CANCELLED'}
        self.start_frame = context.scene.frame_current
        return context.window_manager.invoke_props_dialog(self, width=900)

    def draw(self, _context):
        layout = self.layout
        layout.label(text=f"{len(game_packages._VIRTUAL_ANIMATIONS):,} compatible AnimSequence asset(s) found", icon='ARMATURE_DATA')
        layout.prop(self, "virtual_path", icon='VIEWZOOM')
        layout.prop(self, "start_frame")
        layout.prop(self, "replace_current_action")
        layout.label(text="Keys use the scene frame rate and preserve the package rig's bone-roll convention.", icon='INFO')

    def execute(self, context):
        armature = context.active_object
        prefs = game_packages._preferences(context)
        if prefs is None or armature is None:
            report(self, {'ERROR'}, "FF7R Rebirth add-on preferences are unavailable.")
            return {'CANCELLED'}
        skeleton_path = _selected_armature_skeleton_path(armature)
        virtual_path = self.virtual_path.strip().replace("\\", "/").lstrip("/")
        if not skeleton_path:
            report(self, {'ERROR'}, "The selected armature has no Rebirth Skeleton source.")
            return {'CANCELLED'}
        try:
            compatible = game_packages.refresh_animation_index(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
                skeleton_path,
            )
            if virtual_path not in compatible:
                raise ValueError("Choose an animation from the compatible package search results.")
            with game_packages.PackageAssetSession(
                bpy.path.abspath(prefs.rebirth_install_root),
                bpy.path.abspath(prefs.rebirth_oodle_dll),
                bpy.path.abspath(prefs.rebirth_usmap_path),
            ) as session:
                animation = session.animation_asset(virtual_path)
        except Exception as exc:
            print(f"[FF7R animation ERROR] Import failed for '{virtual_path}':")
            traceback.print_exc()
            report(self, {'ERROR'}, f"Animation import failed: {exc}")
            return {'CANCELLED'}

        try:
            action, keyed_bones, key_count, skipped_bones, worst_rest_error = import_animation_asset(
                armature,
                virtual_path,
                animation,
                start_frame=self.start_frame,
                replace_current_action=self.replace_current_action,
                scene=context.scene,
            )
        except Exception as exc:
            report(self, {'ERROR'}, str(exc))
            return {'CANCELLED'}
        if worst_rest_error > REST_CONVENTION_TOLERANCE:
            report(self,
                {'WARNING'},
                f"'{armature.name}' rest pose differs from the animation's bind pose by "
                f"{worst_rest_error:.3f}; the keys will not land where the clip intends. "
                "Import the Skeleton from packages so the rig uses this add-on's bone frame.",
            )
        report(self,
            {'INFO'},
            f"Imported '{animation.get('name') or action.name}' to '{armature.name}': "
            f"{keyed_bones} bone(s), {key_count:,} channel key(s)"
            + (f"; skipped {skipped_bones} unavailable bone(s)" if skipped_bones else ""),
        )
        return {'FINISHED'}


CLASSES = (FF7R_REBIRTH_OT_apply_animation_game_packages,)
